#!/usr/bin/env python3
"""EPG MrG v0.2.53 - capa resiliente de Telefe y Star Channel sobre LATAM vigente.

Este archivo conserva el generador `build_latam_resilient.py` inmediatamente anterior
cargándolo desde el historial Git local y añade únicamente una política adicional:

    Telefe.ar: mi.tv -> GatoTV Telefe Argentina (fresco)
    Star-Channel.co: mi.tv -> GatoTV Colombia -> GatoTV Centro (fresco)

Telefe se interpreta en America/Argentina/Buenos_Aires. Star Channel usa tabla 24 h
y se interpreta en America/Bogota; Colombia y Ecuador comparten UTC-5. Todo se
normaliza a America/Guayaquil y no hay offsets manuales ni parrillas estáticas.

La carga desde Git salta wrappers previos y recupera el generador resiliente estable.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import date
from types import ModuleType
from typing import Any, Callable

EPG_MRG_LATAM_FALLBACKS_V053 = True
VERSION = "0.2.53"
TELEFE_ID = "Telefe.ar"
TELEFE_GATOTV_SLUG = "telefe_argentina"
TELEFE_GATOTV_SOURCE_URL = f"https://www.gatotv.com/canal/{TELEFE_GATOTV_SLUG}"
TELEFE_SOURCE_TIMEZONE = "America/Argentina/Buenos_Aires"
TELEFE_OUTPUT_TIMEZONE = "America/Guayaquil"
TELEFE_MIN_PROGRAMMES = 5

TELEFE_LAST_SOURCE_MODE: str | None = None
TELEFE_LAST_SOURCE_URL: str | None = None
TELEFE_LAST_SOURCE_TIMEZONE: str | None = None
TELEFE_LAST_LOADED_DAYS = 0
TELEFE_LAST_DAILY_COUNTS: dict[str, int] = {}
TELEFE_LAST_MITV_ERROR: str | None = None

STAR_CHANNEL_ID = "Star-Channel.co"
STAR_GATOTV_CANDIDATES = ("star_channel_colombia", "star_channel_centro")
STAR_SOURCE_TIMEZONE = "America/Bogota"
STAR_OUTPUT_TIMEZONE = "America/Guayaquil"
STAR_MIN_PROGRAMMES = 5
STAR_LAST_SOURCE_MODE: str | None = None
STAR_LAST_SOURCE_URL: str | None = None
STAR_LAST_SOURCE_TIMEZONE: str | None = None
STAR_LAST_LOADED_DAYS = 0
STAR_LAST_DAILY_COUNTS: dict[str, int] = {}
STAR_LAST_MITV_ERROR: str | None = None
STAR_LAST_GATOTV_ERRORS: list[str] = []


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_base_bytes_from_git() -> bytes:
    """Obtiene la última base histórica, saltando wrappers v0.2.52/v0.2.53."""
    override = os.environ.get("EPG_MRG_BASE_LATAM_RESILIENT")
    if override:
        path = Path(override)
        data = path.read_bytes()
        if not data:
            raise RuntimeError(f"Base LATAM de prueba vacía: {path}")
        return data

    root = _repo_root()
    try:
        commits = subprocess.check_output(
            [
                "git", "log", "--format=%H", "--all", "--",
                "scripts/build_latam_resilient.py",
            ],
            cwd=root,
            text=True,
            stderr=subprocess.STDOUT,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "v0.2.53 no pudo consultar el historial Git de build_latam_resilient.py."
        ) from exc

    excluded_markers = (
        b"EPG_MRG_TELEFE_WRAPPER_V052",
        b"EPG_MRG_LATAM_FALLBACKS_V053",
    )
    for commit in commits:
        if not commit.strip():
            continue
        try:
            data = subprocess.check_output(
                ["git", "show", f"{commit}:scripts/build_latam_resilient.py"],
                cwd=root,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        if data and not any(marker in data for marker in excluded_markers):
            return data
    raise RuntimeError(
        "v0.2.53 no encontró en el historial Git una base estable utilizable de "
        "scripts/build_latam_resilient.py."
    )


def _load_base_module() -> ModuleType:
    data = _read_base_bytes_from_git()
    cache_dir = Path(tempfile.gettempdir()) / "epg-mrg-v053"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "build_latam_resilient_base.py"
    path.write_bytes(data)
    spec = importlib.util.spec_from_file_location("_epg_mrg_latam_resilient_base_v053", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v0.2.53 no pudo crear el módulo base LATAM.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_BASE = _load_base_module()
_REAL_MITV_SCRAPER: Callable[..., Any] = _BASE.ORIGINAL_MITV_SCRAPER


def _telefe_gatotv_config():
    """Telefe Argentina: tabla 24 h del país de origen, nunca offset manual."""
    return _BASE.latam.GatoTvChannel(
        TELEFE_GATOTV_SLUG,
        TELEFE_ID,
        ("Telefe", "Telefé", "Telefe Argentina", "Telefé Argentina"),
        "https://telefe.com/",
        source_timezone=TELEFE_SOURCE_TIMEZONE,
        prefer_ampm_local=False,
    )


def _star_gatotv_config(slug: str):
    """Star Channel: obliga tabla 24 h y reloj Colombia (UTC-5)."""
    return _BASE.latam.GatoTvChannel(
        slug,
        STAR_CHANNEL_ID,
        ("Star Channel", "STAR Channel", "Star Channel Colombia", "Star Channel Centro"),
        "https://www.star-latam.com/star-channel/",
        source_timezone=STAR_SOURCE_TIMEZONE,
        prefer_ampm_local=False,
    )


def _mitv_with_channel_fallbacks(
    *,
    country: str,
    slug: str,
    channel_id: str,
    start_date: date,
    local_days: int = 2,
    pause_seconds: float = 0.0,
):
    """mi.tv primario; Telefe y Star Channel tienen fallback GatoTV fresco."""
    global TELEFE_LAST_SOURCE_MODE, TELEFE_LAST_SOURCE_URL
    global TELEFE_LAST_SOURCE_TIMEZONE, TELEFE_LAST_LOADED_DAYS
    global TELEFE_LAST_DAILY_COUNTS, TELEFE_LAST_MITV_ERROR

    if channel_id == STAR_CHANNEL_ID:
        return _star_channel_fallback(
            country=country, slug=slug, channel_id=channel_id, start_date=start_date,
            local_days=local_days, pause_seconds=pause_seconds,
        )
    if channel_id != TELEFE_ID:
        return _REAL_MITV_SCRAPER(
            country=country,
            slug=slug,
            channel_id=channel_id,
            start_date=start_date,
            local_days=local_days,
            pause_seconds=pause_seconds,
        )

    TELEFE_LAST_SOURCE_MODE = None
    TELEFE_LAST_SOURCE_URL = None
    TELEFE_LAST_SOURCE_TIMEZONE = None
    TELEFE_LAST_LOADED_DAYS = 0
    TELEFE_LAST_DAILY_COUNTS = {}
    TELEFE_LAST_MITV_ERROR = None

    try:
        programmes, loaded_days = _REAL_MITV_SCRAPER(
            country=country,
            slug=slug,
            channel_id=channel_id,
            start_date=start_date,
            local_days=local_days,
            pause_seconds=pause_seconds,
        )
    except RuntimeError as exc:
        TELEFE_LAST_MITV_ERROR = str(exc)
        _BASE.latam.epg.warn(
            "Telefe.ar: mi.tv no cubrió la ventana local solicitada; "
            f"se probará GatoTV fresco {TELEFE_GATOTV_SOURCE_URL}. Detalle: {exc}"
        )
    else:
        TELEFE_LAST_SOURCE_MODE = "mi-tv-primary"
        TELEFE_LAST_SOURCE_URL = f"https://mi.tv/{country}/canales/{slug}"
        TELEFE_LAST_SOURCE_TIMEZONE = "UTC"
        TELEFE_LAST_LOADED_DAYS = int(loaded_days)
        _BASE.latam.epg.log(
            f"Telefe.ar: mi.tv primario utilizable; días_fuente={loaded_days}; "
            "UTC->America/Guayaquil; ajuste_manual=0min."
        )
        return programmes, loaded_days

    try:
        programmes, loaded_days, daily_counts = _BASE.latam.scrape_gatotv_channel(
            _telefe_gatotv_config(),
            start_date,
            local_days,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            "Telefe.ar: mi.tv quedó incompleto y GatoTV Telefe Argentina tampoco "
            f"entregó programación utilizable. mi.tv={TELEFE_LAST_MITV_ERROR}; "
            f"GatoTV={exc}"
        ) from exc

    if int(loaded_days) < 1 or len(programmes) < TELEFE_MIN_PROGRAMMES:
        raise RuntimeError(
            "Telefe.ar: GatoTV devolvió programación insuficiente después del fallo "
            f"de mi.tv ({len(programmes)} emisiones; días={loaded_days})."
        )

    TELEFE_LAST_SOURCE_MODE = "gatotv-live"
    TELEFE_LAST_SOURCE_URL = TELEFE_GATOTV_SOURCE_URL
    TELEFE_LAST_SOURCE_TIMEZONE = TELEFE_SOURCE_TIMEZONE
    TELEFE_LAST_LOADED_DAYS = int(loaded_days)
    TELEFE_LAST_DAILY_COUNTS = dict(daily_counts)
    _BASE.latam.epg.log(
        f"Telefe.ar: respaldo GatoTV activo; emisiones={len(programmes)}; "
        f"días={loaded_days}; {TELEFE_SOURCE_TIMEZONE}->{TELEFE_OUTPUT_TIMEZONE}; "
        "ajuste_manual=0min."
    )
    # Contrato esperado por build_latam_epg para los canales mi.tv.
    return programmes, loaded_days


def _star_channel_fallback(
    *, country: str, slug: str, channel_id: str, start_date: date,
    local_days: int = 2, pause_seconds: float = 0.0,
):
    global STAR_LAST_SOURCE_MODE, STAR_LAST_SOURCE_URL, STAR_LAST_SOURCE_TIMEZONE
    global STAR_LAST_LOADED_DAYS, STAR_LAST_DAILY_COUNTS, STAR_LAST_MITV_ERROR
    global STAR_LAST_GATOTV_ERRORS

    STAR_LAST_SOURCE_MODE = None
    STAR_LAST_SOURCE_URL = None
    STAR_LAST_SOURCE_TIMEZONE = None
    STAR_LAST_LOADED_DAYS = 0
    STAR_LAST_DAILY_COUNTS = {}
    STAR_LAST_MITV_ERROR = None
    STAR_LAST_GATOTV_ERRORS = []

    try:
        programmes, loaded_days = _REAL_MITV_SCRAPER(
            country=country, slug=slug, channel_id=channel_id, start_date=start_date,
            local_days=local_days, pause_seconds=pause_seconds,
        )
    except RuntimeError as exc:
        STAR_LAST_MITV_ERROR = str(exc)
        _BASE.latam.epg.warn(
            "Star-Channel.co: mi.tv no cubrió la ventana local; se probarán "
            "GatoTV Colombia y GatoTV Centro en tabla 24 h. " + f"Detalle: {exc}"
        )
    else:
        STAR_LAST_SOURCE_MODE = "mi-tv-primary"
        STAR_LAST_SOURCE_URL = f"https://mi.tv/{country}/canales/{slug}"
        STAR_LAST_SOURCE_TIMEZONE = "UTC"
        STAR_LAST_LOADED_DAYS = int(loaded_days)
        _BASE.latam.epg.log(
            f"Star-Channel.co: mi.tv primario utilizable; días_fuente={loaded_days}; "
            "UTC->America/Guayaquil; ajuste_manual=0min."
        )
        return programmes, loaded_days

    for candidate in STAR_GATOTV_CANDIDATES:
        url = f"https://www.gatotv.com/canal/{candidate}"
        try:
            programmes, loaded_days, daily_counts = _BASE.latam.scrape_gatotv_channel(
                _star_gatotv_config(candidate), start_date, local_days
            )
        except RuntimeError as exc:
            STAR_LAST_GATOTV_ERRORS.append(f"{candidate}: {exc}")
            continue
        if int(loaded_days) < 1 or len(programmes) < STAR_MIN_PROGRAMMES:
            STAR_LAST_GATOTV_ERRORS.append(
                f"{candidate}: programación insuficiente "
                f"({len(programmes)} emisiones; días={loaded_days})"
            )
            continue
        STAR_LAST_SOURCE_MODE = f"gatotv-{candidate}"
        STAR_LAST_SOURCE_URL = url
        STAR_LAST_SOURCE_TIMEZONE = STAR_SOURCE_TIMEZONE
        STAR_LAST_LOADED_DAYS = int(loaded_days)
        STAR_LAST_DAILY_COUNTS = dict(daily_counts)
        _BASE.latam.epg.log(
            f"Star-Channel.co: respaldo GatoTV activo slug={candidate}; "
            f"emisiones={len(programmes)}; días={loaded_days}; "
            f"{STAR_SOURCE_TIMEZONE}->{STAR_OUTPUT_TIMEZONE}; ajuste_manual=0min."
        )
        return programmes, loaded_days

    details = "; ".join(STAR_LAST_GATOTV_ERRORS) or "sin detalle"
    raise RuntimeError(
        "Star-Channel.co: mi.tv quedó incompleto y los respaldos GatoTV tampoco "
        f"entregaron programación utilizable. mi.tv={STAR_LAST_MITV_ERROR}; "
        f"GatoTV=[{details}]"
    )


# El wrapper DW de la base llama a ORIGINAL_MITV_SCRAPER; al sustituirlo aquí,
# Telefe y Star Channel obtienen fallback sin alterar la lógica especial de DW.
_BASE.ORIGINAL_MITV_SCRAPER = _mitv_with_channel_fallbacks


def _annotate_telefe_status(output_dir: Path) -> None:
    path = output_dir / "latam-status.json"
    if not path.is_file() or TELEFE_LAST_SOURCE_MODE is None:
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    status["telefe_hotfix_version"] = VERSION
    status["telefe_source_policy"] = {
        "mode": TELEFE_LAST_SOURCE_MODE,
        "source": TELEFE_LAST_SOURCE_URL,
        "source_timezone": TELEFE_LAST_SOURCE_TIMEZONE,
        "output_timezone": TELEFE_OUTPUT_TIMEZONE,
        "manual_offset_minutes": 0,
        "loaded_days": TELEFE_LAST_LOADED_DAYS,
        "mi_tv_error": TELEFE_LAST_MITV_ERROR,
        "gatotv_fallback": TELEFE_GATOTV_SOURCE_URL,
        "gatotv_source_timezone": TELEFE_SOURCE_TIMEZONE,
        "daily_counts": dict(TELEFE_LAST_DAILY_COUNTS),
    }

    if TELEFE_LAST_SOURCE_MODE == "gatotv-live":
        sources = status.get("sources")
        if isinstance(sources, dict):
            mi_tv = sources.get("mi_tv")
            if isinstance(mi_tv, dict):
                mi_tv.pop(TELEFE_ID, None)
            gato_tv = sources.get("gato_tv")
            if isinstance(gato_tv, dict):
                gato_tv[TELEFE_ID] = TELEFE_GATOTV_SOURCE_URL
        mitv_days = status.get("mitv_source_days")
        if isinstance(mitv_days, dict):
            mitv_days.pop(TELEFE_ID, None)
        gatotv_days = status.get("gatotv_source_days")
        if isinstance(gatotv_days, dict):
            gatotv_days[TELEFE_ID] = TELEFE_LAST_LOADED_DAYS
        daily = status.get("gatotv_daily_counts")
        if isinstance(daily, dict):
            daily[TELEFE_ID] = dict(TELEFE_LAST_DAILY_COUNTS)
        tzs = status.get("gatotv_source_timezones")
        if isinstance(tzs, dict):
            tzs[TELEFE_ID] = TELEFE_SOURCE_TIMEZONE
        ampm = status.get("gatotv_ampm_local_preferred")
        if isinstance(ampm, dict):
            ampm[TELEFE_ID] = False

    path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _annotate_star_status(output_dir: Path) -> None:
    path = output_dir / "latam-status.json"
    if not path.is_file() or STAR_LAST_SOURCE_MODE is None:
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    status["star_channel_hotfix_version"] = VERSION
    status["star_channel_source_policy"] = {
        "mode": STAR_LAST_SOURCE_MODE,
        "source": STAR_LAST_SOURCE_URL,
        "source_timezone": STAR_LAST_SOURCE_TIMEZONE,
        "output_timezone": STAR_OUTPUT_TIMEZONE,
        "manual_offset_minutes": 0,
        "loaded_days": STAR_LAST_LOADED_DAYS,
        "mi_tv_error": STAR_LAST_MITV_ERROR,
        "gatotv_candidates": [f"https://www.gatotv.com/canal/{x}" for x in STAR_GATOTV_CANDIDATES],
        "gatotv_errors": list(STAR_LAST_GATOTV_ERRORS),
        "daily_counts": dict(STAR_LAST_DAILY_COUNTS),
    }
    if STAR_LAST_SOURCE_MODE.startswith("gatotv-"):
        endpoint = status.get("mitv_endpoint_time_channels")
        if isinstance(endpoint, dict):
            endpoint.pop(STAR_CHANNEL_ID, None)
        sources = status.get("sources")
        if isinstance(sources, dict):
            mi_tv = sources.get("mi_tv")
            if isinstance(mi_tv, dict):
                mi_tv.pop(STAR_CHANNEL_ID, None)
            gato_tv = sources.get("gato_tv")
            if isinstance(gato_tv, dict):
                gato_tv[STAR_CHANNEL_ID] = STAR_LAST_SOURCE_URL
        mitv_days = status.get("mitv_source_days")
        if isinstance(mitv_days, dict):
            mitv_days.pop(STAR_CHANNEL_ID, None)
        gatotv_days = status.get("gatotv_source_days")
        if isinstance(gatotv_days, dict):
            gatotv_days[STAR_CHANNEL_ID] = STAR_LAST_LOADED_DAYS
        daily = status.get("gatotv_daily_counts")
        if isinstance(daily, dict):
            daily[STAR_CHANNEL_ID] = dict(STAR_LAST_DAILY_COUNTS)
        tzs = status.get("gatotv_source_timezones")
        if isinstance(tzs, dict):
            tzs[STAR_CHANNEL_ID] = STAR_SOURCE_TIMEZONE
        ampm = status.get("gatotv_ampm_local_preferred")
        if isinstance(ampm, dict):
            ampm[STAR_CHANNEL_ID] = False
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _assert_star_output(output_dir: Path) -> None:
    from lxml import etree
    xml_path = output_dir / "latam.xml"
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=True)
    root = etree.parse(str(xml_path), parser).getroot()
    channels = root.xpath("./channel[@id=$channel_id]", channel_id=STAR_CHANNEL_ID)
    if len(channels) != 1:
        raise RuntimeError(f"v0.2.53 esperaba exactamente un canal {STAR_CHANNEL_ID}.")
    programmes = root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_CHANNEL_ID)
    if len(programmes) < STAR_MIN_PROGRAMMES:
        raise RuntimeError(f"v0.2.53: Star-Channel.co quedó con solo {len(programmes)} emisiones.")
    for item in programmes:
        if not item.get("start", "").endswith(" -0500"):
            raise RuntimeError(f"Star-Channel.co start no Guayaquil: {item.get('start')}")
        if not item.get("stop", "").endswith(" -0500"):
            raise RuntimeError(f"Star-Channel.co stop no Guayaquil: {item.get('stop')}")


def _assert_telefe_output(output_dir: Path) -> None:
    from lxml import etree

    xml_path = output_dir / "latam.xml"
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    root = etree.parse(str(xml_path), parser).getroot()
    channels = root.xpath("./channel[@id=$channel_id]", channel_id=TELEFE_ID)
    if len(channels) != 1:
        raise RuntimeError(f"v0.2.53 esperaba exactamente un canal {TELEFE_ID}.")
    programmes = root.xpath("./programme[@channel=$channel_id]", channel_id=TELEFE_ID)
    if len(programmes) < TELEFE_MIN_PROGRAMMES:
        raise RuntimeError(
            f"v0.2.53: Telefe.ar quedó con solo {len(programmes)} emisiones."
        )
    for item in programmes:
        if not item.get("start", "").endswith(" -0500"):
            raise RuntimeError(f"Telefe.ar start no Guayaquil: {item.get('start')}")
        if not item.get("stop", "").endswith(" -0500"):
            raise RuntimeError(f"Telefe.ar stop no Guayaquil: {item.get('stop')}")


def self_test() -> None:
    """Ejecuta pruebas heredadas y verifica la nueva ruta Telefe -> GatoTV."""
    global _REAL_MITV_SCRAPER

    # Primero todas las regresiones históricas del generador resiliente.
    _BASE.self_test()

    real_scraper = _REAL_MITV_SCRAPER
    real_gatotv = _BASE.latam.scrape_gatotv_channel
    seen: list[str] = []

    def fail_telefe(**kwargs):
        seen.append(kwargs["channel_id"])
        if kwargs["channel_id"] == TELEFE_ID:
            raise RuntimeError(
                "mi.tv Telefe.ar: no se obtuvo programación suficiente "
                "(fechas UTC cargadas: 1/3)."
            )
        return [object()] * 8, 2

    def fake_gatotv(config, start_date, days):
        assert config.channel_id == TELEFE_ID
        assert config.slug == TELEFE_GATOTV_SLUG
        assert config.source_timezone == TELEFE_SOURCE_TIMEZONE
        assert config.prefer_ampm_local is False
        assert days == 2
        return [object()] * 12, 2, {
            "2026-09-09": 6,
            "2026-09-10": 6,
        }

    try:
        _REAL_MITV_SCRAPER = fail_telefe
        _BASE.latam.scrape_gatotv_channel = fake_gatotv
        programmes, loaded = _mitv_with_channel_fallbacks(
            country="ar",
            slug="telefe",
            channel_id=TELEFE_ID,
            start_date=date(2026, 9, 9),
            local_days=2,
            pause_seconds=0,
        )
        assert len(programmes) == 12
        assert loaded == 2
        assert seen == [TELEFE_ID]
        assert TELEFE_LAST_SOURCE_MODE == "gatotv-live"
        assert TELEFE_LAST_SOURCE_URL == TELEFE_GATOTV_SOURCE_URL
        assert TELEFE_LAST_SOURCE_TIMEZONE == TELEFE_SOURCE_TIMEZONE
        assert TELEFE_LAST_DAILY_COUNTS == {"2026-09-09": 6, "2026-09-10": 6}
    finally:
        _REAL_MITV_SCRAPER = real_scraper
        _BASE.latam.scrape_gatotv_channel = real_gatotv

    # Simula exactamente Star Channel 1/3 y Colombia vacío -> Centro utilizable.
    calls: list[str] = []
    def fail_star(**kwargs):
        if kwargs["channel_id"] == STAR_CHANNEL_ID:
            raise RuntimeError(
                "mi.tv Star-Channel.co: no se obtuvo programación suficiente "
                "para la ventana local solicitada (fechas UTC cargadas: 1/3)."
            )
        return [object()] * 8, 2
    def fake_star_gatotv(config, start_date, days):
        calls.append(config.slug)
        assert config.channel_id == STAR_CHANNEL_ID
        assert config.source_timezone == STAR_SOURCE_TIMEZONE
        assert config.prefer_ampm_local is False
        if config.slug == "star_channel_colombia":
            raise RuntimeError("sin parrilla Colombia")
        assert config.slug == "star_channel_centro"
        return [object()] * 18, 2, {"2026-09-09": 9, "2026-09-10": 9}
    try:
        _REAL_MITV_SCRAPER = fail_star
        _BASE.latam.scrape_gatotv_channel = fake_star_gatotv
        programmes, loaded = _mitv_with_channel_fallbacks(
            country="co", slug="fox", channel_id=STAR_CHANNEL_ID,
            start_date=date(2026, 9, 9), local_days=2, pause_seconds=0,
        )
        assert len(programmes) == 18
        assert loaded == 2
        assert calls == ["star_channel_colombia", "star_channel_centro"]
        assert STAR_LAST_SOURCE_MODE == "gatotv-star_channel_centro"
        assert STAR_LAST_SOURCE_TIMEZONE == STAR_SOURCE_TIMEZONE
    finally:
        _REAL_MITV_SCRAPER = real_scraper
        _BASE.latam.scrape_gatotv_channel = real_gatotv

    print(
        "Prueba v0.2.53 correcta: Telefe y Star Channel conservan mi.tv como primario; "
        "Star Channel 1/3 prueba GatoTV Colombia y luego Centro, siempre tabla 24 h, "
        "America/Bogota -> America/Guayaquil, offset manual=0."
    )


def main() -> int:
    result = _BASE.main()
    if result == 0:
        # _BASE.main ya hizo sus validaciones heredadas.
        output_dir = _BASE._output_dir(sys.argv[1:])
        _annotate_telefe_status(output_dir)
        _annotate_star_status(output_dir)
        _assert_telefe_output(output_dir)
        _assert_star_output(output_dir)
    return result


# Reexporta la API que consume el validador final del workflow.
for _name in (
    "EXPECTED_LATAM_IDS",
    "EXPECTED_CHANNELS",
    "REQUIRED_PROGRAMME_IDS",
    "STAR_TVE_ID",
    "ANTENA3_ID",
    "STAR_CHANNEL_ID",
    "WARNER_CHANNEL_ID",
    "HBO_FAMILY_ID",
    "DW_ID",
):
    if hasattr(_BASE, _name):
        globals()[_name] = getattr(_BASE, _name)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, _BASE.etree.XMLSyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

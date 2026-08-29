#!/usr/bin/env python3
"""Construye LATAM sin STAR TVE y con fuentes resilientes para canales mi.tv.

Reglas vigentes desde v0.2.35:
- ``TVEStarHD.es`` permanece completamente excluido.
- Antena 3, Star Channel, Warner Channel y HBO Family se obtienen desde el
  endpoint asíncrono de mi.tv, interpretado como UTC y convertido a
  ``America/Guayaquil`` por ``mitv_utc``.
- ``Deutsche.Welle.cl`` conserva su tvg-id y posición canónica. Para DW se prueba
  primero ``deutsche-welle-espanol`` y luego ``deutsche-welle-amerika`` en mi.tv.
  Si ambos endpoints están vacíos/incompatibles, se usa exclusivamente la señal
  española ``dw_latinoamerica`` de GatoTV para la misma ventana local.
- No se aplican offsets manuales.
"""

from __future__ import annotations

import json
import sys
from dataclasses import fields as dataclass_fields, is_dataclass, replace as dataclass_replace
from datetime import date
from pathlib import Path
from typing import Callable

from lxml import etree

import build_latam_epg as latam
import mitv_utc

STAR_TVE_ID = "TVEStarHD.es"
ANTENA3_ID = "Antena3-America.co"
STAR_CHANNEL_ID = "Star-Channel.co"
WARNER_CHANNEL_ID = "Warner-channel.co"
HBO_FAMILY_ID = "HBO-Family.co"
DW_ID = "Deutsche.Welle.cl"
DW_OLD_SLUG = "deutsche-welle"
DW_PRIMARY_SLUG = "deutsche-welle-espanol"
DW_ALTERNATE_SLUG = "deutsche-welle-amerika"
DW_OLD_SOURCE_URL = "https://mi.tv/cl/canales/deutsche-welle"
DW_PRIMARY_SOURCE_URL = f"https://mi.tv/cl/canales/{DW_PRIMARY_SLUG}"
DW_ALTERNATE_SOURCE_URL = f"https://mi.tv/cl/canales/{DW_ALTERNATE_SLUG}"
DW_GATOTV_SLUG = "dw_latinoamerica"
DW_GATOTV_SOURCE_URL = f"https://www.gatotv.com/canal/{DW_GATOTV_SLUG}"
DW_MITV_CANDIDATES = (DW_PRIMARY_SLUG, DW_ALTERNATE_SLUG)
ADDED_MITV_IDS = frozenset({ANTENA3_ID, STAR_CHANNEL_ID, WARNER_CHANNEL_ID, HBO_FAMILY_ID})
REQUIRED_PROGRAMME_IDS = (
    DW_ID,
    ANTENA3_ID,
    STAR_CHANNEL_ID,
    WARNER_CHANNEL_ID,
    HBO_FAMILY_ID,
)
EXPECTED_CHANNELS = 30
EXPECTED_LATAM_IDS: tuple[str, ...] = (
    "Canal.TC.Televisión.ec",
    "Canal.Gamavisión.ec",
    "Canal.RTS.ec",
    "Canal.TVE.Internacional.(Televisión.Española).ec",
    "TeleamazonasQuito.ec",
    "TeleamazonasGuayaquil.ec",
    "Ecuavisa.ec",
    "EcuavisaInternacional.ec",
    "TVC.ec",
    "Canal.CNN.en.Español.ec",
    "NTN24.co",
    "CanalRCN.co",
    "CaracolTV.co",
    "Canal.Elgourmet.ec",
    "Canal.History.co",
    "Canal.History.2.co",
    "TV.Publica.canal.7.ar",
    "Telefe.ar",
    DW_ID,
    "hgtv.ar",
    "France24Espanol.fr",
    ANTENA3_ID,
    STAR_CHANNEL_ID,
    WARNER_CHANNEL_ID,
    HBO_FAMILY_ID,
    "Canal24Horas.es",
    "La1.es",
    "Clan.es",
    "MakroDigitalTV.ec",
    "Canal.Ecuador.TV.ec",
)
ADDED_MITV_CHANNELS: tuple[latam.MitvChannel, ...] = (
    latam.MitvChannel(
        "co",
        "antena3",
        ANTENA3_ID,
        ("Antena 3", "Antena3"),
        "https://mi.tv/co/canales/antena3",
    ),
    latam.MitvChannel(
        "co",
        "fox",
        STAR_CHANNEL_ID,
        ("Star Channel", "STAR Channel"),
        "https://mi.tv/co/canales/fox",
    ),
    latam.MitvChannel(
        "co",
        "warner",
        WARNER_CHANNEL_ID,
        ("Warner Channel", "Warner"),
        "https://mi.tv/co/canales/warner",
    ),
    latam.MitvChannel(
        "co",
        "hbo-family",
        HBO_FAMILY_ID,
        ("HBO Family",),
        "https://mi.tv/co/canales/hbo-family",
    ),
)

# Se guarda la función real de mitv_utc antes de sustituir el símbolo global que
# build_latam_epg usa en tiempo de ejecución. Así el wrapper nunca se llama a sí
# mismo y configure_channels() es idempotente.
ORIGINAL_MITV_SCRAPER: Callable = mitv_utc.scrape_mitv_channel

DW_LAST_SOURCE_MODE: str | None = None
DW_LAST_SOURCE_URL: str | None = None
DW_LAST_SOURCE_TIMEZONE: str | None = None
DW_LAST_LOADED_DAYS = 0
DW_LAST_DAILY_COUNTS: dict[str, int] = {}
DW_LAST_MITV_ERRORS: list[str] = []


def _arg_path(argv: list[str], name: str, default: Path) -> Path:
    prefix = name + "="
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return Path(argv[index + 1])
        if value.startswith(prefix):
            return Path(value.split("=", 1)[1])
    return default


def _output_dir(argv: list[str]) -> Path:
    return _arg_path(argv, "--output", Path("public"))


def _replace_dw_mitv_config(config: latam.MitvChannel) -> latam.MitvChannel:
    """Normaliza solo el slug/URL primario de DW, preservando demás campos."""
    if is_dataclass(config):
        updates: dict[str, object] = {}
        for field in dataclass_fields(config):
            value = getattr(config, field.name)
            if field.name == "slug":
                updates[field.name] = DW_PRIMARY_SLUG
            elif value == DW_OLD_SOURCE_URL:
                updates[field.name] = DW_PRIMARY_SOURCE_URL
        if not updates:
            raise RuntimeError("No se pudo identificar el slug de DW en MitvChannel.")
        return dataclass_replace(config, **updates)

    if hasattr(config, "_asdict") and hasattr(config, "_replace"):
        values = config._asdict()
        updates = {}
        for name, value in values.items():
            if name == "slug":
                updates[name] = DW_PRIMARY_SLUG
            elif value == DW_OLD_SOURCE_URL:
                updates[name] = DW_PRIMARY_SOURCE_URL
        if not updates:
            raise RuntimeError("No se pudo identificar el slug de DW en MitvChannel.")
        return config._replace(**updates)

    try:
        values = list(config)
    except TypeError as exc:
        raise RuntimeError("Tipo MitvChannel no soportado para normalizar DW.") from exc
    if len(values) < 2:
        raise RuntimeError("MitvChannel de DW no contiene suficientes campos.")
    values[1] = DW_PRIMARY_SLUG
    if len(values) >= 5 and values[4] == DW_OLD_SOURCE_URL:
        values[4] = DW_PRIMARY_SOURCE_URL
    return latam.MitvChannel(*values)


def _dw_gatotv_config() -> latam.GatoTvChannel:
    """Configuración de respaldo para la señal DW en español de Latinoamérica."""
    return latam.GatoTvChannel(
        DW_GATOTV_SLUG,
        DW_ID,
        ("DW (Latinoamérica)", "Deutsche Welle Español", "DW Español"),
        "https://www.dw.com/es/",
    )


def scrape_mitv_with_dw_fallback(
    *,
    country: str,
    slug: str,
    channel_id: str,
    start_date: date,
    local_days: int = mitv_utc.MITV_LOCAL_MAX_DAYS,
    pause_seconds: float = mitv_utc.MITV_REQUEST_PAUSE_SECONDS,
):
    """Usa mi.tv normalmente; DW prueba dos IDs y después GatoTV Latinoamérica."""
    global DW_LAST_SOURCE_MODE, DW_LAST_SOURCE_URL, DW_LAST_SOURCE_TIMEZONE
    global DW_LAST_LOADED_DAYS, DW_LAST_DAILY_COUNTS, DW_LAST_MITV_ERRORS

    if channel_id != DW_ID:
        return ORIGINAL_MITV_SCRAPER(
            country=country,
            slug=slug,
            channel_id=channel_id,
            start_date=start_date,
            local_days=local_days,
            pause_seconds=pause_seconds,
        )

    DW_LAST_SOURCE_MODE = None
    DW_LAST_SOURCE_URL = None
    DW_LAST_SOURCE_TIMEZONE = None
    DW_LAST_LOADED_DAYS = 0
    DW_LAST_DAILY_COUNTS = {}
    DW_LAST_MITV_ERRORS = []

    # Aunque la configuración venga de una versión antigua, la política v0.2.35
    # prueba explícitamente los dos IDs que mi.tv mantiene para DW en Chile.
    for index, candidate_slug in enumerate(DW_MITV_CANDIDATES):
        try:
            programmes, loaded_days = ORIGINAL_MITV_SCRAPER(
                country="cl",
                slug=candidate_slug,
                channel_id=channel_id,
                start_date=start_date,
                local_days=local_days,
                pause_seconds=pause_seconds,
            )
        except RuntimeError as exc:
            message = f"{candidate_slug}: {exc}"
            DW_LAST_MITV_ERRORS.append(message)
            if index + 1 < len(DW_MITV_CANDIDATES):
                latam.epg.warn(
                    f"DW: mi.tv {candidate_slug} no entregó parrilla utilizable; "
                    f"se probará {DW_MITV_CANDIDATES[index + 1]}."
                )
            continue

        DW_LAST_SOURCE_MODE = (
            "mi-tv-primary" if candidate_slug == DW_PRIMARY_SLUG else "mi-tv-alternate"
        )
        DW_LAST_SOURCE_URL = f"https://mi.tv/cl/canales/{candidate_slug}"
        DW_LAST_SOURCE_TIMEZONE = "UTC"
        DW_LAST_LOADED_DAYS = loaded_days
        latam.epg.log(
            f"DW: fuente seleccionada={DW_LAST_SOURCE_MODE}; slug={candidate_slug}; "
            f"fechas_fuente={loaded_days}; UTC->America/Guayaquil; ajuste_manual=0min."
        )
        return programmes, loaded_days

    latam.epg.warn(
        "DW: los dos IDs de mi.tv Chile quedaron sin parrilla utilizable; "
        f"se usará GatoTV {DW_GATOTV_SOURCE_URL} para la misma ventana local."
    )
    try:
        programmes, loaded_days, daily_counts = latam.scrape_gatotv_channel(
            _dw_gatotv_config(),
            start_date,
            local_days,
        )
    except RuntimeError as exc:
        details = "; ".join(DW_LAST_MITV_ERRORS) or "sin detalle"
        raise RuntimeError(
            "Deutsche.Welle.cl: fallaron ambos IDs de mi.tv y el respaldo "
            f"GatoTV. mi.tv=[{details}]; GatoTV={exc}"
        ) from exc

    if loaded_days < 1 or len(programmes) < 5:
        raise RuntimeError(
            "Deutsche.Welle.cl: GatoTV devolvió programación insuficiente "
            f"({len(programmes)} emisiones; días={loaded_days})."
        )

    DW_LAST_SOURCE_MODE = "gatotv-live"
    DW_LAST_SOURCE_URL = DW_GATOTV_SOURCE_URL
    DW_LAST_SOURCE_TIMEZONE = "America/Guayaquil"
    DW_LAST_LOADED_DAYS = loaded_days
    DW_LAST_DAILY_COUNTS = dict(daily_counts)
    latam.epg.log(
        f"DW: respaldo GatoTV activo; emisiones={len(programmes)}; "
        f"días={loaded_days}; reloj=America/Guayaquil; ajuste_manual=0min."
    )
    # build_latam_epg espera el contrato de mi.tv: (programmes, loaded_days).
    return programmes, loaded_days


def configure_channels() -> None:
    """Retira STAR TVE, normaliza DW y añade los cuatro canales mi.tv extra."""
    latam.GATOTV_CHANNELS = tuple(
        config for config in latam.GATOTV_CHANNELS if config.channel_id != STAR_TVE_ID
    )

    patched_mitv_channels: list[latam.MitvChannel] = []
    dw_matches = 0
    for config in latam.MITV_CHANNELS:
        if config.channel_id == DW_ID:
            config = _replace_dw_mitv_config(config)
            dw_matches += 1
        patched_mitv_channels.append(config)
    if dw_matches != 1:
        raise RuntimeError(
            f"Se esperaba exactamente una configuración mi.tv para {DW_ID}; "
            f"obtenidas={dw_matches}."
        )

    latam.MITV_CHANNELS = tuple(
        config for config in patched_mitv_channels if config.channel_id not in ADDED_MITV_IDS
    ) + ADDED_MITV_CHANNELS

    # Intercepta solamente DW. El resto sigue llamando a mitv_utc sin cambios.
    latam.scrape_mitv_channel = scrape_mitv_with_dw_fallback

    latam.LATAM_CHANNEL_IDS = (
        *latam.BASE_CHANNEL_IDS,
        *(config.channel_id for config in latam.MITV_CHANNELS),
        *(config.channel_id for config in latam.GATOTV_CHANNELS),
        latam.MAKRODIGITAL_ID,
        latam.ECUADOR_TV_ID,
    )

    if STAR_TVE_ID in latam.LATAM_CHANNEL_IDS:
        raise RuntimeError("STAR TVE reapareció en LATAM_CHANNEL_IDS.")
    if any(config.channel_id == STAR_TVE_ID for config in latam.GATOTV_CHANNELS):
        raise RuntimeError("STAR TVE reapareció en GATOTV_CHANNELS.")
    if len(latam.LATAM_CHANNEL_IDS) != EXPECTED_CHANNELS:
        raise RuntimeError(
            f"La guía debe contener {EXPECTED_CHANNELS} canales; "
            f"obtenidos={len(latam.LATAM_CHANNEL_IDS)}."
        )
    if len(set(latam.LATAM_CHANNEL_IDS)) != EXPECTED_CHANNELS:
        raise RuntimeError("La guía LATAM contiene IDs duplicados.")
    if tuple(latam.LATAM_CHANNEL_IDS) != EXPECTED_LATAM_IDS:
        raise RuntimeError(
            "El orden/identidad de LATAM_CHANNEL_IDS no coincide con los 30 IDs "
            "canónicos de v0.2.38 antes de añadir Miami."
        )
    for channel_id in ADDED_MITV_IDS:
        if channel_id not in latam.LATAM_CHANNEL_IDS:
            raise RuntimeError(f"Falta el nuevo canal {channel_id}.")

    dw_configs = [config for config in latam.MITV_CHANNELS if config.channel_id == DW_ID]
    if len(dw_configs) != 1 or dw_configs[0].slug != DW_PRIMARY_SLUG:
        raise RuntimeError("La configuración primaria de Deutsche.Welle.cl no es la esperada.")


def _clean_and_annotate_status(output_dir: Path) -> None:
    """Limpia STAR TVE y registra la fuente que realmente produjo DW."""
    status_path = output_dir / "latam-status.json"
    if not status_path.is_file():
        return

    status = json.loads(status_path.read_text(encoding="utf-8"))
    for key in list(status):
        if key.startswith("star_tve_"):
            status.pop(key, None)

    for key in (
        "programme_counts",
        "gatotv_source_days",
        "gatotv_daily_counts",
        "gatotv_source_timezones",
        "gatotv_ampm_local_preferred",
    ):
        value = status.get(key)
        if isinstance(value, dict):
            value.pop(STAR_TVE_ID, None)

    sources = status.get("sources")
    if isinstance(sources, dict):
        gato_tv = sources.get("gato_tv")
        if isinstance(gato_tv, dict):
            gato_tv.pop(STAR_TVE_ID, None)

    status["channels"] = EXPECTED_CHANNELS
    status.pop("mitv_local_time_channels", None)
    status["mitv_endpoint_time_channels"] = {
        ANTENA3_ID: {
            "source": "https://mi.tv/co/canales/antena3",
            "endpoint_timezone": "UTC",
            "output_timezone": "America/Guayaquil",
            "conversion": "UTC->America/Guayaquil",
        },
        STAR_CHANNEL_ID: {
            "source": "https://mi.tv/co/canales/fox",
            "endpoint_timezone": "UTC",
            "output_timezone": "America/Guayaquil",
            "conversion": "UTC->America/Guayaquil",
        },
        WARNER_CHANNEL_ID: {
            "source": "https://mi.tv/co/canales/warner",
            "endpoint_timezone": "UTC",
            "output_timezone": "America/Guayaquil",
            "conversion": "UTC->America/Guayaquil",
        },
        HBO_FAMILY_ID: {
            "source": "https://mi.tv/co/canales/hbo-family",
            "endpoint_timezone": "UTC",
            "output_timezone": "America/Guayaquil",
            "conversion": "UTC->America/Guayaquil",
        },
    }

    if isinstance(sources, dict):
        mi_tv_sources = sources.get("mi_tv")
        if isinstance(mi_tv_sources, dict):
            mi_tv_sources[ANTENA3_ID] = "https://mi.tv/co/canales/antena3"
            mi_tv_sources[STAR_CHANNEL_ID] = "https://mi.tv/co/canales/fox"
            mi_tv_sources[WARNER_CHANNEL_ID] = "https://mi.tv/co/canales/warner"
            mi_tv_sources[HBO_FAMILY_ID] = "https://mi.tv/co/canales/hbo-family"

    if DW_LAST_SOURCE_MODE is None or DW_LAST_SOURCE_URL is None:
        raise RuntimeError("DW terminó la generación sin registrar una fuente efectiva.")

    status["dw_source_policy"] = {
        "mode": DW_LAST_SOURCE_MODE,
        "source": DW_LAST_SOURCE_URL,
        "source_timezone": DW_LAST_SOURCE_TIMEZONE,
        "output_timezone": "America/Guayaquil",
        "manual_offset_minutes": 0,
        "loaded_days": DW_LAST_LOADED_DAYS,
        "mi_tv_candidates": [
            DW_PRIMARY_SOURCE_URL,
            DW_ALTERNATE_SOURCE_URL,
        ],
        "gatotv_fallback": DW_GATOTV_SOURCE_URL,
        "mi_tv_errors": list(DW_LAST_MITV_ERRORS),
    }

    if DW_LAST_SOURCE_MODE.startswith("mi-tv-"):
        status["mitv_endpoint_time_channels"][DW_ID] = {
            "source": DW_LAST_SOURCE_URL,
            "endpoint_timezone": "UTC",
            "output_timezone": "America/Guayaquil",
            "conversion": "UTC->America/Guayaquil",
        }
        if isinstance(sources, dict):
            mi_tv = sources.get("mi_tv")
            if isinstance(mi_tv, dict):
                mi_tv[DW_ID] = DW_LAST_SOURCE_URL
    elif DW_LAST_SOURCE_MODE == "gatotv-live":
        mitv_days = status.get("mitv_source_days")
        if isinstance(mitv_days, dict):
            mitv_days.pop(DW_ID, None)
        gatotv_days = status.get("gatotv_source_days")
        if isinstance(gatotv_days, dict):
            gatotv_days[DW_ID] = DW_LAST_LOADED_DAYS
        daily_counts = status.get("gatotv_daily_counts")
        if isinstance(daily_counts, dict):
            daily_counts[DW_ID] = dict(DW_LAST_DAILY_COUNTS)
        source_tzs = status.get("gatotv_source_timezones")
        if isinstance(source_tzs, dict):
            source_tzs[DW_ID] = "America/Guayaquil"
        ampm_flags = status.get("gatotv_ampm_local_preferred")
        if isinstance(ampm_flags, dict):
            ampm_flags[DW_ID] = False
        if isinstance(sources, dict):
            mi_tv = sources.get("mi_tv")
            if isinstance(mi_tv, dict):
                mi_tv.pop(DW_ID, None)
            gato_tv = sources.get("gato_tv")
            if isinstance(gato_tv, dict):
                gato_tv[DW_ID] = DW_GATOTV_SOURCE_URL

    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _assert_output(output_dir: Path) -> None:
    """Guardia final: 30 canales base, programación útil y fuentes trazables."""
    xml_path = output_dir / "latam.xml"
    if not xml_path.is_file():
        raise RuntimeError("No se generó latam.xml.")

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    root = etree.parse(str(xml_path), parser).getroot()

    if root.xpath("./channel[@id=$channel_id]", channel_id=STAR_TVE_ID):
        raise RuntimeError("latam.xml todavía contiene STAR TVE.")
    if root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_TVE_ID):
        raise RuntimeError("latam.xml todavía contiene emisiones STAR TVE.")

    channel_ids = [node.get("id", "") for node in root.findall("channel")]
    if len(channel_ids) != EXPECTED_CHANNELS or len(set(channel_ids)) != EXPECTED_CHANNELS:
        raise RuntimeError(
            f"latam.xml debe contener {EXPECTED_CHANNELS} canales únicos; "
            f"obtenidos={len(channel_ids)}."
        )
    if tuple(channel_ids) != EXPECTED_LATAM_IDS:
        raise RuntimeError(
            "latam.xml contiene 30 canales base, pero su orden/identidad no coincide "
            "con la secuencia canónica de v0.2.38."
        )

    for channel_id in REQUIRED_PROGRAMME_IDS:
        if channel_id not in channel_ids:
            raise RuntimeError(f"latam.xml no contiene {channel_id}.")
        programmes = root.xpath("./programme[@channel=$channel_id]", channel_id=channel_id)
        if len(programmes) < 5:
            raise RuntimeError(
                f"latam.xml contiene programación insuficiente para {channel_id}: "
                f"{len(programmes)} emisiones."
            )
        for programme in programmes:
            if not programme.get("start", "").endswith(" -0500"):
                raise RuntimeError(f"Hora no Guayaquil en {channel_id}: {programme.get('start')}")
            if not programme.get("stop", "").endswith(" -0500"):
                raise RuntimeError(f"Hora no Guayaquil en {channel_id}: {programme.get('stop')}")

    status_path = output_dir / "latam-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if int(status.get("channels", 0)) != EXPECTED_CHANNELS:
        raise RuntimeError("latam-status.json no informa 30 canales base.")
    counts = status.get("programme_counts", {})
    for channel_id in REQUIRED_PROGRAMME_IDS:
        if int(counts.get(channel_id, 0)) < 5:
            raise RuntimeError(f"latam-status.json no registra programación de {channel_id}.")

    endpoint_modes = status.get("mitv_endpoint_time_channels", {})
    expected_sources = {
        ANTENA3_ID: "https://mi.tv/co/canales/antena3",
        STAR_CHANNEL_ID: "https://mi.tv/co/canales/fox",
        WARNER_CHANNEL_ID: "https://mi.tv/co/canales/warner",
        HBO_FAMILY_ID: "https://mi.tv/co/canales/hbo-family",
    }
    for channel_id, source_url in expected_sources.items():
        mode = endpoint_modes.get(channel_id, {})
        if mode.get("source") != source_url:
            raise RuntimeError(f"Fuente mi.tv inesperada para {channel_id}.")
        if (
            mode.get("endpoint_timezone") != "UTC"
            or mode.get("output_timezone") != "America/Guayaquil"
            or mode.get("conversion") != "UTC->America/Guayaquil"
        ):
            raise RuntimeError(f"Política horaria inesperada para {channel_id}: {mode!r}")

    dw_policy = status.get("dw_source_policy", {})
    mode = dw_policy.get("mode")
    source = dw_policy.get("source")
    expected_dw_sources = {
        "mi-tv-primary": DW_PRIMARY_SOURCE_URL,
        "mi-tv-alternate": DW_ALTERNATE_SOURCE_URL,
        "gatotv-live": DW_GATOTV_SOURCE_URL,
    }
    if mode not in expected_dw_sources or source != expected_dw_sources[mode]:
        raise RuntimeError(f"Fuente efectiva inesperada para DW: {dw_policy!r}")
    expected_tz = "America/Guayaquil" if mode == "gatotv-live" else "UTC"
    if dw_policy.get("source_timezone") != expected_tz:
        raise RuntimeError(f"Zona fuente inesperada para DW: {dw_policy!r}")
    if dw_policy.get("output_timezone") != "America/Guayaquil":
        raise RuntimeError(f"Zona destino inesperada para DW: {dw_policy!r}")
    if int(dw_policy.get("manual_offset_minutes", -999)) != 0:
        raise RuntimeError(f"DW no debe usar offset manual: {dw_policy!r}")


def _sample_page(times_and_titles: list[tuple[str, str]]) -> str:
    items = "\n".join(
        """
        <li><a><div class="content">
          <span class="time">{clock}</span>
          <h2>{title}</h2>
          <p class="synopsis">Prueba endpoint UTC de mi.tv</p>
        </div></a></li>
        """.format(clock=clock, title=title)
        for clock, title in times_and_titles
    )
    return f'<div id="listings"><ul>{items}</ul></div>'


def self_test() -> None:
    global ORIGINAL_MITV_SCRAPER

    configure_channels()
    assert len(latam.LATAM_CHANNEL_IDS) == EXPECTED_CHANNELS
    assert tuple(latam.LATAM_CHANNEL_IDS) == EXPECTED_LATAM_IDS
    assert STAR_TVE_ID not in latam.LATAM_CHANNEL_IDS
    assert ANTENA3_ID in latam.LATAM_CHANNEL_IDS
    assert STAR_CHANNEL_ID in latam.LATAM_CHANNEL_IDS
    assert WARNER_CHANNEL_ID in latam.LATAM_CHANNEL_IDS
    assert HBO_FAMILY_ID in latam.LATAM_CHANNEL_IDS
    dw_configs = [config for config in latam.MITV_CHANNELS if config.channel_id == DW_ID]
    assert len(dw_configs) == 1
    assert dw_configs[0].slug == DW_PRIMARY_SLUG
    assert latam.scrape_mitv_channel is scrape_mitv_with_dw_fallback

    sample = _sample_page(
        [
            ("3:00pm", "Programa 1"),
            ("4:00pm", "Programa 2"),
            ("5:00pm", "Programa 3"),
            ("6:00pm", "Programa 4"),
            ("7:00pm", "Programa 5"),
            ("8:00pm", "Programa 6"),
        ]
    )
    programmes = mitv_utc.parse_mitv_page_utc(
        sample, date(2026, 8, 21), ANTENA3_ID
    )
    assert programmes[0].start.isoformat() == "2026-08-21T10:00:00-05:00"
    assert programmes[0].stop.isoformat() == "2026-08-21T11:00:00-05:00"
    assert programmes[0].channel_id == ANTENA3_ID

    programmes_star = mitv_utc.parse_mitv_page_utc(
        sample, date(2026, 8, 21), STAR_CHANNEL_ID
    )
    assert programmes_star[0].start.isoformat() == "2026-08-21T10:00:00-05:00"

    programmes_warner = mitv_utc.parse_mitv_page_utc(
        sample, date(2026, 8, 21), WARNER_CHANNEL_ID
    )
    assert programmes_warner[0].start.isoformat() == "2026-08-21T10:00:00-05:00"

    programmes_hbo = mitv_utc.parse_mitv_page_utc(
        sample, date(2026, 8, 21), HBO_FAMILY_ID
    )
    assert programmes_hbo[0].start.isoformat() == "2026-08-21T10:00:00-05:00"

    # Prueba 1: slug primario falla y el ID alternativo de mi.tv funciona.
    real_mitv = ORIGINAL_MITV_SCRAPER
    real_gatotv = latam.scrape_gatotv_channel
    calls: list[str] = []

    def fake_mitv(**kwargs):
        candidate = kwargs["slug"]
        calls.append(candidate)
        if candidate == DW_PRIMARY_SLUG:
            raise RuntimeError("0/3 simulado")
        return [object()] * 8, 2

    try:
        ORIGINAL_MITV_SCRAPER = fake_mitv
        result, loaded = scrape_mitv_with_dw_fallback(
            country="cl",
            slug=DW_PRIMARY_SLUG,
            channel_id=DW_ID,
            start_date=date(2026, 8, 26),
            local_days=2,
            pause_seconds=0,
        )
        assert len(result) == 8 and loaded == 2
        assert calls == [DW_PRIMARY_SLUG, DW_ALTERNATE_SLUG]
        assert DW_LAST_SOURCE_MODE == "mi-tv-alternate"
        assert DW_LAST_SOURCE_URL == DW_ALTERNATE_SOURCE_URL

        # Prueba 2: ambos IDs mi.tv fallan y entra GatoTV Latinoamérica.
        calls.clear()

        def all_mitv_fail(**kwargs):
            calls.append(kwargs["slug"])
            raise RuntimeError("0/3 simulado")

        def fake_gatotv(config, start_date, days):
            assert config.channel_id == DW_ID
            assert config.slug == DW_GATOTV_SLUG
            assert days == 2
            return [object()] * 10, 2, {
                "2026-08-26": 5,
                "2026-08-27": 5,
            }

        ORIGINAL_MITV_SCRAPER = all_mitv_fail
        latam.scrape_gatotv_channel = fake_gatotv
        result, loaded = scrape_mitv_with_dw_fallback(
            country="cl",
            slug=DW_PRIMARY_SLUG,
            channel_id=DW_ID,
            start_date=date(2026, 8, 26),
            local_days=2,
            pause_seconds=0,
        )
        assert len(result) == 10 and loaded == 2
        assert calls == [DW_PRIMARY_SLUG, DW_ALTERNATE_SLUG]
        assert DW_LAST_SOURCE_MODE == "gatotv-live"
        assert DW_LAST_SOURCE_URL == DW_GATOTV_SOURCE_URL
        assert DW_LAST_SOURCE_TIMEZONE == "America/Guayaquil"
        assert DW_LAST_DAILY_COUNTS == {"2026-08-26": 5, "2026-08-27": 5}
    finally:
        ORIGINAL_MITV_SCRAPER = real_mitv
        latam.scrape_gatotv_channel = real_gatotv

    print(
        "Prueba v0.2.38 correcta: 30 canales base; STAR TVE excluido; DW="
        "mi.tv espanol -> mi.tv amerika -> GatoTV dw_latinoamerica; "
        "Antena 3/Star Channel/Warner/HBO Family conservan UTC -> "
        "America/Guayaquil; offsets manuales=0."
    )


def main() -> int:
    configure_channels()
    result = latam.main()
    if result == 0:
        output_dir = _output_dir(sys.argv[1:])
        _clean_and_annotate_status(output_dir)
        _assert_output(output_dir)
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (etree.XMLSyntaxError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

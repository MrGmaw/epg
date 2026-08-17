#!/usr/bin/env python3
"""Ejecuta build_latam_epg con respaldo resiliente para STAR TVE.

La fuente primaria de STAR TVE sigue siendo GatoTV y conserva íntegra la lógica
horaria de build_latam_epg: la vista AM/PM localizada se interpreta directamente
en America/Guayaquil y la vista 24 h queda como respaldo Atlantic/Canary ->
America/Guayaquil mediante ZoneInfo. No existen offsets manuales.

Si el acceso HTTP directo a GatoTV entrega una representación reducida sin
parrilla, se reintenta la MISMA fuente mediante sus vistas oficiales Móvil y
Tablet manteniendo una sesión/cookies. El HTML recuperado se procesa con el mismo
``parse_gatotv_page`` de la versión estable, por lo que no cambia ninguna regla
horaria. Solo si ambos transportes de GatoTV fallan se consulta la última
``epg-data/latam.xml``: primero fechas exactas y después el mismo weekday,
conservando hora local de Guayaquil, duración, título y descripción. No se
desplazan horas ni se aplican correcciones manuales.
"""

from __future__ import annotations

import json
import sys
import tempfile
import requests
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

from lxml import etree

import build_latam_epg as latam

STAR_ID = "TVEStarHD.es"
MIN_PROGRAMMES_PER_DAY = 5
LAST_SOURCE_MODE: str | None = None
LAST_LIVE_ERROR: str | None = None
LAST_CACHE_PROGRAMMES = 0
LAST_CACHE_DAYS = 0
LAST_CACHE_EXACT_DAYS = 0
LAST_CACHE_WEEKLY_DAYS = 0


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


def _previous_latam(argv: list[str]) -> Path:
    return _arg_path(argv, "--previous-latam-xml", Path(".cache/previous-latam.xml"))


def _text(node: etree._Element, tag: str) -> str | None:
    values = [latam.epg.normalize_text(value) for value in node.xpath(f"./{tag}/text()")]
    values = [value for value in values if value]
    return " — ".join(values) or None


def _load_cached_star_entries(
    xml_path: Path,
) -> list[tuple[datetime, timedelta, str, str | None]]:
    if not xml_path.is_file() or xml_path.stat().st_size == 0:
        raise RuntimeError(f"STAR TVE: no existe caché LATAM utilizable en {xml_path}.")

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(xml_path), parser)
    entries: list[tuple[datetime, timedelta, str, str | None]] = []
    for node in tree.getroot().xpath("./programme[@channel=$channel_id]", channel_id=STAR_ID):
        try:
            start = latam.parse_xmltv_datetime(node.get("start", ""))
            stop = latam.parse_xmltv_datetime(node.get("stop", ""))
        except ValueError:
            continue
        duration = stop - start
        if duration <= timedelta(0) or duration > timedelta(hours=12):
            continue
        title = _text(node, "title")
        if not title:
            continue
        entries.append((start, duration, title, _text(node, "desc")))
    if not entries:
        raise RuntimeError("STAR TVE: la última latam.xml no contiene emisiones utilizables.")
    return entries


def star_exact_from_previous_latam(
    xml_path: Path,
    start_date: date,
    days: int,
) -> tuple[list[latam.epg.Programme], int, dict[str, int]]:
    """Extrae STAR TVE usando únicamente fechas absolutas ya publicadas."""
    entries = _load_cached_star_entries(xml_path)
    window_start = datetime.combine(start_date, time.min, tzinfo=latam.epg.TZ)
    window_end = window_start + timedelta(days=days)

    programmes: list[latam.epg.Programme] = []
    for start, duration, title, description in entries:
        stop = start + duration
        if not (start < window_end and stop > window_start):
            continue
        programmes.append(
            latam.epg.Programme(
                channel_id=STAR_ID,
                start=start,
                stop=stop,
                title=title,
                description=description,
            )
        )

    deduplicated: dict[tuple[str, str, str], latam.epg.Programme] = {}
    for programme in programmes:
        key = (
            programme.start.isoformat(),
            programme.stop.isoformat(),
            latam.normalized(programme.title),
        )
        deduplicated.setdefault(key, programme)
    result = sorted(deduplicated.values(), key=lambda item: (item.start, item.stop, item.title))
    if len(result) < MIN_PROGRAMMES_PER_DAY:
        raise RuntimeError(
            "STAR TVE: la última latam.xml no contiene al menos 5 emisiones "
            "exactas dentro de la ventana vigente."
        )

    daily_counts: dict[str, int] = {}
    for programme in result:
        day_key = programme.start.astimezone(latam.epg.TZ).date().isoformat()
        daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
    return result, len(daily_counts), daily_counts


def star_weekly_from_previous_latam(
    xml_path: Path,
    start_date: date,
    days: int,
) -> tuple[list[latam.epg.Programme], int, dict[str, int]]:
    """Proyecta la última semana STAR al mismo día semanal, como TVC.

    La caché ya está expresada en America/Guayaquil. Por eso se conserva el reloj
    local (hora/minuto/segundo) y la duración; solo cambia la fecha al mismo
    weekday de la ventana nueva.
    """
    entries = _load_cached_star_entries(xml_path)
    by_weekday: dict[int, list[tuple[datetime, timedelta, str, str | None]]] = defaultdict(list)
    for entry in entries:
        by_weekday[entry[0].astimezone(latam.epg.TZ).weekday()].append(entry)

    # Si la caché contiene varias semanas, usar para cada weekday la ocurrencia
    # más reciente de cada combinación hora+título. Esto evita mezclar duplicados
    # históricos y mantiene la parrilla publicada más nueva disponible.
    normalized_weekly: dict[int, list[tuple[datetime, timedelta, str, str | None]]] = {}
    for weekday in range(7):
        candidates = sorted(by_weekday.get(weekday, []), key=lambda item: item[0], reverse=True)
        dedup: dict[tuple[int, int, int, str], tuple[datetime, timedelta, str, str | None]] = {}
        for entry in candidates:
            old_start, duration, title, description = entry
            local_start = old_start.astimezone(latam.epg.TZ)
            key = (
                local_start.hour,
                local_start.minute,
                local_start.second,
                latam.normalized(title),
            )
            dedup.setdefault(key, entry)
        normalized_weekly[weekday] = sorted(
            dedup.values(),
            key=lambda item: item[0].astimezone(latam.epg.TZ).time(),
        )

    programmes: list[latam.epg.Programme] = []
    daily_counts: dict[str, int] = {}
    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        source_entries = normalized_weekly.get(guide_date.weekday(), [])
        if len(source_entries) < MIN_PROGRAMMES_PER_DAY:
            raise RuntimeError(
                "STAR TVE: la caché semanal no contiene una parrilla suficiente para "
                f"weekday={guide_date.weekday()} ({len(source_entries)} emisiones)."
            )
        day_programmes: list[latam.epg.Programme] = []
        for old_start, duration, title, description in source_entries:
            local_old_start = old_start.astimezone(latam.epg.TZ)
            start = datetime.combine(
                guide_date,
                local_old_start.timetz().replace(tzinfo=None),
                tzinfo=latam.epg.TZ,
            )
            stop = start + duration
            day_programmes.append(
                latam.epg.Programme(
                    channel_id=STAR_ID,
                    start=start,
                    stop=stop,
                    title=title,
                    description=description,
                )
            )
        day_programmes.sort(key=lambda item: (item.start, item.stop, item.title))
        programmes.extend(day_programmes)
        daily_counts[guide_date.isoformat()] = len(day_programmes)

    if len(programmes) < max(MIN_PROGRAMMES_PER_DAY, days * MIN_PROGRAMMES_PER_DAY):
        raise RuntimeError("STAR TVE: la caché semanal no produjo programación suficiente.")
    return programmes, len(daily_counts), daily_counts


def star_hybrid_from_previous_latam(
    xml_path: Path,
    start_date: date,
    days: int,
) -> tuple[list[latam.epg.Programme], int, dict[str, int], int, int]:
    """Conserva días exactos y completa solo faltantes por el mismo weekday."""
    entries = _load_cached_star_entries(xml_path)
    exact_by_date: dict[date, list[tuple[datetime, timedelta, str, str | None]]] = defaultdict(list)
    by_weekday: dict[int, list[tuple[datetime, timedelta, str, str | None]]] = defaultdict(list)
    for entry in entries:
        local_start = entry[0].astimezone(latam.epg.TZ)
        exact_by_date[local_start.date()].append(entry)
        by_weekday[local_start.weekday()].append(entry)

    # Para el respaldo semanal se conserva la misma selección que TVC: entradas
    # válidas agrupadas por weekday, deduplicadas por reloj local+título.
    weekly: dict[int, list[tuple[datetime, timedelta, str, str | None]]] = {}
    for weekday in range(7):
        candidates = sorted(by_weekday.get(weekday, []), key=lambda item: item[0], reverse=True)
        dedup: dict[tuple[int, int, int, str], tuple[datetime, timedelta, str, str | None]] = {}
        for entry in candidates:
            old_start, duration, title, description = entry
            local_start = old_start.astimezone(latam.epg.TZ)
            key = (local_start.hour, local_start.minute, local_start.second, latam.normalized(title))
            dedup.setdefault(key, entry)
        weekly[weekday] = sorted(
            dedup.values(),
            key=lambda item: item[0].astimezone(latam.epg.TZ).time(),
        )

    programmes: list[latam.epg.Programme] = []
    daily_counts: dict[str, int] = {}
    exact_days = 0
    weekly_days = 0
    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        exact_entries = sorted(exact_by_date.get(guide_date, []), key=lambda item: item[0])
        if len(exact_entries) >= MIN_PROGRAMMES_PER_DAY:
            source_entries = exact_entries
            use_exact = True
        else:
            source_entries = weekly.get(guide_date.weekday(), [])
            use_exact = False
            if len(source_entries) < MIN_PROGRAMMES_PER_DAY:
                raise RuntimeError(
                    "STAR TVE: la caché no contiene una parrilla suficiente para "
                    f"{guide_date.isoformat()} (exactas={len(exact_entries)}, "
                    f"weekday={len(source_entries)})."
                )

        day_programmes: list[latam.epg.Programme] = []
        for old_start, duration, title, description in source_entries:
            if use_exact:
                start = old_start.astimezone(latam.epg.TZ)
            else:
                local_old_start = old_start.astimezone(latam.epg.TZ)
                start = datetime.combine(
                    guide_date,
                    local_old_start.timetz().replace(tzinfo=None),
                    tzinfo=latam.epg.TZ,
                )
            stop = start + duration
            day_programmes.append(
                latam.epg.Programme(
                    channel_id=STAR_ID,
                    start=start,
                    stop=stop,
                    title=title,
                    description=description,
                )
            )
        day_programmes.sort(key=lambda item: (item.start, item.stop, item.title))
        programmes.extend(day_programmes)
        daily_counts[guide_date.isoformat()] = len(day_programmes)
        if use_exact:
            exact_days += 1
        else:
            weekly_days += 1

    if len(programmes) < max(MIN_PROGRAMMES_PER_DAY, days * MIN_PROGRAMMES_PER_DAY):
        raise RuntimeError("STAR TVE: la caché híbrida no produjo programación suficiente.")
    return programmes, len(daily_counts), daily_counts, exact_days, weekly_days



def scrape_star_via_gatotv_view_session(
    config,
    start_date: date,
    days: int,
    *,
    session_factory: Callable = requests.Session,
) -> tuple[list[latam.epg.Programme], int, dict[str, int]]:
    """Segundo transporte GatoTV usando sus vistas Móvil/Tablet con sesión.

    GatoTV puede responder al runner con un HTML reducido aunque la parrilla
    pública exista. Los enlaces oficiales ``/vista/mobil`` y ``/vista/tablet``
    inicializan la vista mediante cookie y redirigen a la misma URL de canal.
    Se conserva una única sesión para que esa preferencia sobreviva al redirect.
    El contenido se interpreta exclusivamente con ``latam.parse_gatotv_page``;
    por tanto no cambia ninguna regla horaria de STAR TVE.
    """
    session = session_factory()
    all_programmes: list[latam.epg.Programme] = []
    loaded_days = 0
    daily_counts: dict[str, int] = {}
    fetch_days = days + (1 if getattr(config, "source_timezone", None) is not None else 0)

    for offset in range(fetch_days):
        guide_date = start_date + timedelta(days=offset)
        route = f"/canal/{config.slug}/{guide_date.isoformat()}"
        day_programmes: list[latam.epg.Programme] | None = None
        errors: list[str] = []
        for view_mode in ("mobil", "tablet"):
            try:
                response = session.get(
                    f"https://www.gatotv.com/vista/{view_mode}",
                    params={"ruta": route},
                    headers={
                        **latam.GATOTV_BROWSER_HEADERS,
                        "Referer": "https://www.gatotv.com/",
                    },
                    timeout=30,
                    allow_redirects=True,
                )
                response.raise_for_status()
                parsed = latam.parse_gatotv_page(
                    response.text,
                    guide_date,
                    config.channel_id,
                    source_timezone=config.source_timezone,
                    prefer_ampm_local=config.prefer_ampm_local,
                )
                if len(parsed) >= MIN_PROGRAMMES_PER_DAY:
                    day_programmes = parsed
                    latam.epg.log(
                        f"GatoTV {config.channel_id} {guide_date.isoformat()}: "
                        f"vista={view_mode}; sesión/cookies; {len(parsed)} emisiones."
                    )
                    break
                errors.append(f"{view_mode}: {len(parsed)} emisiones")
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                errors.append(f"{view_mode}: {exc}")

        if day_programmes is None:
            latam.epg.warn(
                f"GatoTV {config.channel_id} {guide_date.isoformat()}: "
                "las vistas con sesión tampoco entregaron parrilla utilizable ("
                + "; ".join(errors)
                + ")."
            )
            continue
        all_programmes.extend(day_programmes)
        loaded_days += 1
        daily_counts[guide_date.isoformat()] = len(day_programmes)

    window_start = datetime.combine(start_date, time.min, tzinfo=latam.epg.TZ)
    window_end = window_start + timedelta(days=days)
    deduplicated: dict[tuple[str, str, str], latam.epg.Programme] = {}
    for programme in all_programmes:
        if not (programme.start < window_end and programme.stop > window_start):
            continue
        key = (
            programme.start.isoformat(),
            programme.stop.isoformat(),
            latam.normalized(programme.title),
        )
        deduplicated.setdefault(key, programme)
    result = sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.stop, item.title),
    )
    if loaded_days == 0 or len(result) < MIN_PROGRAMMES_PER_DAY:
        raise RuntimeError(
            "GatoTV STAR TVE: las vistas Móvil/Tablet con sesión tampoco "
            "produjeron programación suficiente."
        )
    return result, loaded_days, daily_counts

def make_resilient_scraper(
    original: Callable,
    previous_latam_xml: Path,
    view_scraper: Callable = scrape_star_via_gatotv_view_session,
) -> Callable:
    def resilient(config, start_date: date, days: int):
        global LAST_SOURCE_MODE, LAST_LIVE_ERROR, LAST_CACHE_PROGRAMMES, LAST_CACHE_DAYS
        global LAST_CACHE_EXACT_DAYS, LAST_CACHE_WEEKLY_DAYS
        if config.channel_id != STAR_ID:
            return original(config, start_date, days)
        try:
            result = original(config, start_date, days)
            LAST_SOURCE_MODE = "gatotv-live"
            LAST_LIVE_ERROR = None
            LAST_CACHE_PROGRAMMES = 0
            LAST_CACHE_DAYS = 0
            LAST_CACHE_EXACT_DAYS = 0
            LAST_CACHE_WEEKLY_DAYS = 0
            return result
        except RuntimeError as exc:
            LAST_LIVE_ERROR = str(exc)
            latam.epg.warn(
                "STAR TVE: el acceso directo a GatoTV no entregó una parrilla "
                "utilizable; se probarán las vistas Móvil/Tablet del mismo "
                f"GatoTV con sesión y cookies. Detalle: {exc}"
            )

        try:
            programmes, loaded_days, daily_counts = view_scraper(config, start_date, days)
            LAST_SOURCE_MODE = "gatotv-view-session"
            LAST_CACHE_PROGRAMMES = 0
            LAST_CACHE_DAYS = 0
            LAST_CACHE_EXACT_DAYS = 0
            LAST_CACHE_WEEKLY_DAYS = 0
            latam.epg.log(
                "STAR TVE: recuperada desde las vistas oficiales Móvil/Tablet "
                "de GatoTV; mismo parser horario; ajuste_manual=0min."
            )
            return programmes, loaded_days, daily_counts
        except (requests.RequestException, RuntimeError, ValueError) as session_exc:
            latam.epg.warn(
                "STAR TVE: también falló el acceso GatoTV con sesión; recién ahora "
                f"se probará epg-data. Detalle: {session_exc}"
            )
            LAST_LIVE_ERROR = f"directo={LAST_LIVE_ERROR}; sesión={session_exc}"

        try:
            programmes, loaded_days, daily_counts, exact_days, weekly_days = (
                star_hybrid_from_previous_latam(previous_latam_xml, start_date, days)
            )
        except (OSError, etree.XMLSyntaxError, RuntimeError, ValueError) as cache_exc:
            raise RuntimeError(
                "STAR TVE: falló GatoTV y tampoco existe una caché exacta/semanal "
                f"suficiente en epg-data. GatoTV: {LAST_LIVE_ERROR}; caché: {cache_exc}"
            ) from cache_exc

        LAST_CACHE_PROGRAMMES = len(programmes)
        LAST_CACHE_DAYS = loaded_days
        LAST_CACHE_EXACT_DAYS = exact_days
        LAST_CACHE_WEEKLY_DAYS = weekly_days
        if weekly_days == 0:
            LAST_SOURCE_MODE = "epg-data-exact-cache"
        elif exact_days == 0:
            LAST_SOURCE_MODE = "epg-data-weekly-cache"
        else:
            LAST_SOURCE_MODE = "epg-data-exact-plus-weekly-cache"
        latam.epg.log(
            "STAR TVE: respaldo tipo TVC desde epg-data activado: "
            f"{len(programmes)} emisiones en {loaded_days} día(s); "
            f"días_exactos={exact_days}; días_weekday={weekly_days}; "
            "reloj_local=America/Guayaquil; ajuste_manual=0min."
        )
        return programmes, loaded_days, daily_counts

    return resilient

def _record_status(output_dir: Path) -> None:
    status_path = output_dir / "latam-status.json"
    if not status_path.is_file() or LAST_SOURCE_MODE is None:
        return
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    status["star_tve_source_mode"] = LAST_SOURCE_MODE
    status["star_tve_cache_policy"] = (
        "gatotv-live -> gatotv-view-session -> exact-dates -> weekly-same-weekday-local-clock"
    )
    if LAST_SOURCE_MODE.startswith("epg-data-"):
        status["star_tve_fallback"] = "epg-data/latam.xml"
        status["star_tve_cache_programmes"] = LAST_CACHE_PROGRAMMES
        status["star_tve_cache_days"] = LAST_CACHE_DAYS
        status["star_tve_cache_exact_days"] = LAST_CACHE_EXACT_DAYS
        status["star_tve_cache_weekly_days"] = LAST_CACHE_WEEKLY_DAYS
        status["star_tve_gatotv_error"] = LAST_LIVE_ERROR
        status["star_tve_cache_manual_offset_minutes"] = 0
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def self_test() -> None:
    root = etree.Element("tv")
    base = date(2026, 8, 3)  # lunes, semana completa anterior
    for offset in range(7):
        guide_date = base + timedelta(days=offset)
        for item in range(5):
            start = datetime(
                guide_date.year,
                guide_date.month,
                guide_date.day,
                6 + item,
                item,
                tzinfo=latam.epg.TZ,
            )
            stop = start + timedelta(minutes=55 + item)
            node = etree.SubElement(
                root,
                "programme",
                channel=STAR_ID,
                start=start.strftime("%Y%m%d%H%M%S %z"),
                stop=stop.strftime("%Y%m%d%H%M%S %z"),
            )
            etree.SubElement(node, "title", lang="es").text = f"STAR prueba {offset}-{item}"

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "previous-latam.xml"
        etree.ElementTree(root).write(str(path), encoding="UTF-8", xml_declaration=True)

        # Semana siguiente: no hay fechas exactas; deben proyectarse 7 weekdays.
        target = date(2026, 8, 10)
        programmes, loaded_days, counts, exact_days, weekly_days = (
            star_hybrid_from_previous_latam(path, target, 7)
        )
        assert len(programmes) == 35
        assert loaded_days == 7
        assert set(counts.values()) == {5}
        assert exact_days == 0 and weekly_days == 7
        assert programmes[0].start.date() == target
        assert programmes[0].start.hour == 6
        assert programmes[0].start.minute == 0
        assert programmes[0].title == "STAR prueba 0-0"
        assert programmes[0].stop - programmes[0].start == timedelta(minutes=55)

        # Ventana solapada: jueves-domingo deben conservar fechas exactas y solo
        # lunes-miércoles deben completarse por weekday.
        overlap_target = date(2026, 8, 6)
        mixed, mixed_days, mixed_counts, mixed_exact, mixed_weekly = (
            star_hybrid_from_previous_latam(path, overlap_target, 7)
        )
        assert len(mixed) == 35 and mixed_days == 7
        assert set(mixed_counts.values()) == {5}
        assert mixed_exact == 4 and mixed_weekly == 3
        assert mixed[0].start.date() == overlap_target

        calls = 0
        def failing_original(config, start_date, days):
            nonlocal calls
            calls += 1
            raise RuntimeError("fallo GatoTV simulado")

        fake_config = type(
            "Config",
            (),
            {
                "channel_id": STAR_ID,
                "slug": "star_tve",
                "source_timezone": "Atlantic/Canary",
                "prefer_ampm_local": True,
            },
        )()
        def failing_view(config, start_date, days):
            raise RuntimeError("fallo vista GatoTV simulado")
        resilient = make_resilient_scraper(failing_original, path, view_scraper=failing_view)
        fallback, fallback_days, fallback_counts = resilient(fake_config, target, 7)
        assert calls == 1
        assert len(fallback) == 35
        assert fallback_days == 7
        assert set(fallback_counts.values()) == {5}
        assert LAST_SOURCE_MODE == "epg-data-weekly-cache"

        # El transporte alternativo debe mantener cookies y reutilizar exactamente
        # el parser STAR de build_latam_epg. Se simulan 5 filas AM/PM canónicas.
        fixture = "<html><body>" + "".join(
            f'<div class="tbl_EPG_row_x"><div class="tbl_EPG_TimesColumn_x">{h}:00 AM</div>'
            f'<div class="tbl_EPG_TimesColumn_x">{h}:30 AM</div>'
            f'<div class="div_program_title_on_channel_x">Programa {h}</div></div>'
            for h in range(1, 6)
        ) + "</body></html>"

        class FakeResponse:
            text = fixture
            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.calls = []
            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse()

        fake_config2 = type(
            "Config",
            (),
            {
                "channel_id": STAR_ID,
                "slug": "star_tve",
                "source_timezone": "Atlantic/Canary",
                "prefer_ampm_local": True,
            },
        )()
        recovered, recovered_days, recovered_counts = scrape_star_via_gatotv_view_session(
            fake_config2, date(2026, 8, 17), 1, session_factory=FakeSession
        )
        assert len(recovered) == 5
        assert recovered_days >= 1
        assert recovered_counts["2026-08-17"] == 5
        assert recovered[0].start.hour == 1  # AM/PM se mantiene en Guayaquil.

    print(
        "Prueba STAR resiliente correcta: GatoTV primario; caché exacta cuando "
        "existe y respaldo semanal tipo TVC solo para días faltantes; "
        "reloj Guayaquil y 0 offsets."
    )

def main() -> int:
    previous = _previous_latam(sys.argv[1:])
    latam.scrape_gatotv_channel = make_resilient_scraper(latam.scrape_gatotv_channel, previous)
    result = latam.main()
    if result == 0:
        _record_status(_output_dir(sys.argv[1:]))
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (etree.XMLSyntaxError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

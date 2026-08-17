#!/usr/bin/env python3
"""Respaldo resiliente para TC Televisión dentro de ``ec.xml``.

Prioridad de fuentes:

1. EPGShare, cuando ``Canal.TC.Televisión.ec`` contiene programación vigente.
2. GatoTV (``/canal/tc_television``), interpretado directamente en
   ``America/Guayaquil`` por el parser genérico del generador base.
3. Última ``ec.xml`` válida de ``epg-data``, reproyectada por día de semana.

La capa no inventa emisiones. Si ninguna fuente produce una parrilla suficiente,
la construcción falla de forma explícita.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from lxml import etree
import requests

TC_ID = "Canal.TC.Televisión.ec"
GATOTV_TC_BASE = "https://www.gatotv.com/canal/tc_television"
DEFAULT_CACHE_XML = Path(".cache/previous-ec.xml")
MIN_PROGRAMMES = 5

LAST_SOURCE: str | None = None
LAST_PROGRAMMES: int = 0
LAST_GATOTV_DAYS: int = 0


def _parse_xmltv_datetime(value: str, tz) -> datetime:
    """Convierte una fecha XMLTV a ``tz`` tolerando formatos habituales."""
    raw = (value or "").strip()
    for fmt in (
        "%Y%m%d%H%M%S %z",
        "%Y%m%d%H%M %z",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    raise ValueError(f"Fecha XMLTV no reconocida: {value!r}")


def _window(start_date: date, days: int, tz) -> tuple[datetime, datetime]:
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=tz)
    return start, start + timedelta(days=max(1, days))


def _overlaps(programme: etree._Element, start: datetime, end: datetime, tz) -> bool:
    try:
        p_start = _parse_xmltv_datetime(programme.get("start", ""), tz)
        p_stop = _parse_xmltv_datetime(programme.get("stop", ""), tz)
    except ValueError:
        return False
    return p_start < end and p_stop > start


def _current_programmes(
    root: etree._Element,
    start_date: date,
    days: int,
    tz,
) -> list[etree._Element]:
    start, end = _window(start_date, days, tz)
    return [
        programme
        for programme in root.findall("programme")
        if programme.get("channel") == TC_ID
        and _overlaps(programme, start, end, tz)
    ]


def _channel_from_root(root: etree._Element) -> etree._Element | None:
    return next(
        (channel for channel in root.findall("channel") if channel.get("id") == TC_ID),
        None,
    )


def _basic_channel() -> etree._Element:
    channel = etree.Element("channel", id=TC_ID)
    name = etree.SubElement(channel, "display-name", lang="es")
    name.text = "TC Televisión"
    return channel


def _insert_channel_before_programmes(root: etree._Element, channel: etree._Element) -> None:
    children = list(root)
    index = next(
        (i for i, child in enumerate(children) if child.tag == "programme"),
        len(children),
    )
    root.insert(index, channel)


def _replace_tc(
    root: etree._Element,
    programmes: list[etree._Element],
    *,
    channel: etree._Element | None = None,
) -> None:
    """Sustituye exclusivamente TC y conserva intactos los demás canales."""
    existing = _channel_from_root(root)
    source_channel = channel if channel is not None else existing
    replacement = copy.deepcopy(source_channel if source_channel is not None else _basic_channel())
    replacement.set("id", TC_ID)

    if existing is not None:
        root.remove(existing)
    for programme in list(root.findall("programme")):
        if programme.get("channel") == TC_ID:
            root.remove(programme)

    _insert_channel_before_programmes(root, replacement)
    for programme in programmes:
        node = copy.deepcopy(programme)
        node.set("channel", TC_ID)
        root.append(node)


def _read_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    return etree.parse(str(path), parser)


def load_cached_tc(
    epg,
    cache_xml: Path,
    start_date: date,
    days: int,
) -> tuple[list[etree._Element], etree._Element | None]:
    """Reproyecta la última parrilla válida de TC por día de semana."""
    if not cache_xml.is_file():
        raise RuntimeError(f"No existe la caché XMLTV de TC: {cache_xml}.")

    tree = _read_xml(cache_xml)
    root = tree.getroot()
    source_channel = _channel_from_root(root)
    if source_channel is None:
        raise RuntimeError(f"La caché {cache_xml} no contiene el canal {TC_ID}.")

    by_weekday: dict[int, dict[date, list[tuple[etree._Element, datetime, datetime]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for programme in root.findall("programme"):
        if programme.get("channel") != TC_ID:
            continue
        try:
            p_start = _parse_xmltv_datetime(programme.get("start", ""), epg.TZ)
            p_stop = _parse_xmltv_datetime(programme.get("stop", ""), epg.TZ)
        except ValueError:
            continue
        if p_stop <= p_start:
            continue
        by_weekday[p_start.weekday()][p_start.date()].append((programme, p_start, p_stop))

    result: list[etree._Element] = []
    for offset in range(max(1, days)):
        target_date = start_date + timedelta(days=offset)
        candidates = by_weekday.get(target_date.weekday(), {})
        valid_days = [
            source_date
            for source_date, rows in candidates.items()
            if len(rows) >= MIN_PROGRAMMES
        ]
        if not valid_days:
            raise RuntimeError(
                "La caché de TC no contiene una parrilla suficiente para "
                f"{target_date.strftime('%A')} ({target_date.isoformat()})."
            )

        # La fecha más reciente del mismo día de semana es la mejor plantilla.
        source_date = max(valid_days)
        delta = target_date - source_date
        rows = sorted(candidates[source_date], key=lambda item: item[1])
        for programme, p_start, p_stop in rows:
            node = copy.deepcopy(programme)
            node.set("channel", TC_ID)
            node.set("start", epg.format_xmltv_datetime(p_start + delta))
            node.set("stop", epg.format_xmltv_datetime(p_stop + delta))
            result.append(node)

    if len(result) < MIN_PROGRAMMES:
        raise RuntimeError("La caché de TC no produjo una parrilla suficiente.")
    return result, copy.deepcopy(source_channel)


def make_resilient_epgshare_parser(
    epg,
    original_parser: Callable[[], etree._ElementTree],
    cache_xml: Path = DEFAULT_CACHE_XML,
    days: int = 7,
) -> Callable[[], etree._ElementTree]:
    """Envuelve ``parse_epgshare`` y garantiza una parrilla vigente para TC."""

    def resilient_parser() -> etree._ElementTree:
        global LAST_SOURCE, LAST_PROGRAMMES, LAST_GATOTV_DAYS
        LAST_SOURCE = None
        LAST_PROGRAMMES = 0
        LAST_GATOTV_DAYS = 0

        tree = original_parser()
        root = tree.getroot()
        today = datetime.now(epg.TZ).date()
        current = _current_programmes(root, today, days, epg.TZ)
        if len(current) >= MIN_PROGRAMMES:
            LAST_SOURCE = "epgshare"
            LAST_PROGRAMMES = len(current)
            epg.log(
                f"TC Televisión: EPGShare vigente ({len(current)} emisiones en ventana)."
            )
            return tree

        epg.warn(
            "TC Televisión: EPGShare no contiene programación vigente suficiente "
            f"({len(current)} emisiones); se probará GatoTV."
        )

        try:
            gatotv_programmes, loaded_days = epg.scrape_gatotv_range(
                GATOTV_TC_BASE,
                TC_ID,
                today,
                max(1, days),
            )
            gatotv_nodes = [epg.make_programme(item) for item in gatotv_programmes]
            if len(gatotv_nodes) < MIN_PROGRAMMES:
                raise RuntimeError(
                    f"GatoTV produjo solo {len(gatotv_nodes)} emisiones para TC."
                )
            _replace_tc(root, gatotv_nodes)
            LAST_SOURCE = "gatotv"
            LAST_PROGRAMMES = len(gatotv_nodes)
            LAST_GATOTV_DAYS = loaded_days
            epg.log(
                "TC Televisión: respaldo GatoTV activado; "
                f"{len(gatotv_nodes)} emisiones / {loaded_days} día(s)."
            )
            return tree
        except (requests.RequestException, RuntimeError, ValueError, OSError) as gatotv_exc:
            # La caché es deliberadamente el tercer y último nivel de respaldo.
            epg.warn(
                "TC Televisión: GatoTV no produjo una parrilla utilizable "
                f"({gatotv_exc}); se probará epg-data/ec.xml."
            )

        try:
            cached_nodes, cached_channel = load_cached_tc(
                epg,
                cache_xml,
                today,
                max(1, days),
            )
            _replace_tc(root, cached_nodes, channel=cached_channel)
        except (OSError, etree.XMLSyntaxError, RuntimeError, ValueError) as cache_exc:
            raise RuntimeError(
                "TC Televisión no tiene programación utilizable en EPGShare, "
                "GatoTV ni en la última ec.xml válida de epg-data. "
                f"Último error: {cache_exc}"
            ) from cache_exc

        LAST_SOURCE = "epg-data-cache"
        LAST_PROGRAMMES = len(cached_nodes)
        epg.log(
            "TC Televisión: respaldo epg-data activado; "
            f"{len(cached_nodes)} emisiones reproyectadas por día de semana."
        )
        return tree

    return resilient_parser


def _test_xml(epg, start_date: date, days: int = 7) -> etree._ElementTree:
    root = etree.Element("tv")
    root.append(_basic_channel())
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        for index in range(6):
            start = datetime.combine(
                day,
                datetime.min.time(),
                tzinfo=epg.TZ,
            ) + timedelta(hours=index * 3)
            stop = start + timedelta(hours=1)
            item = epg.Programme(
                channel_id=TC_ID,
                start=start,
                stop=stop,
                title=f"TC prueba {day.isoformat()} {index}",
            )
            root.append(epg.make_programme(item))
    return etree.ElementTree(root)


def self_test(epg) -> None:
    """Pruebas sin red: prioridad EPGShare, GatoTV y caché por weekday."""
    global LAST_SOURCE
    today = datetime.now(epg.TZ).date()

    # 1. EPGShare suficiente: el segundo nivel jamás debe consultarse.
    original_scraper = epg.scrape_gatotv_range
    try:
        def should_not_run(*_args, **_kwargs):
            raise AssertionError("GatoTV no debe consultarse con TC vigente en EPGShare.")

        epg.scrape_gatotv_range = should_not_run
        parser = make_resilient_epgshare_parser(
            epg,
            lambda: _test_xml(epg, today, 1),
            Path("/ruta/inexistente.xml"),
            1,
        )
        result = parser()
        assert LAST_SOURCE == "epgshare"
        assert len(_current_programmes(result.getroot(), today, 1, epg.TZ)) == 6
    finally:
        epg.scrape_gatotv_range = original_scraper

    # 2. EPGShare vacío: GatoTV debe reemplazar TC sin tocar la caché.
    try:
        gatotv_items = []
        for index in range(6):
            start = datetime.combine(today, datetime.min.time(), tzinfo=epg.TZ) + timedelta(
                hours=index * 3
            )
            gatotv_items.append(
                epg.Programme(
                    channel_id=TC_ID,
                    start=start,
                    stop=start + timedelta(hours=1),
                    title=f"GatoTV prueba {index}",
                )
            )

        epg.scrape_gatotv_range = lambda *_args, **_kwargs: (gatotv_items, 1)
        empty = etree.Element("tv")
        empty.append(_basic_channel())
        parser = make_resilient_epgshare_parser(
            epg,
            lambda: etree.ElementTree(copy.deepcopy(empty)),
            Path("/ruta/inexistente.xml"),
            1,
        )
        result = parser()
        assert LAST_SOURCE == "gatotv"
        assert len(_current_programmes(result.getroot(), today, 1, epg.TZ)) == 6
    finally:
        epg.scrape_gatotv_range = original_scraper

    # 3. EPGShare y GatoTV vacíos: la semana anterior se reproyecta por weekday.
    with TemporaryDirectory() as temp_dir:
        cache_path = Path(temp_dir) / "previous-ec.xml"
        source_monday = today - timedelta(days=today.weekday() + 7)
        cache_tree = _test_xml(epg, source_monday, 7)
        cache_path.write_bytes(
            etree.tostring(cache_tree, encoding="UTF-8", xml_declaration=True)
        )
        try:
            def fail_gatotv(*_args, **_kwargs):
                raise RuntimeError("fallo simulado")

            epg.scrape_gatotv_range = fail_gatotv
            empty = etree.Element("tv")
            empty.append(_basic_channel())
            parser = make_resilient_epgshare_parser(
                epg,
                lambda: etree.ElementTree(copy.deepcopy(empty)),
                cache_path,
                7,
            )
            result = parser()
            assert LAST_SOURCE == "epg-data-cache"
            current = _current_programmes(result.getroot(), today, 7, epg.TZ)
            assert len(current) == 42
            assert all(node.get("channel") == TC_ID for node in current)
        finally:
            epg.scrape_gatotv_range = original_scraper

    print(
        "Prueba TC resiliente correcta: EPGShare -> GatoTV -> epg-data, "
        "sin offsets manuales.",
        flush=True,
    )

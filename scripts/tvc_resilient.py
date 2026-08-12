#!/usr/bin/env python3
"""Respaldo resiliente para la parrilla de TVC.

Primero se intenta la fuente oficial mediante el scraper del generador base.
Si la web de TVC cambia o deja de entregar una parrilla utilizable, se toma la
última parrilla válida de ``epg-data/ec.xml`` y se traslada por día de la
semana a la nueva ventana. No se inventan títulos ni horarios.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import requests
from lxml import etree

TVC_ID = "TVC.ec"
DEFAULT_CACHE_XML = Path(".cache/previous-ec.xml")
LAST_SOURCE: str | None = None


def _parse_xmltv_datetime(value: str, tz) -> datetime:
    value = value.strip()
    formats = (
        "%Y%m%d%H%M%S %z",
        "%Y%m%d%H%M %z",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    raise ValueError(f"Fecha XMLTV no reconocida: {value!r}")


def load_cached_tvc_programmes(epg, cache_xml: Path, start_date: date, days: int):
    """Reconstruye TVC usando la última semana válida publicada en epg-data."""

    if not cache_xml.is_file() or cache_xml.stat().st_size == 0:
        raise RuntimeError(
            f"TVC: no existe una caché previa utilizable en {cache_xml}."
        )

    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        root = etree.parse(str(cache_xml), parser).getroot()
    except (OSError, etree.XMLSyntaxError) as exc:
        raise RuntimeError(f"TVC: no se pudo leer la caché {cache_xml}: {exc}") from exc

    by_weekday: dict[int, list[tuple[datetime, timedelta, str, str | None]]] = {
        index: [] for index in range(7)
    }

    for node in root.findall("programme"):
        if node.get("channel") != TVC_ID:
            continue
        raw_start = node.get("start")
        raw_stop = node.get("stop")
        if not raw_start or not raw_stop:
            continue
        try:
            old_start = _parse_xmltv_datetime(raw_start, epg.TZ)
            old_stop = _parse_xmltv_datetime(raw_stop, epg.TZ)
        except ValueError:
            continue
        duration = old_stop - old_start
        if duration <= timedelta(0) or duration > timedelta(hours=12):
            continue
        title_node = node.find("title")
        title = epg.normalize_text(title_node.text or "") if title_node is not None else ""
        if not title:
            continue
        desc_node = node.find("desc")
        description = None
        if desc_node is not None and desc_node.text:
            description = epg.normalize_text(desc_node.text) or None
        by_weekday[old_start.weekday()].append(
            (old_start, duration, title, description)
        )

    for weekday, entries in by_weekday.items():
        entries.sort(key=lambda item: item[0])
        dedup: dict[tuple[int, int, str], tuple[datetime, timedelta, str, str | None]] = {}
        for entry in entries:
            old_start, duration, title, description = entry
            key = (old_start.hour, old_start.minute, epg.normalized_key(title))
            dedup.setdefault(key, entry)
        by_weekday[weekday] = list(dedup.values())

    programmes = []
    counts: dict[str, int] = {}
    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        entries = by_weekday.get(guide_date.weekday(), [])
        if len(entries) < 5:
            raise RuntimeError(
                "TVC: la caché previa no contiene una parrilla suficiente para "
                f"{guide_date.strftime('%A')} ({len(entries)} emisiones)."
            )
        day_programmes = []
        for old_start, duration, title, description in entries:
            start = datetime.combine(
                guide_date,
                old_start.timetz().replace(tzinfo=None),
                tzinfo=epg.TZ,
            )
            stop = start + duration
            day_programmes.append(
                epg.Programme(
                    channel_id=TVC_ID,
                    start=start,
                    stop=stop,
                    title=title,
                    description=description,
                )
            )
        day_programmes.sort(key=lambda item: item.start)
        programmes.extend(day_programmes)
        counts[guide_date.isoformat()] = len(day_programmes)

    if len(programmes) < max(5, days * 5):
        raise RuntimeError("TVC: la caché previa no produjo programación suficiente.")

    epg.log(
        "TVC respaldo epg-data: "
        + ", ".join(f"{day}={count}" for day, count in counts.items())
        + f"; total={len(programmes)} emisiones."
    )
    return programmes


def make_resilient_tvc_scraper(
    epg,
    official_scraper: Callable,
    cache_xml: Path = DEFAULT_CACHE_XML,
):
    """Devuelve un scraper que usa la web oficial y cae a la caché validada."""

    def scrape(start_date: date, days: int):
        global LAST_SOURCE
        try:
            programmes = official_scraper(start_date, days)
            if len(programmes) < max(5, days * 5):
                raise RuntimeError(
                    f"TVC oficial devolvió solo {len(programmes)} emisiones."
                )
            LAST_SOURCE = "official"
            return programmes
        except (requests.RequestException, RuntimeError) as exc:
            epg.warn(
                "TVC oficial no disponible o incompatible "
                f"({exc}). Se usará la última parrilla válida de epg-data."
            )
            programmes = load_cached_tvc_programmes(epg, cache_xml, start_date, days)
            LAST_SOURCE = "epg-data-cache"
            return programmes

    return scrape


def self_test(epg) -> None:
    """Prueba determinista de remapeo semanal sin acceso a Internet."""

    import tempfile

    root = etree.Element("tv")
    base = date(2026, 8, 3)  # lunes
    for offset in range(7):
        day = base + timedelta(days=offset)
        for item in range(5):
            start = datetime(
                day.year,
                day.month,
                day.day,
                6 + item,
                0,
                tzinfo=epg.TZ,
            )
            stop = start + timedelta(hours=1)
            node = etree.SubElement(
                root,
                "programme",
                channel=TVC_ID,
                start=epg.format_xmltv_datetime(start),
                stop=epg.format_xmltv_datetime(stop),
            )
            etree.SubElement(node, "title", lang="es").text = f"TVC prueba {offset}-{item}"

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ec.xml"
        etree.ElementTree(root).write(str(path), encoding="UTF-8", xml_declaration=True)
        target = date(2026, 8, 10)  # lunes siguiente
        programmes = load_cached_tvc_programmes(epg, path, target, 7)
        assert len(programmes) == 35
        assert programmes[0].start.date() == target
        assert programmes[0].title == "TVC prueba 0-0"
        assert programmes[-1].start.date() == target + timedelta(days=6)
    print("Prueba TVC resiliente correcta: caché semanal remapeada y validada.")

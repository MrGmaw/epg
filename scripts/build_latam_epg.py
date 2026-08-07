#!/usr/bin/env python3
"""Construye ``latam.xml`` con los 21 canales seleccionados.

La guía principal ``ec.xml`` se genera primero y actúa como fuente estable
para once canales existentes y como respaldo de Ecuador TV. Después se añaden
nueve canales de mi.tv y la parrilla oficial de Ecuador TV cuando está
disponible.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import requests
from bs4 import BeautifulSoup, Tag
from lxml import etree

import build_epg_base as epg
from mitv_utc import scrape_mitv_channel

ECUADOR_TV_URL = "https://www.ecuadortv.ec/programas"
ECUADOR_TV_ID = "Canal.Ecuador.TV.ec"

BASE_CHANNEL_IDS: tuple[str, ...] = (
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
)


@dataclass(frozen=True)
class MitvChannel:
    country: str
    slug: str
    channel_id: str
    names: tuple[str, ...]
    website: str


MITV_CHANNELS: tuple[MitvChannel, ...] = (
    MitvChannel(
        "co",
        "rcn",
        "CanalRCN.co",
        ("Canal RCN", "RCN"),
        "https://www.canalrcn.com/",
    ),
    MitvChannel(
        "co",
        "caracol",
        "CaracolTV.co",
        ("Caracol TV", "Caracol"),
        "https://www.caracoltv.com/",
    ),
    MitvChannel(
        "co",
        "el-gourmet",
        "Canal.Elgourmet.ec",
        ("El Gourmet", "elGourmet"),
        "https://elgourmet.com/",
    ),
    MitvChannel(
        "co",
        "history",
        "Canal.History.co",
        ("History", "History Channel"),
        "https://www.historylatam.com/",
    ),
    MitvChannel(
        "co",
        "h2",
        "Canal.History.2.co",
        ("History 2", "H2"),
        "https://www.historylatam.com/",
    ),
    MitvChannel(
        "ar",
        "canal-7-capital",
        "TV.Publica.canal.7.ar",
        ("TV Pública", "Televisión Pública Argentina"),
        "https://www.tvpublica.com.ar/",
    ),
    MitvChannel(
        "ar",
        "telefe",
        "Telefe.ar",
        ("Telefe",),
        "https://mitelefe.com/",
    ),
    MitvChannel(
        "cl",
        "deutsche-welle-espanol",
        "Deutsche.Welle.cl",
        ("Deutsche Welle Español", "DW Español"),
        "https://www.dw.com/es/",
    ),
    MitvChannel(
        "ar",
        "hgtv",
        "hgtv.ar",
        ("HGTV",),
        "https://mi.tv/ar/canales/hgtv",
    ),
)

LATAM_CHANNEL_IDS: tuple[str, ...] = (
    *BASE_CHANNEL_IDS,
    *(channel.channel_id for channel in MITV_CHANNELS),
    ECUADOR_TV_ID,
)

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}
ECUADOR_TV_CATEGORIES = (
    "Educación, Cultura y Medio Ambiente",
    "Hogar y Estilo de vida",
    "Informativo y opinión",
    "Series y Novelas",
    "Aventuras Infantiles",
    "Salud y Bienestar",
    "Noticias 7",
    "Deportivo",
    "Infantil",
)
DATE_RE = re.compile(
    r"(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s*,?\s*)?"
    r"(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+"
    r"(?P<year>\d{4})",
    re.I,
)
TIME_RANGE_RE = re.compile(
    r"(?P<start>(?:[01]?\d|2[0-3]):[0-5]\d)\s*"
    r"(?:-|–|—|\ba\b)\s*"
    r"(?P<stop>(?:[01]?\d|2[0-3]):[0-5]\d)",
    re.I,
)
RECURRENCE_RE = re.compile(
    r"\b(?:de\s+)?lunes\s+a\s+(?:viernes|domingo)\b|"
    r"\b(?:sabados|domingos|fines\s+de\s+semana)\b|"
    r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+y\s+"
    r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
    re.I,
)


def normalized(value: str) -> str:
    value = epg.normalize_text(value).casefold()
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def parse_xmltv_datetime(value: str) -> datetime:
    value = value.strip()
    for pattern in ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M %z"):
        try:
            return datetime.strptime(value, pattern).astimezone(epg.TZ)
        except ValueError:
            continue
    raise ValueError(f"Fecha XMLTV no reconocida: {value!r}")


def parse_source_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(path), parser)
    if tree.getroot().tag != "tv":
        raise RuntimeError(f"La raíz de {path} no es <tv>.")
    return tree


def source_channel(root: etree._Element, channel_id: str) -> etree._Element:
    matches = root.xpath("./channel[@id=$channel_id]", channel_id=channel_id)
    if len(matches) != 1:
        raise RuntimeError(
            f"Se esperaba un canal {channel_id!r} en ec.xml; encontrados: "
            f"{len(matches)}."
        )
    return matches[0]


def source_programmes(
    root: etree._Element,
    channel_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[etree._Element]:
    result: list[etree._Element] = []
    for programme in root.xpath(
        "./programme[@channel=$channel_id]",
        channel_id=channel_id,
    ):
        try:
            start = parse_xmltv_datetime(programme.get("start", ""))
            stop = parse_xmltv_datetime(programme.get("stop", ""))
        except ValueError:
            continue
        if start < window_end and stop > window_start:
            result.append(copy.deepcopy(programme))
    if not result:
        raise RuntimeError(f"El canal {channel_id} no tiene programación en ec.xml.")
    return result


def make_channel(
    channel_id: str,
    names: Sequence[str],
    website: str,
    icon_url: str | None = None,
) -> etree._Element:
    channel = etree.Element("channel", id=channel_id)
    for name in names:
        display_name = etree.SubElement(channel, "display-name", lang="es")
        display_name.text = name
    if icon_url:
        etree.SubElement(channel, "icon", src=icon_url)
    url = etree.SubElement(channel, "url")
    url.text = website
    return channel


def parse_spanish_date(value: str) -> date | None:
    match = DATE_RE.search(value)
    if match is None:
        return None
    month_key = normalized(match.group("month"))
    month = SPANISH_MONTHS.get(month_key)
    if month is None:
        return None
    try:
        return date(
            int(match.group("year")),
            month,
            int(match.group("day")),
        )
    except ValueError:
        return None


def date_for_weekday(base_date: date, weekday_name: str) -> date | None:
    weekday = WEEKDAYS.get(normalized(weekday_name))
    if weekday is None:
        return None
    offset = (weekday - base_date.weekday()) % 7
    return base_date + timedelta(days=offset)


def clean_ecuador_tv_title(value: str) -> str:
    value = epg.normalize_text(value)
    value = re.sub(r"\bon\s*air\b", "", value, flags=re.I)
    for category in sorted(ECUADOR_TV_CATEGORIES, key=len, reverse=True):
        if normalized(value).startswith(normalized(category)):
            value = value[len(category) :].strip(" :-–—|")
            break
    return epg.normalize_text(value)


def programme_from_schedule_text(
    value: str,
    guide_date: date,
    channel_id: str,
    previous_text: str | None = None,
) -> epg.Programme | None:
    match = TIME_RANGE_RE.search(value)
    if match is None:
        return None

    start_clock = datetime.strptime(match.group("start"), "%H:%M").time()
    stop_clock = datetime.strptime(match.group("stop"), "%H:%M").time()
    prefix = value[: match.start()].strip(" :-–—|")
    title = clean_ecuador_tv_title(prefix)
    if not title and previous_text:
        title = clean_ecuador_tv_title(previous_text)
    if not title or normalized(title) in {
        "lunes",
        "martes",
        "miercoles",
        "jueves",
        "viernes",
        "sabado",
        "domingo",
    }:
        return None

    start = datetime.combine(guide_date, start_clock, tzinfo=epg.TZ)
    stop_date = guide_date if stop_clock > start_clock else guide_date + timedelta(days=1)
    stop = datetime.combine(stop_date, stop_clock, tzinfo=epg.TZ)
    if stop <= start:
        return None
    return epg.Programme(
        channel_id=channel_id,
        start=start,
        stop=stop,
        title=title,
    )


def parse_ecuador_tv_page(
    page: str,
    start_date: date,
    days: int,
    channel_id: str = ECUADOR_TV_ID,
) -> tuple[list[epg.Programme], set[date]]:
    """Extrae días completos de la parrilla oficial de Ecuador TV.

    La página ha usado estructuras dinámicas distintas. El parser trabaja con
    el texto visible del HTML y reconoce fechas españolas, pestañas por día y
    rangos ``HH:MM - HH:MM``. Solo acepta un día oficial cuando encuentra al
    menos cinco emisiones; los días restantes se conservan desde EPGShare.
    """

    soup = BeautifulSoup(page, "lxml")
    lines = [epg.normalize_text(value) for value in soup.stripped_strings]
    lines = [value for value in lines if value]

    window_end_date = start_date + timedelta(days=days)
    current_date: date | None = None
    previous_line: str | None = None
    by_date: dict[date, list[epg.Programme]] = defaultdict(list)

    for line in lines:
        explicit_date = parse_spanish_date(line)
        if explicit_date is not None:
            current_date = explicit_date
            if TIME_RANGE_RE.search(line) is None:
                previous_line = line
                continue
            line = DATE_RE.sub("", line).strip(" ,:-–—|")

        weekday_line = normalized(line).strip(" ,:")
        if weekday_line in WEEKDAYS and TIME_RANGE_RE.search(line) is None:
            current_date = date_for_weekday(start_date, weekday_line)
            previous_line = line
            continue

        if TIME_RANGE_RE.search(line) is None:
            previous_line = line
            continue
        if RECURRENCE_RE.search(normalized(line)) is not None:
            # Horarios generales de fichas de programas, no la parrilla diaria.
            previous_line = line
            continue

        if current_date is None:
            # La vista principal suele corresponder al día local actual.
            current_date = start_date

        if not start_date <= current_date < window_end_date:
            previous_line = line
            continue

        programme = programme_from_schedule_text(
            line,
            current_date,
            channel_id,
            previous_text=previous_line,
        )
        if programme is not None:
            by_date[current_date].append(programme)
        previous_line = line

    accepted_dates: set[date] = set()
    programmes: list[epg.Programme] = []
    for guide_date, entries in sorted(by_date.items()):
        deduplicated: dict[tuple[str, str, str], epg.Programme] = {}
        for programme in entries:
            key = (
                programme.start.isoformat(),
                programme.stop.isoformat(),
                normalized(programme.title),
            )
            deduplicated.setdefault(key, programme)
        day_programmes = sorted(
            deduplicated.values(),
            key=lambda item: (item.start, item.stop, item.title),
        )
        overlap_count = sum(
            1
            for current, following in zip(day_programmes, day_programmes[1:])
            if following.start < current.stop
        )
        if len(day_programmes) < 5 or overlap_count > max(1, len(day_programmes) // 4):
            epg.warn(
                "Ecuador TV oficial: se descartó "
                f"{guide_date.isoformat()} porque contiene "
                f"{len(day_programmes)} emisiones y {overlap_count} solapamientos."
            )
            continue
        accepted_dates.add(guide_date)
        programmes.extend(day_programmes)

    if accepted_dates:
        epg.log(
            "Ecuador TV oficial: días aceptados="
            + ", ".join(day.isoformat() for day in sorted(accepted_dates))
            + f"; total={len(programmes)} emisiones."
        )
    else:
        epg.warn(
            "Ecuador TV oficial: no se encontró un día completo; "
            "se utilizará EPGShare como respaldo."
        )

    return programmes, accepted_dates


def combine_ecuador_tv(
    *,
    source_root: etree._Element,
    start_date: date,
    days: int,
) -> tuple[etree._Element, list[etree._Element], dict[str, object]]:
    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=days)
    channel = copy.deepcopy(source_channel(source_root, ECUADOR_TV_ID))
    epg.ensure_display_name(channel, "Ecuador TV", aliases=("Ecuador TV Canal 7",))
    official_url = channel.find("url")
    if official_url is None:
        official_url = etree.SubElement(channel, "url")
    official_url.text = ECUADOR_TV_URL

    fallback = source_programmes(
        source_root,
        ECUADOR_TV_ID,
        window_start,
        window_end,
    )

    official_programmes: list[epg.Programme] = []
    official_dates: set[date] = set()
    try:
        page = epg.fetch_text(
            ECUADOR_TV_URL,
            headers={"Referer": "https://www.ecuadortv.ec/"},
        )
        official_programmes, official_dates = parse_ecuador_tv_page(
            page,
            start_date,
            days,
        )
    except (requests.RequestException, RuntimeError) as exc:
        epg.warn(f"Ecuador TV oficial: {exc}; se utilizará EPGShare.")

    fallback_dates = {
        parse_xmltv_datetime(programme.get("start", "")).date()
        for programme in fallback
    }
    kept_fallback = [
        programme
        for programme in fallback
        if parse_xmltv_datetime(programme.get("start", "")).date()
        not in official_dates
    ]
    official_elements = [epg.make_programme(item) for item in official_programmes]
    combined = kept_fallback + official_elements
    combined.sort(key=lambda item: (item.get("start", ""), item.get("stop", "")))

    effective_fallback_dates = sorted(fallback_dates.difference(official_dates))
    if official_dates and effective_fallback_dates:
        source_name = "official+epgshare_fallback"
    elif official_dates:
        source_name = "official"
    else:
        source_name = "epgshare_fallback"

    return channel, combined, {
        "source": source_name,
        "official_dates": [day.isoformat() for day in sorted(official_dates)],
        "fallback_dates": [day.isoformat() for day in effective_fallback_dates],
    }


def validate_latam_tree(
    tree: etree._ElementTree,
    dtd_path: Path | None,
) -> dict[str, int]:
    root = tree.getroot()
    if root.attrib != {
        "generator-info-name": "none",
        "generator-info-url": "none",
    }:
        raise RuntimeError(f"Atributos inesperados de <tv>: {dict(root.attrib)!r}")

    channel_ids = [channel.get("id", "") for channel in root.findall("channel")]
    if channel_ids != list(LATAM_CHANNEL_IDS):
        raise RuntimeError(
            "Orden o conjunto de canales inesperado en latam.xml.\n"
            f"Esperado: {list(LATAM_CHANNEL_IDS)!r}\n"
            f"Obtenido: {channel_ids!r}"
        )
    expected_count = len(LATAM_CHANNEL_IDS)
    if len(channel_ids) != expected_count or len(set(channel_ids)) != expected_count:
        raise RuntimeError(
            f"latam.xml debe contener exactamente {expected_count} canales únicos."
        )

    counts = Counter(
        programme.get("channel", "")
        for programme in root.findall("programme")
    )
    missing_programmes = [channel_id for channel_id in channel_ids if counts[channel_id] == 0]
    if missing_programmes:
        raise RuntimeError(
            f"Canales de latam.xml sin programación: {missing_programmes}"
        )

    for programme in root.findall("programme"):
        if programme.get("channel") not in set(channel_ids):
            raise RuntimeError("Existe un programme asociado a un canal no publicado.")
        start = parse_xmltv_datetime(programme.get("start", ""))
        stop = parse_xmltv_datetime(programme.get("stop", ""))
        if stop <= start:
            raise RuntimeError(
                f"Rango inválido en {programme.get('channel')}: "
                f"{programme.get('start')} → {programme.get('stop')}"
            )
        if programme.find("title") is None:
            raise RuntimeError("Existe un programme sin title.")

    if dtd_path is not None:
        with dtd_path.open("rb") as handle:
            dtd = etree.DTD(handle)
        if not dtd.validate(tree):
            errors = "\n".join(
                str(error)
                for error in dtd.error_log.filter_from_errors()[:20]
            )
            raise RuntimeError(f"latam.xml no supera XMLTV DTD:\n{errors}")

    return {channel_id: counts[channel_id] for channel_id in channel_ids}


def write_xml_and_gzip(
    tree: etree._ElementTree,
    xml_path: Path,
    gz_path: Path,
) -> None:
    payload = etree.tostring(
        tree.getroot(),
        encoding="UTF-8",
        xml_declaration=False,
        pretty_print=True,
    )
    header = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n'
    )
    xml_bytes = header + payload
    xml_path.write_bytes(xml_bytes)
    with gz_path.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            compresslevel=9,
            mtime=0,
        ) as gz_handle:
            gz_handle.write(xml_bytes)
    if gzip.decompress(gz_path.read_bytes()) != xml_bytes:
        raise RuntimeError(f"{gz_path.name} no coincide con {xml_path.name}.")


def write_index(output_dir: Path) -> None:
    now = datetime.now(epg.TZ)
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EPG MrG</title>
</head>
<body>
  <h1>EPG MrG</h1>
  <h2>Guía principal Ecuador</h2>
  <ul>
    <li><a href="./ec.xml">ec.xml</a></li>
    <li><a href="./ec.xml.gz">ec.xml.gz</a></li>
    <li><a href="./status.json">status.json</a></li>
  </ul>
  <h2>Guía seleccionada Ecuador y Latinoamérica</h2>
  <ul>
    <li><a href="./latam.xml">latam.xml</a></li>
    <li><a href="./latam.xml.gz">latam.xml.gz</a></li>
    <li><a href="./latam-status.json">latam-status.json</a></li>
  </ul>
  <p><a href="./xmltv.dtd">xmltv.dtd</a></p>
  <p>Última generación: {now.strftime('%Y-%m-%d %H:%M:%S')} (Ecuador).</p>
  <p><code>https://mrgmaw.github.io/epg/latam.xml.gz</code></p>
  <p>GSE Smart IPTV: <code>https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/latam.xml.gz</code></p>
</body>
</html>
"""
    (output_dir / "index.html").write_text(html, encoding="utf-8", newline="\n")
    (output_dir / ".nojekyll").touch()


def build_latam(
    *,
    source_xml: Path,
    output_dir: Path,
    dtd_path: Path | None,
    days: int,
    mitv_days: int,
) -> dict[str, object]:
    start_date = datetime.now(epg.TZ).date()
    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=days)

    source_tree = parse_source_xml(source_xml)
    source_root = source_tree.getroot()
    root = etree.Element(
        "tv",
        **{
            "generator-info-name": "none",
            "generator-info-url": "none",
        },
    )

    channel_elements: list[etree._Element] = []
    programme_elements: list[etree._Element] = []

    for channel_id in BASE_CHANNEL_IDS:
        channel_elements.append(copy.deepcopy(source_channel(source_root, channel_id)))
        programme_elements.extend(
            source_programmes(
                source_root,
                channel_id,
                window_start,
                window_end,
            )
        )

    mitv_source_days: dict[str, int] = {}
    for config in MITV_CHANNELS:
        channel_elements.append(
            make_channel(config.channel_id, config.names, config.website)
        )
        programmes, loaded_days = scrape_mitv_channel(
            country=config.country,
            slug=config.slug,
            channel_id=config.channel_id,
            start_date=start_date,
            local_days=mitv_days,
        )
        mitv_source_days[config.channel_id] = loaded_days
        programme_elements.extend(epg.make_programme(item) for item in programmes)

    ecuador_channel, ecuador_programmes, ecuador_status = combine_ecuador_tv(
        source_root=source_root,
        start_date=start_date,
        days=days,
    )
    channel_elements.append(ecuador_channel)
    programme_elements.extend(ecuador_programmes)

    for channel in channel_elements:
        root.append(channel)
    programme_elements.sort(
        key=lambda item: (
            item.get("start", ""),
            item.get("channel", ""),
            " ".join(item.xpath("./title/text()")),
        )
    )
    for programme in programme_elements:
        root.append(programme)

    tree = etree.ElementTree(root)
    programme_counts = validate_latam_tree(tree, dtd_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_xml_and_gzip(
        tree,
        output_dir / "latam.xml",
        output_dir / "latam.xml.gz",
    )

    now = datetime.now(epg.TZ)
    status: dict[str, object] = {
        "generated_at": now.isoformat(),
        "base_date": start_date.isoformat(),
        "window_days": days,
        "mitv_local_days": mitv_days,
        "channels": len(LATAM_CHANNEL_IDS),
        "programmes": sum(programme_counts.values()),
        "programme_counts": programme_counts,
        "mitv_source_days": mitv_source_days,
        "ecuador_tv": ecuador_status,
        "sources": {
            "base_guide": source_xml.name,
            "epgshare": epg.EPGSHARE_URL,
            "ecuador_tv_official": ECUADOR_TV_URL,
            "mi_tv": {
                config.channel_id: (
                    f"https://mi.tv/{config.country}/canales/{config.slug}"
                )
                for config in MITV_CHANNELS
            },
        },
    }
    (output_dir / "latam-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_index(output_dir)
    return status


def self_test() -> None:
    sample = """
    <html><body>
      <h2>jueves, 06 de agosto de 2026</h2>
      <div>Noticias 7 Noticias 7 Primera Emisión 07:00 - 08:30 onAir</div>
      <div>Hogar y Estilo de vida Esto es Ecuador 08:30 - 09:30</div>
      <div>Educación, Cultura y Medio Ambiente Aprendamos 09:30 - 10:00</div>
      <div>Series y Novelas El cuento de la rosa 10:00 - 11:00</div>
      <div>Deportivo Fanático 11:00 - 12:00</div>
      <div>Informativo y opinión Perspectiva 7 12:00 - 13:00</div>
    </body></html>
    """
    programmes, dates = parse_ecuador_tv_page(
        sample,
        date(2026, 8, 6),
        2,
    )
    assert dates == {date(2026, 8, 6)}
    assert len(programmes) == 6
    assert programmes[0].title == "Noticias 7 Primera Emisión"
    assert programmes[0].start.isoformat() == "2026-08-06T07:00:00-05:00"

    combined = programme_from_schedule_text(
        "Series y Novelas Estas Secretarias 22:30 - 23:30",
        date(2026, 8, 6),
        ECUADOR_TV_ID,
    )
    assert combined is not None
    assert combined.title == "Estas Secretarias"

    assert len(LATAM_CHANNEL_IDS) == 21
    assert len(set(LATAM_CHANNEL_IDS)) == 21
    assert "hgtv.ar" in LATAM_CHANNEL_IDS
    assert LATAM_CHANNEL_IDS[-1] == ECUADOR_TV_ID
    print(
        "Prueba latam correcta: 21 IDs únicos, HGTV incluido y parser de Ecuador TV validado."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-xml", type=Path, default=Path("public/ec.xml"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--dtd", type=Path)
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("GUIDE_DAYS", "7")),
    )
    parser.add_argument(
        "--mitv-days",
        type=int,
        default=int(os.environ.get("MITV_LOCAL_DAYS", "2")),
    )
    args = parser.parse_args()

    if not args.source_xml.is_file():
        parser.error(f"No existe la guía base: {args.source_xml}")
    if not 1 <= args.days <= 7:
        parser.error("--days debe estar entre 1 y 7.")
    if not 1 <= args.mitv_days <= 2:
        parser.error("--mitv-days debe estar entre 1 y 2.")
    if args.dtd is not None and not args.dtd.is_file():
        parser.error(f"No existe el DTD: {args.dtd}")

    status = build_latam(
        source_xml=args.source_xml,
        output_dir=args.output,
        dtd_path=args.dtd,
        days=args.days,
        mitv_days=args.mitv_days,
    )
    epg.log(json.dumps(status, ensure_ascii=False, indent=2))
    epg.log(f"Guía latam generada en: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (requests.RequestException, etree.XMLSyntaxError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

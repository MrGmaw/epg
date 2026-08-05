#!/usr/bin/env python3
"""Construye una guía XMLTV de Ecuador.

Fuentes:
- EPGShare EC1 como base.
- Parrilla oficial de Teleamazonas, separada en Quito y Guayaquil.
- ReporTV Finder para la programación diaria de Oromar TV.

La salida conserva los metadatos XMLTV de EPGShare y añade tres canales:
TeleamazonasQuito.ec, TeleamazonasGuayaquil.ec y OromarTV.ec.
"""

from __future__ import annotations

import argparse
import gzip
import html
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from lxml import etree

TZ = ZoneInfo("America/Guayaquil")
TZ_SUFFIX = "-0500"

EPGSHARE_URL = "https://epgshare01.online/epgshare01/epg_ripper_EC1.xml.gz"
TELEAMAZONAS_URL = "https://www.teleamazonas.com/programacion/"
REPORTV_URL = "https://www.reportv.com.ar/finder/index/3269/"

DAYS_ES = (
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
)

TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
REPORTV_TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d\s*hs\.?$", re.I)

IGNORED_LABELS = {
    "quito",
    "guayaquil",
    "lunes",
    "martes",
    "miércoles",
    "miercoles",
    "jueves",
    "viernes",
    "sábado",
    "sabado",
    "domingo",
    "programación",
    "programacion",
    "parrilla de programación",
    "parrilla de programacion",
}

SUPPLEMENTAL_IDS = {
    "TeleamazonasQuito.ec",
    "TeleamazonasGuayaquil.ec",
    "OromarTV.ec",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
    "MrGmaw-EPG/2.0"
)


@dataclass(frozen=True)
class ScheduleItem:
    minute: int
    title: str
    description: str | None = None


@dataclass(frozen=True)
class Programme:
    channel_id: str
    start: datetime
    stop: datetime
    title: str
    description: str | None = None


def log(message: str) -> None:
    print(message, flush=True)


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\xa0", " ").replace("\u200b", "")
    value = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", value).strip()


def normalized_key(value: str) -> str:
    value = normalize_text(value).casefold()
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def fetch_bytes(url: str, *, timeout: int = 120) -> bytes:
    log(f"Descargando: {url}")
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=timeout,
    )
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"La respuesta de {url} está vacía.")
    return response.content


def fetch_text(url: str, *, timeout: int = 120) -> str:
    content = fetch_bytes(url, timeout=timeout)
    # Teleamazonas usa UTF-8. ReporTV históricamente ha usado variantes
    # de Windows-1252; se intenta UTF-8 y luego cp1252.
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def lines_from_tag(tag: Tag) -> list[str]:
    lines: list[str] = []
    for raw in tag.get_text("\n", strip=True).splitlines():
        line = normalize_text(raw)
        if line:
            lines.append(line)
    return lines


def find_smallest_ancestor_with_times(
    start: Tag,
    pattern: re.Pattern[str],
    *,
    minimum: int,
    maximum: int,
) -> Tag:
    candidates: list[tuple[int, Tag]] = []
    node: Tag | None = start
    while node is not None:
        lines = lines_from_tag(node)
        count = sum(1 for line in lines if pattern.fullmatch(line))
        if minimum <= count <= maximum:
            candidates.append((len(lines), node))
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None

    if not candidates:
        raise RuntimeError("No se encontró un contenedor de programación reconocible.")

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def clean_title_parts(parts: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for part in parts:
        part = normalize_text(part)
        if not part:
            continue
        key = normalized_key(part)
        if key in IGNORED_LABELS:
            continue
        if key in {"thumb", "image", "imagen"}:
            continue
        if cleaned and normalized_key(cleaned[-1]) == key:
            continue
        cleaned.append(part)
    return cleaned


def parse_schedule_blocks(lines: Sequence[str], expected_blocks: int = 14) -> list[list[ScheduleItem]]:
    blocks: list[list[ScheduleItem]] = []
    current: list[ScheduleItem] = []
    previous_minute: int | None = None
    crossed_midnight = False
    index = 0

    while index < len(lines):
        line = lines[index]
        if not TIME_RE.fullmatch(line):
            index += 1
            continue

        hour, minute = (int(value) for value in line.split(":"))
        minute_of_day = hour * 60 + minute

        # Cada parrilla de Teleamazonas empieza alrededor de las 05:00,
        # cruza medianoche y termina antes de las 05:00 del día siguiente.
        if (
            current
            and crossed_midnight
            and previous_minute is not None
            and previous_minute < 300
            and minute_of_day >= 300
        ):
            if len(current) >= 8:
                blocks.append(current)
            current = []
            crossed_midnight = False
            previous_minute = None
            if len(blocks) >= expected_blocks:
                break

        if previous_minute is not None and minute_of_day < previous_minute:
            crossed_midnight = True

        title_parts: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and not TIME_RE.fullmatch(lines[cursor]):
            title_parts.append(lines[cursor])
            cursor += 1

        title_parts = clean_title_parts(title_parts)
        if title_parts:
            title = title_parts[0]
            description = " — ".join(title_parts[1:]) or None
            current.append(
                ScheduleItem(
                    minute=minute_of_day,
                    title=title,
                    description=description,
                )
            )

        previous_minute = minute_of_day
        index = cursor

    if current and len(blocks) < expected_blocks and len(current) >= 8:
        blocks.append(current)

    if len(blocks) < expected_blocks:
        lengths = [len(block) for block in blocks]
        raise RuntimeError(
            "Teleamazonas: se esperaban 14 parrillas "
            f"(2 ciudades × 7 días), pero se encontraron {len(blocks)}. "
            f"Tamaños: {lengths}"
        )

    return blocks[:expected_blocks]


def scrape_teleamazonas() -> tuple[list[list[ScheduleItem]], list[list[ScheduleItem]]]:
    page = fetch_text(TELEAMAZONAS_URL)
    soup = BeautifulSoup(page, "lxml")

    heading: Tag | None = None
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "div", "section"]):
        text = normalized_key(tag.get_text(" ", strip=True))
        if text == "parrilla de programacion":
            heading = tag
            break

    if heading is None:
        # Respaldo: localizar cualquier nodo que contenga el encabezado.
        text_node = soup.find(string=lambda value: bool(value) and "PARRILLA DE PROGRAMACIÓN" in value.upper())
        if text_node is not None and isinstance(text_node.parent, Tag):
            heading = text_node.parent

    if heading is None:
        raise RuntimeError("Teleamazonas: no se encontró 'PARRILLA DE PROGRAMACIÓN'.")

    try:
        container = find_smallest_ancestor_with_times(
            heading,
            TIME_RE,
            minimum=80,
            maximum=900,
        )
        lines = lines_from_tag(container)
    except RuntimeError:
        # Último recurso: usar el documento a partir del encabezado.
        all_lines = lines_from_tag(soup)
        start = next(
            (
                idx
                for idx, line in enumerate(all_lines)
                if normalized_key(line) == "parrilla de programacion"
            ),
            0,
        )
        lines = all_lines[start:]

    blocks = parse_schedule_blocks(lines, expected_blocks=14)
    quito = blocks[:7]
    guayaquil = blocks[7:14]

    log(
        "Teleamazonas: "
        f"Quito={sum(len(block) for block in quito)} emisiones semanales; "
        f"Guayaquil={sum(len(block) for block in guayaquil)} emisiones semanales."
    )
    return quito, guayaquil


def parse_reportv_schedule(lines: Sequence[str]) -> list[ScheduleItem]:
    items: list[ScheduleItem] = []
    index = 0

    while index < len(lines):
        match = REPORTV_TIME_RE.fullmatch(lines[index])
        if match is None:
            index += 1
            continue

        clock = re.sub(r"\s*hs\.?$", "", lines[index], flags=re.I)
        hour, minute = (int(value) for value in clock.split(":"))
        minute_of_day = hour * 60 + minute

        parts: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and REPORTV_TIME_RE.fullmatch(lines[cursor]) is None:
            candidate = normalize_text(lines[cursor])
            key = normalized_key(candidate)
            if candidate and key not in IGNORED_LABELS:
                parts.append(candidate)
            cursor += 1

        parts = clean_title_parts(parts)
        # ReporTV suele repetir el título como título corto y título largo.
        if parts:
            title = parts[0]
            description = " — ".join(parts[1:]) or None
            items.append(ScheduleItem(minute_of_day, title, description))

        index = cursor

    # Elimina duplicados exactos conservando el orden.
    unique: list[ScheduleItem] = []
    seen: set[tuple[int, str]] = set()
    for item in items:
        key = (item.minute, normalized_key(item.title))
        if key not in seen:
            seen.add(key)
            unique.append(item)

    if len(unique) < 4:
        raise RuntimeError(
            "Oromar/ReporTV: se encontraron menos de cuatro emisiones; "
            "la estructura de la fuente puede haber cambiado."
        )

    return unique


def scrape_oromar() -> list[ScheduleItem]:
    page = fetch_text(REPORTV_URL)
    soup = BeautifulSoup(page, "lxml")

    candidates: list[Tag] = []
    for text_node in soup.find_all(string=re.compile(r"\bOROMAR\b", re.I)):
        parent = text_node.parent
        if isinstance(parent, Tag):
            candidates.append(parent)

    best: tuple[int, Tag] | None = None
    for candidate in candidates:
        node: Tag | None = candidate
        while node is not None:
            lines = lines_from_tag(node)
            time_count = sum(1 for line in lines if REPORTV_TIME_RE.fullmatch(line))
            oromar_count = sum(1 for line in lines if "oromar" in normalized_key(line))
            if 4 <= time_count <= 80 and oromar_count >= 1:
                score = len(lines)
                if best is None or score < best[0]:
                    best = (score, node)
            parent = node.parent
            node = parent if isinstance(parent, Tag) else None

    if best is None:
        # El buscador puede entregar el canal dentro del texto completo.
        lines = lines_from_tag(soup)
        positions = [idx for idx, line in enumerate(lines) if "oromar" in normalized_key(line)]
        for position in positions:
            window = lines[max(0, position - 5) : position + 250]
            try:
                items = parse_reportv_schedule(window)
            except RuntimeError:
                continue
            log(f"Oromar/ReporTV: {len(items)} emisiones encontradas.")
            return items
        raise RuntimeError("Oromar/ReporTV: no se encontró el bloque del canal OROMAR.")

    items = parse_reportv_schedule(lines_from_tag(best[1]))
    log(f"Oromar/ReporTV: {len(items)} emisiones encontradas para hoy.")
    return items


def instantiate_weekly_schedule(
    weekly: Sequence[Sequence[ScheduleItem]],
    channel_id: str,
    start_date: date,
    days: int,
) -> list[Programme]:
    if len(weekly) != 7:
        raise ValueError("La parrilla semanal debe contener siete días.")

    starts: list[tuple[datetime, ScheduleItem]] = []
    first_date = start_date - timedelta(days=1)
    last_date = start_date + timedelta(days=days + 1)

    cursor_date = first_date
    while cursor_date <= last_date:
        schedule = weekly[cursor_date.weekday()]
        event_date = cursor_date
        previous_minute: int | None = None

        for item in schedule:
            if previous_minute is not None and item.minute < previous_minute:
                event_date += timedelta(days=1)

            start = datetime.combine(
                event_date,
                time(hour=item.minute // 60, minute=item.minute % 60),
                tzinfo=TZ,
            )
            starts.append((start, item))
            previous_minute = item.minute

        cursor_date += timedelta(days=1)

    starts.sort(key=lambda value: value[0])
    programmes: list[Programme] = []
    window_start = datetime.combine(start_date, time.min, tzinfo=TZ)
    window_end = window_start + timedelta(days=days)

    for index, (start, item) in enumerate(starts):
        stop = (
            starts[index + 1][0]
            if index + 1 < len(starts)
            else start + timedelta(minutes=30)
        )
        if stop <= start:
            stop = start + timedelta(minutes=30)
        if start < window_end and stop > window_start:
            programmes.append(
                Programme(
                    channel_id=channel_id,
                    start=start,
                    stop=stop,
                    title=item.title,
                    description=item.description,
                )
            )

    return programmes


def instantiate_daily_schedule(
    schedule: Sequence[ScheduleItem],
    channel_id: str,
    schedule_date: date,
) -> list[Programme]:
    starts: list[tuple[datetime, ScheduleItem]] = []
    event_date = schedule_date
    previous_minute: int | None = None

    for item in schedule:
        if previous_minute is not None and item.minute < previous_minute:
            event_date += timedelta(days=1)
        start = datetime.combine(
            event_date,
            time(hour=item.minute // 60, minute=item.minute % 60),
            tzinfo=TZ,
        )
        starts.append((start, item))
        previous_minute = item.minute

    programmes: list[Programme] = []
    for index, (start, item) in enumerate(starts):
        stop = (
            starts[index + 1][0]
            if index + 1 < len(starts)
            else start + timedelta(minutes=30)
        )
        if stop <= start:
            stop = start + timedelta(minutes=30)
        programmes.append(
            Programme(
                channel_id=channel_id,
                start=start,
                stop=stop,
                title=item.title,
                description=item.description,
            )
        )
    return programmes


def format_xmltv_datetime(value: datetime) -> str:
    local = value.astimezone(TZ)
    return local.strftime("%Y%m%d%H%M%S") + f" {TZ_SUFFIX}"


def display_name_text(channel: etree._Element) -> str:
    values = [normalize_text(text) for text in channel.xpath("./display-name/text()")]
    return " ".join(values)


def remove_existing_supplemental(root: etree._Element) -> None:
    ids_to_remove: set[str] = set(SUPPLEMENTAL_IDS)

    for channel in root.findall("channel"):
        channel_id = channel.get("id", "")
        name_key = normalized_key(display_name_text(channel))
        id_key = normalized_key(channel_id)
        if "teleamazonas" in name_key or "teleamazonas" in id_key:
            ids_to_remove.add(channel_id)
        if "oromar" in name_key or "oromar" in id_key:
            ids_to_remove.add(channel_id)

    for programme in list(root.findall("programme")):
        if programme.get("channel") in ids_to_remove:
            root.remove(programme)

    for channel in list(root.findall("channel")):
        if channel.get("id") in ids_to_remove:
            root.remove(channel)


def make_channel(
    channel_id: str,
    names: Sequence[str],
    icon_url: str,
    website: str,
) -> etree._Element:
    channel = etree.Element("channel", id=channel_id)
    for name in names:
        display_name = etree.SubElement(channel, "display-name", lang="es")
        display_name.text = name
    etree.SubElement(channel, "icon", src=icon_url)
    url = etree.SubElement(channel, "url")
    url.text = website
    return channel


def make_programme(programme: Programme) -> etree._Element:
    element = etree.Element(
        "programme",
        start=format_xmltv_datetime(programme.start),
        stop=format_xmltv_datetime(programme.stop),
        channel=programme.channel_id,
    )
    title = etree.SubElement(element, "title", lang="es")
    title.text = programme.title
    if programme.description:
        description = etree.SubElement(element, "desc", lang="es")
        description.text = programme.description
    return element


def parse_epgshare() -> etree._ElementTree:
    compressed = fetch_bytes(EPGSHARE_URL, timeout=180)
    try:
        xml_bytes = gzip.decompress(compressed)
    except OSError as exc:
        raise RuntimeError("EPGShare EC1 no es un GZIP válido.") from exc

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    tree = etree.parse(io.BytesIO(xml_bytes), parser)
    root = tree.getroot()
    if root.tag != "tv":
        raise RuntimeError(f"La raíz de EPGShare debería ser <tv>, no <{root.tag}>.")
    return tree


def insert_channels_before_programmes(root: etree._Element, channels: Sequence[etree._Element]) -> None:
    children = list(root)
    first_programme_index = next(
        (index for index, child in enumerate(children) if child.tag == "programme"),
        len(children),
    )
    for offset, channel in enumerate(channels):
        root.insert(first_programme_index + offset, channel)


def validate_tree(tree: etree._ElementTree, required_channels: set[str], dtd_path: Path | None) -> dict[str, int]:
    root = tree.getroot()

    expected_root_attributes = {
        "generator-info-name": "none",
        "generator-info-url": "none",
    }
    if root.attrib != expected_root_attributes:
        raise RuntimeError(f"Atributos inesperados en <tv>: {dict(root.attrib)!r}")

    channel_ids = [channel.get("id") for channel in root.findall("channel")]
    if len(channel_ids) != len(set(channel_ids)):
        raise RuntimeError("Existen identificadores de canal duplicados.")

    missing = required_channels.difference(channel_ids)
    if missing:
        raise RuntimeError(f"Faltan canales obligatorios: {sorted(missing)}")

    programme_counts = {channel_id: 0 for channel_id in required_channels}
    channel_set = set(channel_ids)
    invalid_ranges = 0

    for programme in root.findall("programme"):
        channel_id = programme.get("channel")
        if channel_id not in channel_set:
            raise RuntimeError(f"Programa asociado a canal inexistente: {channel_id!r}")
        if channel_id in programme_counts:
            programme_counts[channel_id] += 1

        start = programme.get("start", "")
        stop = programme.get("stop", "")
        if not start or not stop:
            raise RuntimeError("Existe un programme sin start o stop.")
        if start[:14].isdigit() and stop[:14].isdigit() and start[:14] >= stop[:14]:
            invalid_ranges += 1

        if programme.find("title") is None:
            raise RuntimeError("Existe un programme sin title.")

    empty_required = [channel_id for channel_id, count in programme_counts.items() if count == 0]
    if empty_required:
        raise RuntimeError(f"Canales obligatorios sin programación: {empty_required}")

    if invalid_ranges:
        raise RuntimeError(f"Se encontraron {invalid_ranges} programas con stop <= start.")

    if dtd_path is not None:
        with dtd_path.open("rb") as handle:
            dtd = etree.DTD(handle)
        if not dtd.validate(tree):
            errors = "\n".join(str(error) for error in dtd.error_log.filter_from_errors()[:20])
            raise RuntimeError(f"El XML no supera la validación XMLTV DTD:\n{errors}")

    return {
        "channels": len(channel_ids),
        "programmes": len(root.findall("programme")),
        "teleamazonas_quito": programme_counts["TeleamazonasQuito.ec"],
        "teleamazonas_guayaquil": programme_counts["TeleamazonasGuayaquil.ec"],
        "oromar": programme_counts["OromarTV.ec"],
    }


def write_outputs(
    tree: etree._ElementTree,
    output_dir: Path,
    stats: dict[str, int],
    base_date: date,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    root = tree.getroot()

    payload = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=False,
        pretty_print=True,
    )
    exact_header = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'
        b'\n'
    )
    xml_bytes = exact_header + payload

    xml_path = output_dir / "ec.xml"
    gz_path = output_dir / "ec.xml.gz"
    xml_path.write_bytes(xml_bytes)

    with gz_path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, compresslevel=9, mtime=0) as gz_handle:
            gz_handle.write(xml_bytes)

    if gzip.decompress(gz_path.read_bytes()) != xml_bytes:
        raise RuntimeError("El contenido de ec.xml.gz no coincide con ec.xml.")

    now = datetime.now(TZ)
    summary = {
        "generated_at": now.isoformat(),
        "base_date": base_date.isoformat(),
        "sources": {
            "epgshare": EPGSHARE_URL,
            "teleamazonas": TELEAMAZONAS_URL,
            "oromar": REPORTV_URL,
        },
        **stats,
    }
    (output_dir / "status.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    index_html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EPG Ecuador</title>
  <style>
    body {{ max-width: 800px; margin: 48px auto; padding: 0 20px; font-family: system-ui, sans-serif; line-height: 1.6; }}
    code {{ overflow-wrap: anywhere; }}
    li {{ margin: .65rem 0; }}
  </style>
</head>
<body>
  <h1>EPG Ecuador</h1>
  <p>Guía XMLTV generada automáticamente.</p>
  <ul>
    <li><a href="./ec.xml">ec.xml</a></li>
    <li><a href="./ec.xml.gz">ec.xml.gz</a></li>
    <li><a href="./xmltv.dtd">xmltv.dtd</a></li>
    <li><a href="./status.json">status.json</a></li>
  </ul>
  <p>Incluye Teleamazonas Quito, Teleamazonas Guayaquil y Oromar TV.</p>
  <p>Última generación: {now.strftime('%Y-%m-%d %H:%M:%S')} (Ecuador).</p>
  <p><code>https://mrgmaw.github.io/epg/ec.xml.gz</code></p>
</body>
</html>
"""
    (output_dir / "index.html").write_text(index_html, encoding="utf-8", newline="\n")
    (output_dir / ".nojekyll").touch()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="public", type=Path)
    parser.add_argument("--dtd", type=Path)
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("GUIDE_DAYS", "3")),
        help="Días de Teleamazonas que se añaden a la guía.",
    )
    args = parser.parse_args()

    if not 1 <= args.days <= 7:
        parser.error("--days debe estar entre 1 y 7.")
    if args.dtd is not None and not args.dtd.is_file():
        parser.error(f"No existe el DTD: {args.dtd}")

    today = datetime.now(TZ).date()
    log(f"Fecha base en Ecuador: {today.isoformat()}")

    tree = parse_epgshare()
    root = tree.getroot()
    remove_existing_supplemental(root)

    tele_quito_week, tele_guayaquil_week = scrape_teleamazonas()
    oromar_today = scrape_oromar()

    channels = [
        make_channel(
            "TeleamazonasQuito.ec",
            ("Teleamazonas Quito", "Teleamazonas UIO"),
            "https://graph.facebook.com/TeleamazonasEcuador/picture?width=512&height=512",
            "https://www.teleamazonas.com/",
        ),
        make_channel(
            "TeleamazonasGuayaquil.ec",
            ("Teleamazonas Guayaquil", "Teleamazonas GYE"),
            "https://graph.facebook.com/TeleamazonasEcuador/picture?width=512&height=512",
            "https://www.teleamazonas.com/",
        ),
        make_channel(
            "OromarTV.ec",
            ("Oromar TV", "Oromar"),
            "https://oromartv.com/images/OTV400.png",
            "https://oromartv.com/",
        ),
    ]
    insert_channels_before_programmes(root, channels)

    programmes: list[Programme] = []
    programmes.extend(
        instantiate_weekly_schedule(
            tele_quito_week,
            "TeleamazonasQuito.ec",
            today,
            args.days,
        )
    )
    programmes.extend(
        instantiate_weekly_schedule(
            tele_guayaquil_week,
            "TeleamazonasGuayaquil.ec",
            today,
            args.days,
        )
    )
    programmes.extend(
        instantiate_daily_schedule(
            oromar_today,
            "OromarTV.ec",
            today,
        )
    )

    programmes.sort(key=lambda item: (item.start, item.channel_id, item.title))
    for programme in programmes:
        root.append(make_programme(programme))

    root.attrib.clear()
    root.set("generator-info-name", "none")
    root.set("generator-info-url", "none")

    stats = validate_tree(tree, SUPPLEMENTAL_IDS, args.dtd)
    write_outputs(tree, args.output, stats, today)

    log(json.dumps(stats, ensure_ascii=False, indent=2))
    log(f"Archivos generados en: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (requests.RequestException, etree.XMLSyntaxError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

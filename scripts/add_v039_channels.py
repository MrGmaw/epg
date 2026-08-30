#!/usr/bin/env python3
"""EPG MrG v0.2.39: añade CBS New York y Oromar TV y asegura 5 logos locales.

Se ejecuta después de ``add_miami_epg.py`` sobre el ``latam.xml`` de 32 canales.

Fuentes:
- CBS New York / WCBS-TV: EPGShare US1. Las marcas XMLTV con offset se
  convierten a America/Guayaquil. Una marca sin offset se interpreta como
  America/New_York. Nunca se aplica un offset manual.
- Oromar TV: AmericaTVGuide Ecuador. La página ya publica la parrilla en
  GMT-5 Ecuador; se interpreta directamente como America/Guayaquil.

Los logos se descargan como imágenes de marca, se validan con Pillow, se
normalizan a PNG y se cachean en ``public/logos``. Si una fuente de imagen
falla temporalmente, se conserva el PNG válido de la ejecución anterior.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from lxml import etree
from PIL import Image, UnidentifiedImageError

VERSION = "0.2.39"
EXPECTED_INPUT_CHANNELS = 32
EXPECTED_FINAL_CHANNELS = 34
MIN_PROGRAMMES_PER_CHANNEL = 5

OUTPUT_TZ = ZoneInfo("America/Guayaquil")
NEW_YORK_TZ = ZoneInfo("America/New_York")
LOCAL_LOGO_BASE = "https://mrgmaw.github.io/epg/logos/"

CBS_ID = "CBS.(WCBS).New.York,.NY.us"
CBS_NAME = "CBS New York (WCBS-TV)"
CBS_SOURCE_ID = "CBS.(WCBS).New.York,.NY.us"
CBS_SOURCE_URL = "https://epgshare01.online/epgshare01/epg_ripper_US1.xml.gz"
CBS_PAGE_URL = "https://www.cbsnews.com/newyork/cbs2/"
CBS_LOGO_URL = (
    "https://assets2.cbsnewsstatic.com/hub/i/r/2024/07/26/"
    "c486368f-8a23-4d85-a7c6-569b3e9406c0/thumbnail/620x349/"
    "dfabdc6cf76863f0fac74ab6a394b1c4/lockup-logo-black.png"
)

OROMAR_ID = "OromarTV.ec"
OROMAR_NAME = "Oromar TV"
OROMAR_SOURCE_URL = "https://americatvguide.com/es/ec/channel/oromar_tv"
OROMAR_PAGE_URL = "https://oromartv.com/"
OROMAR_LOGO_URL = "https://oromartv.com/images/OTV400.png"

TARGET_IDS = (CBS_ID, OROMAR_ID)
LOGO_IDS = (
    OROMAR_ID,
    CBS_ID,
    "Antena3-America.co",
    "HBO-Family.co",
    "Warner-channel.co",
)

ANTENA3_LOGO = (
    "https://upload.wikimedia.org/wikipedia/commons/8/83/"
    "Antena3Internacional2025.png"
)
WARNER_LOGO = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b0/"
    "Warner_Channel_2026.svg/960px-Warner_Channel_2026.svg.png"
)
HBO_FAMILY_LOGO = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/22/"
    "HBO_Family.svg/960px-HBO_Family.svg.png"
)

USER_AGENT = "EPG-MrG/0.2.39 (+GitHub Actions; XMLTV)"
REQUEST_TIMEOUT = 35


@dataclass(frozen=True)
class LogoTarget:
    channel_id: str
    page_url: str
    candidates: tuple[str, ...]


LOGO_TARGETS: tuple[LogoTarget, ...] = (
    LogoTarget(OROMAR_ID, OROMAR_PAGE_URL, (OROMAR_LOGO_URL,)),
    LogoTarget(CBS_ID, CBS_PAGE_URL, (CBS_LOGO_URL,)),
    LogoTarget(
        "Antena3-America.co",
        "https://mi.tv/co/canales/antena3",
        (ANTENA3_LOGO,),
    ),
    LogoTarget(
        "HBO-Family.co",
        "https://mi.tv/co/canales/hbo-family",
        (HBO_FAMILY_LOGO,),
    ),
    LogoTarget(
        "Warner-channel.co",
        "https://mi.tv/co/canales/warner",
        (WARNER_LOGO,),
    ),
)


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"ADVERTENCIA: {message}", file=sys.stderr, flush=True)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "es-EC,es;q=0.9,en;q=0.7",
            "Accept": "*/*",
        }
    )
    return s


def request_bytes(s: requests.Session, url: str, *, attempts: int = 4) -> bytes:
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = s.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            if not response.content:
                raise RuntimeError(f"respuesta vacía desde {url}")
            return response.content
        except (requests.RequestException, RuntimeError) as exc:
            error = exc
            if attempt < attempts:
                time.sleep(min(2 * attempt, 6))
    raise RuntimeError(f"no se pudo descargar {url}: {error}") from error


def decode_source_xml(payload: bytes) -> bytes:
    if payload.startswith(b"\x1f\x8b"):
        return gzip.decompress(payload)
    return payload


_XMLTV_RE = re.compile(
    r"^\s*(\d{8}|\d{10}|\d{12}|\d{14})(?:\s*([+-]\d{4}|Z))?\s*$"
)


def parse_xmltv_datetime(value: str, default_tz: ZoneInfo = OUTPUT_TZ) -> datetime:
    match = _XMLTV_RE.match(value or "")
    if not match:
        raise ValueError(f"marca XMLTV no soportada: {value!r}")
    digits, offset = match.groups()
    formats = {
        8: "%Y%m%d",
        10: "%Y%m%d%H",
        12: "%Y%m%d%H%M",
        14: "%Y%m%d%H%M%S",
    }
    naive = datetime.strptime(digits, formats[len(digits)])
    if offset == "Z":
        aware = naive.replace(tzinfo=timezone.utc)
    elif offset:
        sign = 1 if offset[0] == "+" else -1
        delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))
        aware = naive.replace(tzinfo=timezone(sign * delta))
    else:
        aware = naive.replace(tzinfo=default_tz)
    return aware


def format_xmltv(dt: datetime) -> str:
    return dt.astimezone(OUTPUT_TZ).strftime("%Y%m%d%H%M%S %z")


def safe_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )


def select_source_channel(root: etree._Element, preferred: str) -> etree._Element:
    exact = root.xpath("./channel[@id=$channel_id]", channel_id=preferred)
    if exact:
        return exact[0]
    token = "CBS.(WCBS).New.York"
    candidates = [
        node
        for node in root.findall("channel")
        if token in (node.get("id") or "")
    ]
    if len(candidates) == 1:
        return candidates[0]
    ids = [node.get("id") for node in candidates]
    raise RuntimeError(f"EPGShare US1: no se encontró WCBS de forma inequívoca: {ids}")


def clone_cbs_from_epgshare(
    payload: bytes,
    window_start: datetime,
    window_end: datetime,
) -> tuple[etree._Element, list[etree._Element], str | None]:
    xml = decode_source_xml(payload)
    root = etree.fromstring(xml, parser=safe_parser())
    source_channel = select_source_channel(root, CBS_SOURCE_ID)
    source_id = source_channel.get("id") or CBS_SOURCE_ID
    icon_src = None
    source_icon = source_channel.find("icon")
    if source_icon is not None:
        icon_src = source_icon.get("src")

    channel = etree.Element("channel", id=CBS_ID)
    display = etree.SubElement(channel, "display-name")
    display.text = CBS_NAME

    programmes: list[etree._Element] = []
    for node in root.findall("programme"):
        if node.get("channel") != source_id:
            continue
        start_raw = node.get("start")
        stop_raw = node.get("stop")
        if not start_raw or not stop_raw:
            continue
        try:
            start = parse_xmltv_datetime(start_raw, NEW_YORK_TZ).astimezone(OUTPUT_TZ)
            stop = parse_xmltv_datetime(stop_raw, NEW_YORK_TZ).astimezone(OUTPUT_TZ)
        except ValueError:
            continue
        if stop <= window_start or start >= window_end or stop <= start:
            continue
        item = copy.deepcopy(node)
        item.set("channel", CBS_ID)
        item.set("start", format_xmltv(start))
        item.set("stop", format_xmltv(stop))
        programmes.append(item)
    programmes.sort(key=lambda node: node.get("start", ""))
    if len(programmes) < MIN_PROGRAMMES_PER_CHANNEL:
        raise RuntimeError(
            f"EPGShare US1: WCBS devolvió solo {len(programmes)} emisiones útiles."
        )
    return channel, programmes, icon_src


_HEADER_RE = re.compile(
    r"\b(?:Hoy|Mañana)\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*-",
    re.IGNORECASE,
)
_TIME_LINE_RE = re.compile(r"^(\d{1,2}:\d{2})(.*)$")


def _parse_date_token(token: str) -> date:
    token = token.strip()
    fmt = "%d/%m/%Y" if len(token.rsplit("/", 1)[-1]) == 4 else "%d/%m/%y"
    return datetime.strptime(token, fmt).date()


def parse_americatvguide_oromar(html: str) -> list[tuple[datetime, str]]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True).replace("\xa0", " ")
    raw_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in raw_lines if line]

    sections: dict[date, list[tuple[str, str]]] = {}
    current_date: date | None = None
    pending_time: str | None = None

    for line in lines:
        header = _HEADER_RE.search(line)
        if header:
            current_date = _parse_date_token(header.group(1))
            sections.setdefault(current_date, [])
            pending_time = None
            continue
        if current_date is None:
            continue

        cleaned = line.lstrip("|•· ").strip()
        match = _TIME_LINE_RE.match(cleaned)
        if match:
            hhmm = match.group(1)
            title = match.group(2).strip(" |–—-\t")
            if title:
                sections[current_date].append((hhmm, title))
                pending_time = None
            else:
                pending_time = hhmm
            continue
        if pending_time:
            # Título separado del horario en otra celda/nodo.
            if not _HEADER_RE.search(cleaned):
                sections[current_date].append((pending_time, cleaned))
            pending_time = None

    if not sections:
        # Respaldo para HTML muy aplanado: secciona directamente sobre el texto.
        matches = list(_HEADER_RE.finditer(text))
        for index, header in enumerate(matches):
            day = _parse_date_token(header.group(1))
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            chunk = text[header.end() : end]
            found = []
            for row in re.finditer(
                r"(?:^|\n|\|)\s*(\d{1,2}:\d{2})\s+([^\n|]+)",
                chunk,
            ):
                found.append((row.group(1), row.group(2).strip()))
            if found:
                sections[day] = found

    absolute: list[tuple[datetime, str]] = []
    for day in sorted(sections):
        rows = sections[day]
        # Algunas guías repiten como primera fila un programa iniciado la víspera.
        if len(rows) >= 2:
            first_hour = int(rows[0][0].split(":", 1)[0])
            second_hour = int(rows[1][0].split(":", 1)[0])
            if first_hour >= 20 and second_hour <= 5:
                rows = rows[1:]

        rollover = 0
        previous_minutes: int | None = None
        for hhmm, title in rows:
            hour, minute = (int(part) for part in hhmm.split(":", 1))
            if hour > 23 or minute > 59:
                continue
            minutes = hour * 60 + minute
            if previous_minutes is not None and minutes <= previous_minutes:
                rollover += 1
            start = datetime.combine(
                day + timedelta(days=rollover),
                dt_time(hour, minute),
                tzinfo=OUTPUT_TZ,
            )
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                absolute.append((start, title))
            previous_minutes = minutes

    # Deduplica la fila 00:00 que suele aparecer al final de hoy y al inicio de mañana.
    dedup: dict[tuple[datetime, str], None] = {}
    for item in absolute:
        dedup.setdefault(item, None)
    result = sorted(dedup, key=lambda item: item[0])
    return result


def build_oromar_programmes(
    html: str,
    window_start: datetime,
    window_end: datetime,
) -> tuple[etree._Element, list[etree._Element], int]:
    schedule = parse_americatvguide_oromar(html)
    if len(schedule) < MIN_PROGRAMMES_PER_CHANNEL + 1:
        raise RuntimeError(
            f"AmericaTVGuide Oromar: solo se detectaron {len(schedule)} inicios."
        )

    channel = etree.Element("channel", id=OROMAR_ID)
    display = etree.SubElement(channel, "display-name")
    display.text = OROMAR_NAME

    programmes: list[etree._Element] = []
    loaded_days: set[date] = set()
    for index, (start, title) in enumerate(schedule):
        if index + 1 < len(schedule):
            stop = schedule[index + 1][0]
        else:
            stop = start + timedelta(hours=1)
        if stop <= start or stop - start > timedelta(hours=8):
            continue
        if stop <= window_start or start >= window_end:
            continue
        node = etree.Element(
            "programme",
            start=format_xmltv(start),
            stop=format_xmltv(stop),
            channel=OROMAR_ID,
        )
        title_node = etree.SubElement(node, "title", lang="es")
        title_node.text = title
        programmes.append(node)
        loaded_days.add(start.astimezone(OUTPUT_TZ).date())

    if len(programmes) < MIN_PROGRAMMES_PER_CHANNEL:
        raise RuntimeError(
            f"AmericaTVGuide Oromar: solo {len(programmes)} emisiones dentro de la ventana."
        )
    return channel, programmes, len(loaded_days)


def clone_previous_channel(
    previous_xml: Path,
    channel_id: str,
    display_name: str,
    window_start: datetime,
    window_end: datetime,
) -> tuple[etree._Element, list[etree._Element]] | None:
    if not previous_xml.is_file() or previous_xml.stat().st_size == 0:
        return None
    root = etree.parse(str(previous_xml), safe_parser()).getroot()
    channels = root.xpath("./channel[@id=$channel_id]", channel_id=channel_id)
    if not channels:
        return None
    channel = copy.deepcopy(channels[0])
    # El display-name se normaliza para evitar arrastrar alias viejos.
    displays = channel.findall("display-name")
    if displays:
        displays[0].text = display_name
    else:
        etree.SubElement(channel, "display-name").text = display_name

    programmes: list[etree._Element] = []
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=channel_id):
        try:
            start = parse_xmltv_datetime(node.get("start", ""), OUTPUT_TZ).astimezone(OUTPUT_TZ)
            stop = parse_xmltv_datetime(node.get("stop", ""), OUTPUT_TZ).astimezone(OUTPUT_TZ)
        except ValueError:
            continue
        if stop <= window_start or start >= window_end or stop <= start:
            continue
        item = copy.deepcopy(node)
        item.set("start", format_xmltv(start))
        item.set("stop", format_xmltv(stop))
        programmes.append(item)
    programmes.sort(key=lambda node: node.get("start", ""))
    if len(programmes) < MIN_PROGRAMMES_PER_CHANNEL:
        return None
    return channel, programmes


def image_to_png(payload: bytes) -> tuple[bytes, int, int]:
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("imagen mayor de 8 MB")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            width, height = image.size
            if width < 32 or height < 32:
                raise ValueError(f"imagen demasiado pequeña: {width}x{height}")
            if width > 5000 or height > 5000:
                raise ValueError(f"imagen demasiado grande: {width}x{height}")
            converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            out = io.BytesIO()
            converted.save(out, format="PNG", optimize=True)
            png = out.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"contenido no es una imagen compatible: {exc}") from exc
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Pillow no produjo un PNG válido")
    return png, width, height


def validate_cached_png(path: Path) -> tuple[int, int, str] | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    data = path.read_bytes()
    try:
        _png, width, height = image_to_png(data)
    except ValueError:
        return None
    return width, height, hashlib.sha256(data).hexdigest()


def existing_channel_icon(root: etree._Element, channel_id: str) -> str | None:
    nodes = root.xpath("./channel[@id=$channel_id]", channel_id=channel_id)
    if not nodes:
        return None
    icon = nodes[0].find("icon")
    if icon is not None:
        src = (icon.get("src") or "").strip()
        if src.startswith(("http://", "https://")) and not src.startswith(LOCAL_LOGO_BASE):
            return src
    return None


def ensure_logos(
    root: etree._Element,
    logos_dir: Path,
    manifest_path: Path,
    s: requests.Session,
    extra_candidates: dict[str, Sequence[str]] | None = None,
) -> dict[str, dict[str, object]]:
    logos_dir.mkdir(parents=True, exist_ok=True)
    previous: dict[str, object] = {}
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = {}
    channels_obj = previous.get("channels")
    channels: dict[str, dict[str, object]] = (
        dict(channels_obj) if isinstance(channels_obj, dict) else {}
    )
    extra_candidates = extra_candidates or {}

    for target in LOGO_TARGETS:
        path = logos_dir / f"{target.channel_id}.png"
        candidates: list[str] = []
        current_icon = existing_channel_icon(root, target.channel_id)
        if current_icon:
            candidates.append(current_icon)
        candidates.extend(extra_candidates.get(target.channel_id, ()))
        candidates.extend(target.candidates)
        # Mantiene orden, elimina duplicados.
        candidates = list(dict.fromkeys(url for url in candidates if url))

        selected_url: str | None = None
        selected_png: bytes | None = None
        width = height = 0
        errors: list[str] = []
        for url in candidates:
            try:
                payload = request_bytes(s, url)
                png, width, height = image_to_png(payload)
            except (RuntimeError, ValueError) as exc:
                errors.append(f"{url}: {exc}")
                continue
            selected_url = url
            selected_png = png
            break

        source = "downloaded"
        if selected_png is not None:
            path.write_bytes(selected_png)
            sha = hashlib.sha256(selected_png).hexdigest()
        else:
            cached = validate_cached_png(path)
            if cached is None:
                detail = "; ".join(errors) or "sin candidatos"
                raise RuntimeError(
                    f"Logo {target.channel_id}: no se pudo obtener ni conservar PNG: {detail}"
                )
            width, height, sha = cached
            source = "cache"
            old = channels.get(target.channel_id)
            if isinstance(old, dict):
                selected_url = str(old.get("source_url") or "") or None
            warn(
                f"Logo {target.channel_id}: fuentes remotas no disponibles; se conserva caché."
            )

        channels[target.channel_id] = {
            "page_url": target.page_url,
            "local_url": f"{LOCAL_LOGO_BASE}{target.channel_id}.png",
            "available": True,
            "source": source,
            "source_url": selected_url,
            "width": width,
            "height": height,
            "sha256": sha,
        }
        log(
            f"Logo {target.channel_id}: {source}; {width}x{height}; "
            f"{channels[target.channel_id]['local_url']}"
        )

    # Compatibilidad: validate_outputs.py interpreta targets/available/missing como
    # contadores del subsistema de logos base generado antes de esta extensión.
    # Los cinco logos de v0.2.39 viven en channels, pero no alteran esos contadores.
    previous_channel_ids = set(channels_obj) if isinstance(channels_obj, dict) else set()
    core_ids = sorted(previous_channel_ids - set(LOGO_IDS))
    core_available = [
        channel_id
        for channel_id in core_ids
        if isinstance(channels.get(channel_id), dict)
        and channels[channel_id].get("available") is True
    ]
    core_missing = sorted(set(core_ids) - set(core_available))
    manifest = {
        "generated_at": datetime.now(OUTPUT_TZ).isoformat(),
        "public_base_url": LOCAL_LOGO_BASE.rstrip("/"),
        "targets": int(previous.get("targets", len(core_ids))),
        "available": len(core_available),
        "missing": core_missing,
        "channels": channels,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return channels


def set_local_icon(root: etree._Element, channel_id: str) -> None:
    nodes = root.xpath("./channel[@id=$channel_id]", channel_id=channel_id)
    if len(nodes) != 1:
        raise RuntimeError(f"No existe exactamente un channel para {channel_id}: {len(nodes)}")
    channel = nodes[0]
    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    icon = etree.Element("icon")
    icon.set("src", f"{LOCAL_LOGO_BASE}{channel_id}.png")
    # XMLTV DTD: display-name+, icon*, url*. Inserta antes del primer <url>.
    insert_at = len(channel)
    for index, child in enumerate(channel):
        if child.tag == "url":
            insert_at = index
            break
    channel.insert(insert_at, icon)


def remove_target(root: etree._Element, channel_id: str) -> None:
    for node in root.xpath("./channel[@id=$channel_id]", channel_id=channel_id):
        root.remove(node)
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=channel_id):
        root.remove(node)


def append_channel(root: etree._Element, channel: etree._Element, programmes: Iterable[etree._Element]) -> None:
    # Los <channel> deben permanecer antes de <programme>. Inserta antes del primer programa.
    first_programme = root.find("programme")
    if first_programme is None:
        root.append(channel)
    else:
        root.insert(root.index(first_programme), channel)
    for programme in programmes:
        root.append(programme)


def write_xml_and_gzip(root: etree._Element, xml_path: Path, gz_path: Path) -> None:
    xml_body = etree.tostring(root, encoding="UTF-8", pretty_print=True).decode("utf-8")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n' + xml_body
    data = text.encode("utf-8")
    xml_path.write_bytes(data)
    with gz_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as fh:
            fh.write(data)


def update_index(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    replacements = (
        ("Guía seleccionada de 32 canales", "Guía seleccionada de 34 canales"),
        ("guía seleccionada de 32 canales", "guía seleccionada de 34 canales"),
        ("32 canales", "34 canales"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def update_status(
    path: Path,
    cbs_mode: str,
    cbs_count: int,
    oromar_mode: str,
    oromar_count: int,
    oromar_days: int,
) -> None:
    if path.is_file():
        status = json.loads(path.read_text(encoding="utf-8"))
    else:
        status = {}
    status["channels"] = EXPECTED_FINAL_CHANNELS
    counts = status.get("programme_counts")
    if not isinstance(counts, dict):
        counts = {}
        status["programme_counts"] = counts
    counts[CBS_ID] = cbs_count
    counts[OROMAR_ID] = oromar_count
    sources = status.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        status["sources"] = sources
    sources["v039"] = {
        CBS_ID: CBS_SOURCE_URL,
        OROMAR_ID: OROMAR_SOURCE_URL,
    }
    status["v039_epg"] = {
        "version": VERSION,
        "output_timezone": "America/Guayaquil",
        "manual_offset_minutes": 0,
        "channels": {
            CBS_ID: {
                "mode": cbs_mode,
                "source": CBS_SOURCE_URL,
                "source_timezone": "America/New_York / explicit XMLTV offset",
                "output_timezone": "America/Guayaquil",
                "programmes": cbs_count,
            },
            OROMAR_ID: {
                "mode": oromar_mode,
                "source": OROMAR_SOURCE_URL,
                "source_timezone": "America/Guayaquil",
                "output_timezone": "America/Guayaquil",
                "programmes": oromar_count,
                "loaded_days": oromar_days,
            },
        },
        "logos": list(LOGO_IDS),
    }
    path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def ensure_expected_input(root: etree._Element) -> None:
    ids = [node.get("id", "") for node in root.findall("channel")]
    # Idempotencia: si el script se reejecuta sobre una salida propia, retira primero los dos objetivos.
    base = [channel_id for channel_id in ids if channel_id not in TARGET_IDS]
    if len(base) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError(
            f"v0.2.39 espera 32 canales antes de CBS/Oromar; obtuvo {len(base)}."
        )
    if len(set(base)) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError("La entrada LATAM contiene IDs duplicados.")


def self_test() -> int:
    # DST: 12:00 EDT en Nueva York = 11:00 en Ecuador.
    parsed = parse_xmltv_datetime("20260829120000 -0400", NEW_YORK_TZ).astimezone(OUTPUT_TZ)
    assert parsed.strftime("%Y%m%d%H%M%S %z") == "20260829110000 -0500"
    # Invierno: EST y Ecuador coinciden en UTC-5.
    parsed = parse_xmltv_datetime("20261201120000 -0500", NEW_YORK_TZ).astimezone(OUTPUT_TZ)
    assert parsed.strftime("%Y%m%d%H%M%S %z") == "20261201120000 -0500"

    sample = """
    <html><body>
      <h5>Hoy - 29/8/26 - Sábado</h5>
      <div>00:00 Mar de risas</div><div>02:30 El Talismán</div>
      <div>03:30 Corazón apasionado</div><div>04:30 Noticias Oromar</div>
      <div>05:00 Iglesia universal</div><div>06:00 Desde tempranito</div>
      <div>07:00 Noticias Oromar - Primera emisión</div>
      <div>08:00 El Talismán</div><div>09:00 Walker Ranger Texas</div>
      <div>10:00 Bonanza</div><div>00:00 Mar de risas</div>
      <h5>Mañana - 30/8/26 - Domingo</h5>
      <span>00:00</span><span>Mar de risas</span>
      <div>02:30 El Talismán</div><div>03:30 Corazón apasionado</div>
      <div>04:30 Noticias Oromar</div><div>05:00 Iglesia universal</div>
      <div>06:00 Desde tempranito</div><div>07:00 Noticias Oromar</div>
    </body></html>
    """
    schedule = parse_americatvguide_oromar(sample)
    assert len(schedule) >= 16, schedule
    assert schedule[0][0].strftime("%Y-%m-%d %H:%M") == "2026-08-29 00:00"
    assert any(title == "Noticias Oromar - Primera emisión" for _start, title in schedule)

    start = datetime(2026, 8, 29, 0, 0, tzinfo=OUTPUT_TZ)
    channel, programmes, days = build_oromar_programmes(
        sample, start, start + timedelta(days=3)
    )
    assert channel.get("id") == OROMAR_ID
    assert len(programmes) >= MIN_PROGRAMMES_PER_CHANNEL
    assert days >= 2
    assert all(node.get("start", "").endswith(" -0500") for node in programmes)

    image = Image.new("RGB", (64, 48), "white")
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    png, width, height = image_to_png(buf.getvalue())
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (width, height) == (64, 48)

    assert TARGET_IDS == (CBS_ID, OROMAR_ID)
    assert len(LOGO_IDS) == 5
    assert EXPECTED_FINAL_CHANNELS == 34
    log("Prueba v0.2.39 correcta: horarios, Oromar, PNG y guardias validados.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--previous-latam-xml", type=Path, default=Path(".cache/previous-latam.xml")
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.days < 1 or args.days > 14:
        raise SystemExit("--days debe estar entre 1 y 14")

    output = args.output
    xml_path = output / "latam.xml"
    gz_path = output / "latam.xml.gz"
    status_path = output / "latam-status.json"
    index_path = output / "index.html"
    logos_dir = output / "logos"
    manifest_path = logos_dir / "manifest.json"
    if not xml_path.is_file():
        raise SystemExit(f"No existe {xml_path}")

    root = etree.parse(str(xml_path), safe_parser()).getroot()
    ensure_expected_input(root)
    for target_id in TARGET_IDS:
        remove_target(root, target_id)

    now_local = datetime.now(OUTPUT_TZ)
    window_start = datetime.combine(now_local.date(), dt_time.min, tzinfo=OUTPUT_TZ)
    window_end = window_start + timedelta(days=args.days)
    s = session()

    # CBS New York.
    cbs_mode = "epgshare-us1-live"
    cbs_extra_logo: str | None = None
    try:
        cbs_payload = request_bytes(s, CBS_SOURCE_URL)
        cbs_channel, cbs_programmes, cbs_extra_logo = clone_cbs_from_epgshare(
            cbs_payload, window_start, window_end
        )
    except Exception as exc:  # noqa: BLE001 - fallback deliberado a caché publicada
        warn(f"CBS New York: fuente primaria falló: {exc}")
        previous = clone_previous_channel(
            args.previous_latam_xml, CBS_ID, CBS_NAME, window_start, window_end
        )
        if previous is None:
            raise RuntimeError(
                "CBS New York: EPGShare US1 falló y no existe fallback previo utilizable."
            ) from exc
        cbs_channel, cbs_programmes = previous
        cbs_mode = "previous-latam-cache"
    append_channel(root, cbs_channel, cbs_programmes)
    log(f"CBS New York: {len(cbs_programmes)} emisiones; modo={cbs_mode}.")

    # Oromar TV.
    oromar_mode = "americatvguide-live"
    try:
        oromar_html = request_bytes(s, OROMAR_SOURCE_URL).decode("utf-8", errors="replace")
        oromar_channel, oromar_programmes, oromar_days = build_oromar_programmes(
            oromar_html, window_start, window_end
        )
    except Exception as exc:  # noqa: BLE001 - fallback deliberado a caché publicada
        warn(f"Oromar TV: fuente primaria falló: {exc}")
        previous = clone_previous_channel(
            args.previous_latam_xml, OROMAR_ID, OROMAR_NAME, window_start, window_end
        )
        if previous is None:
            raise RuntimeError(
                "Oromar TV: AmericaTVGuide falló y no existe fallback previo utilizable."
            ) from exc
        oromar_channel, oromar_programmes = previous
        oromar_days = len(
            {
                parse_xmltv_datetime(node.get("start", ""), OUTPUT_TZ)
                .astimezone(OUTPUT_TZ)
                .date()
                for node in oromar_programmes
            }
        )
        oromar_mode = "previous-latam-cache"
    append_channel(root, oromar_channel, oromar_programmes)
    log(
        f"Oromar TV: {len(oromar_programmes)} emisiones; días={oromar_days}; "
        f"modo={oromar_mode}."
    )

    channel_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(channel_ids) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError(
            f"v0.2.39 debe dejar {EXPECTED_FINAL_CHANNELS} canales; obtenidos={len(channel_ids)}"
        )
    if channel_ids[-2:] != TARGET_IDS:
        raise RuntimeError(f"CBS/Oromar no quedaron al final: {channel_ids[-2:]}")
    if len(set(channel_ids)) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError("v0.2.39 produjo IDs duplicados")

    extra_logo_candidates: dict[str, Sequence[str]] = {}
    if cbs_extra_logo:
        extra_logo_candidates[CBS_ID] = (cbs_extra_logo,)
    ensure_logos(root, logos_dir, manifest_path, s, extra_logo_candidates)
    for channel_id in LOGO_IDS:
        set_local_icon(root, channel_id)

    # Verificación final de los dos canales y los cinco logos antes de escribir.
    for channel_id in TARGET_IDS:
        count = len(root.xpath("./programme[@channel=$channel_id]", channel_id=channel_id))
        if count < MIN_PROGRAMMES_PER_CHANNEL:
            raise RuntimeError(f"{channel_id}: programación insuficiente ({count})")
    for channel_id in LOGO_IDS:
        path = logos_dir / f"{channel_id}.png"
        if validate_cached_png(path) is None:
            raise RuntimeError(f"{channel_id}: PNG local ausente o inválido")

    write_xml_and_gzip(root, xml_path, gz_path)
    update_status(
        status_path,
        cbs_mode,
        len(cbs_programmes),
        oromar_mode,
        len(oromar_programmes),
        oromar_days,
    )
    update_index(index_path)
    log(
        "v0.2.39 aplicada: 34 canales; CBS New York y Oromar añadidos; "
        "5 logos locales asegurados; offset manual=0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

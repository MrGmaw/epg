#!/usr/bin/env python3
"""EPG MrG v0.2.39: añade CBS New York y Oromar TV y asegura 5 logos locales.

Se ejecuta después de ``add_miami_epg.py`` sobre el ``latam.xml`` de 32 canales.

Fuentes:
- CBS New York / WCBS-TV: TVPassport (WCBS 4555) como fuente primaria;
  EPGShare US1 como respaldo. Las horas se convierten con ZoneInfo desde
  America/New_York a America/Guayaquil. Nunca se aplica un offset manual.
- Oromar TV: AmericaTVListings Ecuador y AmericaTVGuide se intentan solo
  como fuentes en vivo de actualización. Como ambos servicios pueden devolver
  HTTP 403 a GitHub Actions, existe una parrilla semanal local garantizada,
  basada en la grilla continental GMT-5 vigente al 29-08-2026 y contrastada
  con Oromar TV. Nunca se aplica un offset manual.

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
CBS_TVPASSPORT_BASE = "https://www.tvpassport.com/tv-listings/stations"
CBS_TVPASSPORT_SITE_IDS = (
    "cbs-wcbs-new-york-ny-hd/4555",
    "cbs-wcbs-new-york-ny/1766",
)
CBS_TVPASSPORT_PAGE = (
    f"{CBS_TVPASSPORT_BASE}/{CBS_TVPASSPORT_SITE_IDS[0]}"
)
CBS_PAGE_URL = "https://www.cbsnews.com/newyork/cbs2/"
CBS_LOGO_URL = (
    "https://assets2.cbsnewsstatic.com/hub/i/r/2024/07/26/"
    "c486368f-8a23-4d85-a7c6-569b3e9406c0/thumbnail/620x349/"
    "dfabdc6cf76863f0fac74ab6a394b1c4/lockup-logo-black.png"
)

OROMAR_ID = "OromarTV.ec"
OROMAR_NAME = "Oromar TV"
OROMAR_LISTINGS_URL = "https://americatvlistings.com/es/ec-ECT/oromar-tv"
OROMAR_SOURCE_URL = "https://americatvguide.com/es/ec/channel/oromar_tv"
OROMAR_PAGE_URL = "https://oromartv.com/"
OROMAR_LOGO_URL = "https://oromartv.com/images/OTV400.png"
OROMAR_BUNDLED_SOURCE = "bundled-weekly-grid-2026-08-29"

# Parrilla continental (America/Guayaquil, UTC-5) verificada al 29-08-2026.
# Se conserva en el repositorio como salvaguarda porque AmericaTVListings y
# AmericaTVGuide responden 403 a IPs de GitHub Actions. La parrilla de lunes a
# viernes coincide además con los horarios recurrentes publicados por Oromar.
OROMAR_WEEKLY_GRID: dict[int, tuple[tuple[str, str], ...]] = {
    # Lunes a viernes
    **{weekday: (
        ("00:00", "Mar de risas"),
        ("02:30", "El Talismán"),
        ("03:30", "Corazón apasionado"),
        ("04:30", "Noticias Oromar"),
        ("05:00", "Iglesia universal"),
        ("06:00", "Desde tempranito"),
        ("07:00", "Noticias Oromar - Primera emisión"),
        ("08:00", "El Talismán"),
        ("09:00", "Walker Ranger Texas"),
        ("10:00", "Bonanza"),
        ("11:00", "Bonanza"),
        ("12:00", "Noticias Oromar - Segunda emisión"),
        ("13:00", "Comunidad Oromar"),
        ("14:00", "Triunfo del amor"),
        ("15:00", "Triunfo del amor"),
        ("16:00", "La hija del Mariachi"),
        ("17:00", "Bonanza"),
        ("18:00", "Bonanza"),
        ("19:00", "Noticias Oromar - Tercera emisión"),
        ("20:00", "BLN: La dinastía"),
        ("22:30", "Noticias Oromar"),
        ("23:00", "Iglesia universal"),
    ) for weekday in range(5)},
    # Sábado, parrilla continental ec-ECT del 29-08-2026.
    5: (
        ("00:00", "Iglesia universal"),
        ("01:00", "Así se hace Ecuador"),
        ("03:30", "Ecuador multicolor"),
        ("06:00", "Mar de risas"),
        ("07:00", "Outlet TV"),
        ("08:30", "Promo TV"),
        ("09:00", "Conversando con Orlando"),
        ("09:30", "Promo TV"),
        ("11:00", "Outlet TV"),
        ("12:00", "Promo TV"),
        ("12:30", "Walker Ranger Texas"),
        ("14:00", "El gran Chaparral"),
        ("16:00", "Bonanza"),
        ("19:00", "Butaca Premiere"),
        ("21:00", "El gran Chaparral"),
        ("23:00", "Walker Ranger Texas"),
    ),
    # Domingo, parrilla continental ec-ECT del 30-08-2026.
    6: (
        ("00:00", "Iglesia universal"),
        ("01:00", "Así se hace Ecuador"),
        ("03:30", "Ecuador multicolor"),
        ("06:00", "Mar de risas"),
        ("07:00", "Outlet TV"),
        ("08:30", "Video control"),
        ("09:00", "Iglesia universal"),
        ("11:00", "Mundo TV"),
        ("12:30", "Walker Ranger Texas"),
        ("14:00", "El gran Chaparral"),
        ("16:00", "Bonanza"),
        ("19:00", "Butaca Premiere"),
        ("21:00", "El gran Chaparral"),
        ("23:00", "Walker Ranger Texas"),
    ),
}

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
TVPASSPORT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
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


def request_bytes(s: requests.Session, url: str, *, attempts: int = 4, headers: dict[str, str] | None = None) -> bytes:
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = s.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
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


def parse_tvpassport_cbs(
    html: str,
    window_start: datetime,
    window_end: datetime,
) -> list[etree._Element]:
    """Parsea una página diaria de TVPassport siguiendo su estructura pública.

    TVPassport expone cada emisión como ``.station-listings .list-group-item``
    con ``data-st`` y ``data-duration``. El selector ``#timezone_selector``
    indica la zona horaria de esas marcas; si no aparece, WCBS se interpreta
    como America/New_York.
    """
    soup = BeautifulSoup(html, "html.parser")
    selector = soup.select_one("#timezone_selector")
    timezone_name = "America/New_York"
    if selector is not None:
        selected = selector.select_one("option[selected]")
        candidate = (
            (selected.get("value") if selected is not None else None)
            or selector.get("value")
        )
        if candidate:
            timezone_name = str(candidate).strip()
    try:
        source_tz = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - página externa puede traer una zona inesperada
        source_tz = NEW_YORK_TZ

    programmes: list[etree._Element] = []
    for item in soup.select(".station-listings .list-group-item"):
        start_raw = str(item.get("data-st") or "").strip()
        duration_raw = str(item.get("data-duration") or "").strip()
        title = str(item.get("data-showname") or "").strip()
        if not start_raw or not duration_raw or not title:
            continue
        try:
            naive = datetime.strptime(start_raw, "%Y-%m-%d %H:%M:%S")
            start = naive.replace(tzinfo=source_tz).astimezone(OUTPUT_TZ)
            duration = int(float(duration_raw))
        except (ValueError, TypeError):
            continue
        if duration <= 0 or duration > 24 * 60:
            continue
        stop = start + timedelta(minutes=duration)
        if stop <= window_start or start >= window_end:
            continue

        node = etree.Element(
            "programme",
            start=format_xmltv(start),
            stop=format_xmltv(stop),
            channel=CBS_ID,
        )
        title_node = etree.SubElement(node, "title", lang="en")
        title_node.text = title
        subtitle = str(item.get("data-episodetitle") or "").strip()
        if subtitle:
            subtitle_node = etree.SubElement(node, "sub-title", lang="en")
            subtitle_node.text = subtitle
        description = str(item.get("data-description") or "").strip()
        if description:
            desc_node = etree.SubElement(node, "desc", lang="en")
            desc_node.text = description
        categories = str(item.get("data-showtype") or "").strip()
        if categories:
            for category in (part.strip() for part in categories.split(",")):
                if category:
                    category_node = etree.SubElement(node, "category", lang="en")
                    category_node.text = category
        programmes.append(node)
    return programmes


def build_cbs_from_tvpassport(
    s: requests.Session,
    window_start: datetime,
    window_end: datetime,
) -> tuple[etree._Element, list[etree._Element], str]:
    """Descarga WCBS de TVPassport; prueba HD y luego SD.

    Se solicitan fechas de Nueva York con un día de margen a ambos extremos,
    porque una página diaria puede contener emisiones posteriores a medianoche.
    """
    start_date = window_start.astimezone(NEW_YORK_TZ).date() - timedelta(days=1)
    end_date = window_end.astimezone(NEW_YORK_TZ).date() + timedelta(days=1)
    errors: list[str] = []
    headers = {
        "User-Agent": TVPASSPORT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for site_id in CBS_TVPASSPORT_SITE_IDS:
        programmes_by_key: dict[tuple[str, str, str], etree._Element] = {}
        loaded_pages = 0
        page_errors: list[str] = []
        current = start_date
        while current <= end_date:
            url = f"{CBS_TVPASSPORT_BASE}/{site_id}/{current.isoformat()}"
            try:
                payload = request_bytes(s, url, attempts=3, headers=headers)
                html = payload.decode("utf-8", errors="replace")
                daily = parse_tvpassport_cbs(html, window_start, window_end)
            except Exception as exc:  # noqa: BLE001 - una fecha no invalida toda la fuente
                page_errors.append(f"{current.isoformat()}: {exc}")
                current += timedelta(days=1)
                continue
            if daily:
                loaded_pages += 1
            for node in daily:
                title_node = node.find("title")
                key = (
                    node.get("start", ""),
                    node.get("stop", ""),
                    title_node.text if title_node is not None and title_node.text else "",
                )
                programmes_by_key[key] = node
            current += timedelta(days=1)

        programmes = sorted(
            programmes_by_key.values(), key=lambda node: node.get("start", "")
        )
        if len(programmes) >= MIN_PROGRAMMES_PER_CHANNEL:
            channel = etree.Element("channel", id=CBS_ID)
            display = etree.SubElement(channel, "display-name")
            display.text = CBS_NAME
            return channel, programmes, f"tvpassport-live:{site_id};pages={loaded_pages}"
        detail = "; ".join(page_errors[:3])
        if len(page_errors) > 3:
            detail += f"; +{len(page_errors) - 3} errores más"
        errors.append(
            f"{site_id}: solo {len(programmes)} emisiones útiles ({loaded_pages} páginas)"
            + (f"; errores={detail}" if detail else "")
        )

    raise RuntimeError("TVPassport WCBS no produjo guía suficiente: " + " | ".join(errors))


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




_LISTINGS_DATE_RE = re.compile(
    r"(?im)^(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo),\s*"
    r"(\d{1,2}/\d{1,2}/\d{2,4})(?:,|$)"
)
_LISTINGS_TIME_RE = re.compile(r"^(\d{1,2}:\d{2})\s+(.+)$")

def _parse_listings_date(token: str) -> date:
    parts = [int(x) for x in token.split("/")]
    if len(parts) != 3:
        raise ValueError(f"fecha AmericaTVListings inválida: {token!r}")
    day, month, year = parts
    if year < 100:
        year += 2000
    return date(year, month, day)

def parse_americatvlistings_oromar(html: str) -> list[tuple[datetime, str]]:
    """Parsea la página específica de Oromar en AmericaTVListings.

    La página presenta encabezados diarios (p. ej. ``sábado, 29/08/26``) y
    emisiones con formato ``HH:MM Título``. El HTML cambia de envoltorios con
    frecuencia, por lo que se trabaja sobre texto normalizado y no sobre clases
    CSS frágiles.
    """
    soup = BeautifulSoup(html, "html.parser")
    lines = [
        re.sub(r"\s+", " ", line.replace("\xa0", " ")).strip()
        for line in soup.get_text("\n", strip=True).splitlines()
    ]
    lines = [line for line in lines if line]

    current_date: date | None = None
    rows: list[tuple[datetime, str]] = []

    for line in lines:
        date_match = _LISTINGS_DATE_RE.match(line)
        if date_match:
            current_date = _parse_listings_date(date_match.group(1))
            continue
        if current_date is None or line.lower().startswith("no results found"):
            continue
        match = _LISTINGS_TIME_RE.match(line)
        if not match:
            continue
        hhmm, title = match.groups()
        hour, minute = (int(x) for x in hhmm.split(":"))
        if hour > 23 or minute > 59:
            continue
        title = re.sub(r"\s+", " ", title).strip(" |–—-\t")
        if not title:
            continue
        rows.append((datetime.combine(current_date, dt_time(hour, minute), tzinfo=OUTPUT_TZ), title))

    # Algunos renderizados agrupan todo el día en una sola línea. Si el pase
    # anterior encontró muy poco, se segmenta por encabezados y por marcas HH:MM.
    if len(rows) < MIN_PROGRAMMES_PER_CHANNEL + 1:
        text = re.sub(r"[\t\r]+", " ", soup.get_text("\n", strip=True).replace("\xa0", " "))
        headers = list(_LISTINGS_DATE_RE.finditer(text))
        fallback_rows: list[tuple[datetime, str]] = []
        for idx, header in enumerate(headers):
            day = _parse_listings_date(header.group(1))
            end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
            chunk = text[header.end():end]
            starts = list(re.finditer(r"(?<!\d)(\d{1,2}:\d{2})\s+", chunk))
            for j, start_match in enumerate(starts):
                hour, minute = (int(x) for x in start_match.group(1).split(":"))
                if hour > 23 or minute > 59:
                    continue
                title_start = start_match.end()
                title_end = starts[j + 1].start() if j + 1 < len(starts) else len(chunk)
                title = re.sub(r"\s+", " ", chunk[title_start:title_end]).strip(" |–—-\n")
                title = re.split(r"(?:No results found|Facebook|Twitter|TV Channel|TV guide)", title, maxsplit=1)[0].strip()
                if title:
                    fallback_rows.append((datetime.combine(day, dt_time(hour, minute), tzinfo=OUTPUT_TZ), title))
        if len(fallback_rows) > len(rows):
            rows = fallback_rows

    dedup: dict[tuple[datetime, str], None] = {}
    for item in rows:
        dedup.setdefault(item, None)
    return sorted(dedup, key=lambda item: item[0])

def build_oromar_bundled_schedule(
    window_start: datetime, window_end: datetime
) -> list[tuple[datetime, str]]:
    """Genera una grilla completa sin red para la ventana solicitada.

    Se agrega el primer inicio del día siguiente como centinela para calcular
    correctamente el ``stop`` del último programa dentro de la ventana.
    """
    first_day = window_start.astimezone(OUTPUT_TZ).date()
    last_day = window_end.astimezone(OUTPUT_TZ).date()
    schedule: list[tuple[datetime, str]] = []
    day = first_day
    while day <= last_day:
        rows = OROMAR_WEEKLY_GRID[day.weekday()]
        for hhmm, title in rows:
            hour, minute = (int(part) for part in hhmm.split(":", 1))
            schedule.append(
                (datetime.combine(day, dt_time(hour, minute), tzinfo=OUTPUT_TZ), title)
            )
        day += timedelta(days=1)
    return schedule


def build_oromar_from_bundled(
    window_start: datetime, window_end: datetime
) -> tuple[etree._Element, list[etree._Element], int]:
    return build_oromar_from_schedule(
        build_oromar_bundled_schedule(window_start, window_end),
        window_start,
        window_end,
        "Oromar bundled weekly grid",
    )


def build_oromar_from_schedule(
    schedule: list[tuple[datetime, str]],
    window_start: datetime,
    window_end: datetime,
    source_name: str,
) -> tuple[etree._Element, list[etree._Element], int]:
    if len(schedule) < MIN_PROGRAMMES_PER_CHANNEL + 1:
        raise RuntimeError(f"{source_name} Oromar: solo se detectaron {len(schedule)} inicios.")

    channel = etree.Element("channel", id=OROMAR_ID)
    etree.SubElement(channel, "display-name").text = OROMAR_NAME
    programmes: list[etree._Element] = []
    loaded_days: set[date] = set()
    for index, (start, title) in enumerate(schedule):
        stop = schedule[index + 1][0] if index + 1 < len(schedule) else start + timedelta(hours=1)
        if stop <= start or stop - start > timedelta(hours=8):
            continue
        if stop <= window_start or start >= window_end:
            continue
        node = etree.Element("programme", start=format_xmltv(start), stop=format_xmltv(stop), channel=OROMAR_ID)
        etree.SubElement(node, "title", lang="es").text = title
        programmes.append(node)
        loaded_days.add(start.astimezone(OUTPUT_TZ).date())
    if len(programmes) < MIN_PROGRAMMES_PER_CHANNEL:
        raise RuntimeError(f"{source_name} Oromar: solo {len(programmes)} emisiones dentro de la ventana.")
    return channel, programmes, len(loaded_days)

def build_oromar_from_listings(
    html: str, window_start: datetime, window_end: datetime
) -> tuple[etree._Element, list[etree._Element], int]:
    return build_oromar_from_schedule(
        parse_americatvlistings_oromar(html), window_start, window_end, "AmericaTVListings"
    )


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
    return build_oromar_from_schedule(
        parse_americatvguide_oromar(html),
        window_start,
        window_end,
        "AmericaTVGuide",
    )


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
        CBS_ID: CBS_TVPASSPORT_PAGE,
        OROMAR_ID: OROMAR_LISTINGS_URL,
    }
    status["v039_epg"] = {
        "version": VERSION,
        "output_timezone": "America/Guayaquil",
        "manual_offset_minutes": 0,
        "channels": {
            CBS_ID: {
                "mode": cbs_mode,
                "source": (
                    CBS_TVPASSPORT_PAGE
                    if cbs_mode.startswith("tvpassport-live")
                    else CBS_SOURCE_URL
                    if cbs_mode == "epgshare-us1-live"
                    else "previous-latam-cache"
                ),
                "fallback_sources": [CBS_SOURCE_URL, "previous-latam-cache"],
                "source_timezone": "America/New_York / explicit XMLTV offset",
                "output_timezone": "America/Guayaquil",
                "programmes": cbs_count,
            },
            OROMAR_ID: {
                "mode": oromar_mode,
                "source": (
                    OROMAR_LISTINGS_URL
                    if oromar_mode == "americatvlistings-live"
                    else OROMAR_SOURCE_URL
                    if oromar_mode == "americatvguide-live"
                    else OROMAR_BUNDLED_SOURCE
                    if oromar_mode == "bundled-weekly-fallback"
                    else "previous-latam-cache"
                ),
                "fallback_sources": [
                    OROMAR_SOURCE_URL,
                    OROMAR_BUNDLED_SOURCE,
                    "previous-latam-cache",
                ],
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

    listings_sample = """
    <html><body>
      <h3>sábado, 29/08/26, AmericaTVListings.com</h3>
      <a>00:00 Iglesia universal</a><a>01:00 Así se hace Ecuador</a>
      <a>03:30 Ecuador multicolor</a><a>06:00 Mar de risas</a>
      <a>07:00 Outlet TV</a><a>08:30 Promo TV</a><a>09:00 Conversando con Orlando</a>
      <a>09:30 Promo TV</a><a>11:00 Outlet TV</a><a>12:00 Promo TV</a>
      <a>12:30 Walker Ranger Texas</a><a>14:00 El gran Chaparral</a>
      <h3>domingo, 30/08/26, AmericaTVListings.com</h3>
      <a>00:00 Iglesia universal</a><a>01:00 Así se hace Ecuador</a>
      <a>03:30 Ecuador multicolor</a><a>06:00 Mar de risas</a>
      <a>07:00 Outlet TV</a><a>08:30 Video control</a>
    </body></html>
    """
    listings_schedule = parse_americatvlistings_oromar(listings_sample)
    assert len(listings_schedule) >= 18, listings_schedule
    assert listings_schedule[0][0].strftime("%Y-%m-%d %H:%M %z") == "2026-08-29 00:00 -0500"
    assert any(title == "Walker Ranger Texas" for _start, title in listings_schedule)
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

    tvp_sample = """
    <select id="timezone_selector"><option value="America/New_York" selected>Eastern</option></select>
    <div class="station-listings">
      <div class="list-group-item" data-st="2026-08-29 12:00:00" data-duration="60"
           data-showname="CBS Test" data-episodetitle="Episode" data-description="Description"
           data-showtype="News, Local"></div>
    </div>
    """
    tvp = parse_tvpassport_cbs(
        tvp_sample,
        datetime(2026, 8, 29, 0, 0, tzinfo=OUTPUT_TZ),
        datetime(2026, 8, 30, 0, 0, tzinfo=OUTPUT_TZ),
    )
    assert len(tvp) == 1
    assert tvp[0].get("start") == "20260829110000 -0500"
    assert tvp[0].findtext("title") == "CBS Test"

    assert TARGET_IDS == (CBS_ID, OROMAR_ID)
    assert len(LOGO_IDS) == 5
    assert EXPECTED_FINAL_CHANNELS == 34
    test_start = datetime(2026, 8, 29, 0, 0, tzinfo=OUTPUT_TZ)
    test_end = test_start + timedelta(days=7)
    bundled_channel, bundled_programmes, bundled_days = build_oromar_from_bundled(
        test_start, test_end
    )
    assert bundled_channel.get("id") == OROMAR_ID
    assert bundled_days == 7
    assert len(bundled_programmes) >= 100
    assert all(node.get("start", "").endswith(" -0500") for node in bundled_programmes)
    bundled_titles = [node.findtext("title") for node in bundled_programmes]
    assert "Conversando con Orlando" in bundled_titles
    assert "BLN: La dinastía" in bundled_titles
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

    # CBS New York. TVPassport es primario; EPGShare y el XML previo son respaldos.
    cbs_mode = "tvpassport-live"
    cbs_extra_logo: str | None = None
    tvpassport_error: Exception | None = None
    epgshare_error: Exception | None = None
    try:
        cbs_channel, cbs_programmes, cbs_mode = build_cbs_from_tvpassport(
            s, window_start, window_end
        )
    except Exception as exc:  # noqa: BLE001 - fallback deliberado a EPGShare
        tvpassport_error = exc
        warn(f"CBS New York: TVPassport falló: {exc}")
        try:
            cbs_payload = request_bytes(s, CBS_SOURCE_URL)
            cbs_channel, cbs_programmes, cbs_extra_logo = clone_cbs_from_epgshare(
                cbs_payload, window_start, window_end
            )
            cbs_mode = "epgshare-us1-live"
        except Exception as exc2:  # noqa: BLE001 - fallback a caché publicada
            epgshare_error = exc2
            warn(f"CBS New York: EPGShare US1 falló: {exc2}")
            previous = clone_previous_channel(
                args.previous_latam_xml, CBS_ID, CBS_NAME, window_start, window_end
            )
            if previous is None:
                raise RuntimeError(
                    "CBS New York: fallaron TVPassport y EPGShare US1 y no existe "
                    "fallback previo utilizable. "
                    f"TVPassport={tvpassport_error}; EPGShare={epgshare_error}"
                ) from exc2
            cbs_channel, cbs_programmes = previous
            cbs_mode = "previous-latam-cache"
    append_channel(root, cbs_channel, cbs_programmes)
    log(f"CBS New York: {len(cbs_programmes)} emisiones; modo={cbs_mode}.")

    # Oromar TV. Las fuentes en vivo pueden bloquear GitHub Actions con 403.
    # Se prueban una sola vez y, si fallan, se usa la parrilla semanal local
    # garantizada. El XML previo queda como último salvavidas ante un error
    # interno inesperado del fallback local.
    oromar_mode = "americatvlistings-live"
    listings_error: Exception | None = None
    guide_error: Exception | None = None
    bundled_error: Exception | None = None
    try:
        listings_html = request_bytes(
            s,
            OROMAR_LISTINGS_URL,
            attempts=1,
            headers={
                "User-Agent": TVPASSPORT_USER_AGENT,
                "Accept-Language": "es-EC,es;q=0.9,en;q=0.7",
                "Referer": "https://americatvlistings.com/es/ec-ECT/0",
            },
        ).decode("utf-8", errors="replace")
        oromar_channel, oromar_programmes, oromar_days = build_oromar_from_listings(
            listings_html, window_start, window_end
        )
    except Exception as exc:  # noqa: BLE001 - fallback deliberado
        listings_error = exc
        warn(f"Oromar TV: AmericaTVListings no utilizable: {exc}")
        try:
            oromar_html = request_bytes(
                s,
                OROMAR_SOURCE_URL,
                attempts=1,
                headers={"User-Agent": TVPASSPORT_USER_AGENT},
            ).decode("utf-8", errors="replace")
            oromar_channel, oromar_programmes, oromar_days = build_oromar_programmes(
                oromar_html, window_start, window_end
            )
            oromar_mode = "americatvguide-live"
        except Exception as exc2:  # noqa: BLE001 - fallback local garantizado
            guide_error = exc2
            warn(f"Oromar TV: AmericaTVGuide no utilizable: {exc2}")
            try:
                oromar_channel, oromar_programmes, oromar_days = build_oromar_from_bundled(
                    window_start, window_end
                )
                oromar_mode = "bundled-weekly-fallback"
                warn(
                    "Oromar TV: usando parrilla semanal local porque las fuentes web "
                    "bloquearon GitHub Actions. La EPG continuará normalmente."
                )
            except Exception as exc3:  # noqa: BLE001 - último salvavidas
                bundled_error = exc3
                previous = clone_previous_channel(
                    args.previous_latam_xml, OROMAR_ID, OROMAR_NAME, window_start, window_end
                )
                if previous is None:
                    raise RuntimeError(
                        "Oromar TV: fuentes web bloqueadas y falló también la parrilla "
                        "local garantizada. "
                        f"AmericaTVListings={listings_error}; "
                        f"AmericaTVGuide={guide_error}; bundled={bundled_error}"
                    ) from exc3
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

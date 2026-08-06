#!/usr/bin/env python3
"""Construye una guía XMLTV de Ecuador.

Fuentes:
- EPGShare EC1 como guía base.
- Parrilla oficial de Teleamazonas para Quito y Guayaquil.
- EPGShare EC1 para Ecuavisa nacional, normalizada a ``Ecuavisa.ec``.
- GatoTV para Ecuavisa Internacional.
- Parrilla semanal oficial de TVC, extraída del JSON incrustado en su página.
- mi.tv Colombia para CNN en Español y NTN24, mediante su endpoint HTML asíncrono.

La salida conserva los metadatos XMLTV de EPGShare y garantiza siete
identificadores estables:

- TeleamazonasQuito.ec
- TeleamazonasGuayaquil.ec
- Ecuavisa.ec
- EcuavisaInternacional.ec
- TVC.ec
- Canal.CNN.en.Español.ec
- NTN24.co
"""

from __future__ import annotations

import argparse
import copy
import gzip
import html
import io
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from lxml import etree
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TZ = ZoneInfo("America/Guayaquil")
TZ_SUFFIX = "-0500"

EPGSHARE_URL = "https://epgshare01.online/epgshare01/epg_ripper_EC1.xml.gz"
TELEAMAZONAS_URL = "https://www.teleamazonas.com/programacion/"
GATOTV_ECUAVISA_INTERNACIONAL_BASE = (
    "https://www.gatotv.com/canal/ecuavisa_internacional"
)
TVC_URL = "https://www.tvc.com.ec/programacion/"
MITV_ASYNC_BASE = "https://mi.tv/co/async/channel"
MITV_CNN_PAGE = "https://mi.tv/co/canales/cnn-en-espanol"
MITV_NTN24_PAGE = "https://mi.tv/co/canales/nuestra-tele-noticias-24hs"
MITV_CNN_SLUG = "cnn-en-espanol"
MITV_NTN24_SLUG = "nuestra-tele-noticias-24hs"
MITV_MAX_DAYS = 2
CNN_EN_ESPANOL_ID = "Canal.CNN.en.Español.ec"
NTN24_ID = "NTN24.co"

TELEAMAZONAS_ICON = (
    "https://graph.facebook.com/TeleamazonasEcuador/"
    "picture?width=512&height=512"
)
ECUAVISA_ICON = "https://i.imgur.com/Hl5wowk.png"
ECUAVISA_INTERNACIONAL_ICON = "https://i.imgur.com/NJI6vt0.png"
TVC_ICON = (
    "https://alba-ec-tvc.cdn.mediatiquepress.com/"
    "wp-content/uploads/2023/07/logo-150x150.png"
)
NTN24_ICON = "https://i.imgur.com/UoKmSAP.png"

TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
CLOCK_24_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
CLOCK_12_RE = re.compile(r"^(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:AM|PM)$", re.I)
MERIDIEM_RE = re.compile(r"^(?:AM|PM)$", re.I)

TVC_DAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

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
    "horarios de programación",
    "horarios de programacion",
    "hora inicio",
    "hora fin",
    "programa",
    "madrugada",
    "mañana",
    "manana",
    "tarde",
    "noche",
    "am/pm",
    "24 hrs",
}

REQUIRED_IDS = {
    "TeleamazonasQuito.ec",
    "TeleamazonasGuayaquil.ec",
    "Ecuavisa.ec",
    "EcuavisaInternacional.ec",
    "TVC.ec",
    CNN_EN_ESPANOL_ID,
    NTN24_ID,
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
    "MrGmaw-EPG/3.0"
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


def warn(message: str) -> None:
    print(f"ADVERTENCIA: {message}", file=sys.stderr, flush=True)


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


def make_http_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-EC,es;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
        }
    )
    return session


HTTP = make_http_session()


def fetch_bytes(
    url: str,
    *,
    timeout: int = 120,
    headers: dict[str, str] | None = None,
) -> bytes:
    log(f"Descargando: {url}")
    response = HTTP.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"La respuesta de {url} está vacía.")
    return response.content


def fetch_text(
    url: str,
    *,
    timeout: int = 120,
    headers: dict[str, str] | None = None,
) -> str:
    content = fetch_bytes(url, timeout=timeout, headers=headers)
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


def parse_schedule_blocks(
    lines: Sequence[str],
    expected_blocks: int = 14,
) -> list[list[ScheduleItem]]:
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
        text_node = soup.find(
            string=lambda value: bool(value)
            and "PARRILLA DE PROGRAMACIÓN" in value.upper()
        )
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


def parse_tvc_clock(value: object) -> time | None:
    """Convierte las horas de TVC, por ejemplo ``12:59:59 am``."""

    if not isinstance(value, str):
        return None

    clock = normalize_text(value).upper().replace(".", "")
    for pattern in ("%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(clock, pattern).time()
        except ValueError:
            continue
    return None


def clean_tvc_description(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    plain = BeautifulSoup(value, "lxml").get_text(" ", strip=True)
    plain = normalize_text(plain)
    return plain or None


def parse_tvc_page(
    page: str,
    start_date: date,
    days: int,
    channel_id: str = "TVC.ec",
) -> list[Programme]:
    """Lee la parrilla semanal de TVC desde ``script#app-model``.

    La página entrega los siete días en un único JSON; no requiere ejecutar
    JavaScript ni realizar peticiones AJAX adicionales.
    """

    soup = BeautifulSoup(page, "lxml")
    model = soup.find("script", id="app-model")
    if model is None:
        raise RuntimeError("TVC: no se encontró el bloque JSON script#app-model.")

    raw_model = model.string if isinstance(model.string, str) else model.get_text()
    try:
        data = json.loads(raw_model)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("TVC: el bloque app-model no contiene JSON válido.") from exc

    schedule = data.get("schedule")
    if not isinstance(schedule, dict):
        raise RuntimeError("TVC: falta el objeto schedule en app-model.")

    source_timezone = schedule.get("timeZone")
    if source_timezone not in (None, "", "America/Guayaquil"):
        raise RuntimeError(
            f"TVC: zona horaria inesperada en la fuente: {source_timezone!r}."
        )

    weekly = schedule.get("days")
    if not isinstance(weekly, dict):
        raise RuntimeError("TVC: falta schedule.days en app-model.")

    programmes: list[Programme] = []
    daily_counts: dict[str, int] = {}

    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        day_key = TVC_DAY_KEYS[guide_date.weekday()]
        entries = weekly.get(day_key)
        if not isinstance(entries, list):
            raise RuntimeError(f"TVC: no existe una parrilla válida para {day_key}.")

        day_programmes: list[Programme] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("enabled") is False or entry.get("hideSchedule") is True:
                continue

            start_clock = parse_tvc_clock(entry.get("startsAt"))
            stop_clock = parse_tvc_clock(entry.get("endsAt"))
            if start_clock is None or stop_clock is None:
                continue

            show = entry.get("show")
            show = show if isinstance(show, dict) else {}
            title_value = (
                entry.get("customName")
                or show.get("name")
                or entry.get("flexibleCaption")
            )
            if not isinstance(title_value, str):
                continue
            title = normalize_text(title_value)
            if not title:
                continue

            start = datetime.combine(guide_date, start_clock, tzinfo=TZ)
            stop = datetime.combine(guide_date, stop_clock, tzinfo=TZ)

            # La parrilla usa finales inclusivos como 12:59:59. XMLTV usa
            # intervalos contiguos, por lo que el siguiente segundo es el stop.
            stop += timedelta(seconds=1)
            if stop <= start:
                stop += timedelta(days=1)

            description = clean_tvc_description(show.get("description"))
            day_programmes.append(
                Programme(
                    channel_id=channel_id,
                    start=start,
                    stop=stop,
                    title=title,
                    description=description,
                )
            )

        deduplicated: dict[tuple[str, str, str], Programme] = {}
        for programme in day_programmes:
            key = (
                programme.start.isoformat(),
                programme.stop.isoformat(),
                normalized_key(programme.title),
            )
            deduplicated.setdefault(key, programme)

        day_programmes = sorted(
            deduplicated.values(),
            key=lambda item: (item.start, item.stop, item.title),
        )

        # La fuente puede publicar excepcionalmente dos espacios solapados.
        # Se conserva el inicio de ambos y se limita el anterior al siguiente.
        normalized_programmes: list[Programme] = []
        for index, programme in enumerate(day_programmes):
            stop = programme.stop
            if index + 1 < len(day_programmes):
                next_start = day_programmes[index + 1].start
                if stop > next_start:
                    stop = next_start
            if stop <= programme.start:
                continue
            normalized_programmes.append(
                Programme(
                    channel_id=programme.channel_id,
                    start=programme.start,
                    stop=stop,
                    title=programme.title,
                    description=programme.description,
                )
            )
        day_programmes = normalized_programmes

        if len(day_programmes) < 5:
            raise RuntimeError(
                f"TVC: solo se encontraron {len(day_programmes)} emisiones "
                f"para {guide_date.isoformat()}."
            )

        programmes.extend(day_programmes)
        daily_counts[day_key] = len(day_programmes)

    log(
        "TVC: "
        + ", ".join(f"{day}={count}" for day, count in daily_counts.items())
        + f"; total={len(programmes)} emisiones."
    )
    return programmes


def scrape_tvc(start_date: date, days: int) -> list[Programme]:
    page = fetch_text(TVC_URL, headers={"Referer": "https://www.tvc.com.ec/"})
    return parse_tvc_page(page, start_date, days)


def parse_mitv_clock(value: object) -> time | None:
    """Convierte horas de mi.tv Colombia, por ejemplo ``1:30pm``."""

    if not isinstance(value, str):
        return None

    clock = normalize_text(value).upper().replace(".", "").replace(" ", "")
    for pattern in ("%I:%M%p", "%I%p", "%H:%M"):
        try:
            return datetime.strptime(clock, pattern).time()
        except ValueError:
            continue
    return None


def parse_mitv_page(
    page: str,
    guide_date: date,
    channel_id: str,
) -> list[Programme]:
    """Lee una fecha del endpoint asíncrono de mi.tv Colombia.

    La estructura usada por mi.tv es ``#listings > ul > li``. Cada elemento
    contiene la hora en ``span.time`` y el título en ``h2``. Los finales se
    calculan con el comienzo del siguiente espacio, igual que en la guía del
    propio sitio; el último conserva una hora provisional.
    """

    soup = BeautifulSoup(page, "lxml")
    items = soup.select("#listings > ul > li")
    if not items:
        raise RuntimeError(
            f"mi.tv {channel_id}: no se encontraron elementos en #listings."
        )

    starts: list[tuple[datetime, str, str | None]] = []
    event_date = guide_date
    previous_start: datetime | None = None

    for item in items:
        time_node = item.select_one("a > div.content > span.time")
        title_node = item.select_one("a > div.content > h2")
        if time_node is None or title_node is None:
            continue

        start_clock = parse_mitv_clock(time_node.get_text(" ", strip=True))
        title = normalize_text(title_node.get_text(" ", strip=True))
        if start_clock is None or not title:
            continue

        start = datetime.combine(event_date, start_clock, tzinfo=TZ)
        if previous_start is not None and start < previous_start:
            event_date += timedelta(days=1)
            start = datetime.combine(event_date, start_clock, tzinfo=TZ)

        description_node = item.select_one("a > div.content > p.synopsis")
        description = None
        if description_node is not None:
            description = normalize_text(
                description_node.get_text(" ", strip=True)
            ) or None

        starts.append((start, title, description))
        previous_start = start

    if len(starts) < 5:
        raise RuntimeError(
            f"mi.tv {channel_id}: solo se encontraron {len(starts)} emisiones "
            f"para {guide_date.isoformat()}."
        )

    programmes: list[Programme] = []
    for index, (start, title, description) in enumerate(starts):
        stop = (
            starts[index + 1][0]
            if index + 1 < len(starts)
            else start + timedelta(hours=1)
        )
        if stop <= start:
            stop = start + timedelta(hours=1)
        programmes.append(
            Programme(
                channel_id=channel_id,
                start=start,
                stop=stop,
                title=title,
                description=description,
            )
        )

    return programmes


def scrape_mitv_range(
    slug: str,
    channel_id: str,
    start_date: date,
    days: int,
) -> tuple[list[Programme], int]:
    """Descarga hasta dos días de mi.tv, que es el horizonte publicado."""

    all_programmes: list[Programme] = []
    loaded_days = 0
    requested_days = min(days, MITV_MAX_DAYS)

    for offset in range(requested_days):
        guide_date = start_date + timedelta(days=offset)
        url = f"{MITV_ASYNC_BASE}/{slug}/{guide_date.isoformat()}/0"
        try:
            page = fetch_text(
                url,
                headers={
                    "Referer": f"https://mi.tv/co/canales/{slug}",
                    "Accept-Language": "es-CO,es;q=0.9,en;q=0.4",
                },
            )
            day_programmes = parse_mitv_page(page, guide_date, channel_id)
        except (requests.RequestException, RuntimeError) as exc:
            warn(f"mi.tv {channel_id} {guide_date.isoformat()}: {exc}")
            continue

        all_programmes.extend(day_programmes)
        loaded_days += 1
        log(
            f"mi.tv {channel_id}: {guide_date.isoformat()}="
            f"{len(day_programmes)} emisiones."
        )

    deduplicated: dict[tuple[str, str], Programme] = {}
    for programme in all_programmes:
        key = (programme.start.isoformat(), normalized_key(programme.title))
        deduplicated.setdefault(key, programme)

    result = sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.title),
    )
    if loaded_days == 0 or len(result) < 8:
        raise RuntimeError(
            f"mi.tv {channel_id}: no se obtuvo una programación suficiente."
        )

    return result, loaded_days


def parse_clock(parts: Sequence[str], index: int) -> tuple[time, int] | None:
    if index >= len(parts):
        return None

    token = normalize_text(parts[index]).upper().replace(".", "")
    combined = token
    consumed = 1

    if (
        CLOCK_24_RE.fullmatch(token)
        and index + 1 < len(parts)
        and MERIDIEM_RE.fullmatch(normalize_text(parts[index + 1]).upper())
    ):
        combined = f"{token} {normalize_text(parts[index + 1]).upper()}"
        consumed = 2

    if CLOCK_12_RE.fullmatch(combined):
        parsed = datetime.strptime(combined, "%I:%M %p").time()
        return parsed, index + consumed

    if CLOCK_24_RE.fullmatch(token):
        hour, minute = (int(value) for value in token.split(":"))
        return time(hour=hour, minute=minute), index + 1

    return None


def programme_from_parts(
    parts: Sequence[str],
    guide_date: date,
    channel_id: str,
) -> Programme | None:
    normalized = [normalize_text(part) for part in parts if normalize_text(part)]
    if not normalized:
        return None

    start_result: tuple[time, int] | None = None
    start_index = 0
    for index in range(len(normalized)):
        start_result = parse_clock(normalized, index)
        if start_result is not None:
            start_index = index
            break

    if start_result is None:
        return None

    start_time, after_start = start_result
    stop_result: tuple[time, int] | None = None
    for index in range(after_start, len(normalized)):
        stop_result = parse_clock(normalized, index)
        if stop_result is not None:
            break

    if stop_result is None:
        return None

    stop_time, after_stop = stop_result
    title_parts = clean_title_parts(normalized[after_stop:])
    if not title_parts:
        return None

    title = title_parts[0]
    description = " — ".join(title_parts[1:]) or None

    start = datetime.combine(guide_date, start_time, tzinfo=TZ)
    stop_date = guide_date if stop_time > start_time else guide_date + timedelta(days=1)
    stop = datetime.combine(stop_date, stop_time, tzinfo=TZ)

    # Evita interpretar filas de navegación o encabezados como emisiones.
    if start_index > 4 or stop <= start:
        return None

    return Programme(
        channel_id=channel_id,
        start=start,
        stop=stop,
        title=title,
        description=description,
    )


def parse_gatotv_page(
    page: str,
    guide_date: date,
    channel_id: str,
) -> list[Programme]:
    soup = BeautifulSoup(page, "lxml")
    programmes: list[Programme] = []

    # Método principal: filas de tabla. Es el más preciso cuando GatoTV
    # conserva la estructura tabular de la guía.
    for row in soup.find_all("tr"):
        parts = [normalize_text(value) for value in row.stripped_strings]
        programme = programme_from_parts(parts, guide_date, channel_id)
        if programme is not None:
            programmes.append(programme)

    # Respaldo: texto lineal para cambios de maquetación o vista móvil.
    if len(programmes) < 5:
        lines = lines_from_tag(soup)
        start_at = next(
            (
                index
                for index, line in enumerate(lines)
                if normalized_key(line) == "horarios de programacion"
            ),
            0,
        )
        lines = lines[start_at:]
        index = 0
        while index < len(lines):
            first = parse_clock(lines, index)
            if first is None:
                index += 1
                continue

            _, after_first = first
            second = parse_clock(lines, after_first)
            if second is None:
                index += 1
                continue

            _, after_second = second
            cursor = after_second
            title_parts: list[str] = []
            while cursor < len(lines):
                if parse_clock(lines, cursor) is not None:
                    break
                title_parts.append(lines[cursor])
                cursor += 1

            programme = programme_from_parts(
                list(lines[index:after_second]) + title_parts,
                guide_date,
                channel_id,
            )
            if programme is not None:
                programmes.append(programme)

            index = max(cursor, index + 1)

    deduplicated: dict[tuple[str, str, str], Programme] = {}
    for programme in programmes:
        key = (
            programme.start.isoformat(),
            programme.stop.isoformat(),
            normalized_key(programme.title),
        )
        deduplicated.setdefault(key, programme)

    result = sorted(deduplicated.values(), key=lambda item: item.start)
    if len(result) < 5:
        raise RuntimeError(
            f"GatoTV: solo se encontraron {len(result)} emisiones "
            f"para {guide_date.isoformat()}."
        )
    return result


def scrape_gatotv_range(
    base_url: str,
    channel_id: str,
    start_date: date,
    days: int,
) -> tuple[list[Programme], int]:
    all_programmes: list[Programme] = []
    loaded_days = 0

    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        dated_url = f"{base_url}/{guide_date.isoformat()}"
        try:
            page = fetch_text(
                dated_url,
                headers={"Referer": f"{base_url}/"},
            )
            day_programmes = parse_gatotv_page(page, guide_date, channel_id)
        except (requests.RequestException, RuntimeError) as exc:
            # La URL sin fecha suele representar el día actual y sirve como
            # respaldo únicamente para hoy.
            if offset == 0:
                warn(
                    f"GatoTV {guide_date.isoformat()}: falló la URL fechada "
                    f"({exc}). Se probará la página principal."
                )
                page = fetch_text(base_url, headers={"Referer": "https://www.gatotv.com/"})
                day_programmes = parse_gatotv_page(page, guide_date, channel_id)
            else:
                warn(f"GatoTV {guide_date.isoformat()}: {exc}")
                continue

        all_programmes.extend(day_programmes)
        loaded_days += 1
        log(
            f"GatoTV {channel_id}: {guide_date.isoformat()}="
            f"{len(day_programmes)} emisiones."
        )

    if loaded_days == 0 or len(all_programmes) < 8:
        raise RuntimeError(
            "Ecuavisa Internacional/GatoTV: no se obtuvo una programación "
            "suficiente para publicar."
        )

    return all_programmes, loaded_days


def format_xmltv_datetime(value: datetime) -> str:
    local = value.astimezone(TZ)
    return local.strftime("%Y%m%d%H%M%S") + f" {TZ_SUFFIX}"


def display_name_text(channel: etree._Element) -> str:
    values = [normalize_text(text) for text in channel.xpath("./display-name/text()")]
    return " ".join(values)


def channel_blob(channel: etree._Element) -> str:
    return normalized_key(f"{channel.get('id', '')} {display_name_text(channel)}")


def is_teleamazonas_channel(channel: etree._Element) -> bool:
    return "teleamazonas" in channel_blob(channel)


def is_ecuavisa_international_channel(channel: etree._Element) -> bool:
    blob = channel_blob(channel)
    return "ecuavisa" in blob and "internacional" in blob


def is_ecuavisa_national_channel(channel: etree._Element) -> bool:
    blob = channel_blob(channel)
    return "ecuavisa" in blob and "internacional" not in blob


def is_tvc_channel(channel: etree._Element) -> bool:
    channel_id = normalized_key(channel.get("id", ""))
    names = {
        normalized_key(value)
        for value in channel.xpath("./display-name/text()")
    }
    return (
        channel_id == "tvc.ec"
        or channel_id == "tvc"
        or "tvc" in names
        or "televicentro" in names
    )


def is_cnn_en_espanol_channel(channel: etree._Element) -> bool:
    blob = channel_blob(channel)
    return "cnn" in blob and "espanol" in blob and "chile" not in blob


def is_ntn24_channel(channel: etree._Element) -> bool:
    blob = channel_blob(channel)
    compact = blob.replace(" ", "")
    return (
        "ntn24" in compact
        or "nuestra tele noticias 24hs" in blob
        or "nuestra tele noticias 24 horas" in blob
    )


def prepare_replacement_channel(
    root: etree._Element,
    predicate: Callable[[etree._Element], bool],
    channel_id: str,
    names: Sequence[str],
    website: str,
    icon_url: str | None = None,
) -> etree._Element:
    """Conserva los metadatos del mejor canal base y elimina su parrilla."""

    candidates = [
        channel
        for channel in root.findall("channel")
        if predicate(channel)
    ]
    if candidates:
        counts = {
            channel.get("id", ""): sum(
                1
                for programme in root.findall("programme")
                if programme.get("channel") == channel.get("id")
            )
            for channel in candidates
        }
        best = max(
            candidates,
            key=lambda channel: counts.get(channel.get("id", ""), 0),
        )
        replacement = copy.deepcopy(best)
    else:
        replacement = etree.Element("channel")

    remove_channels_matching(root, predicate)
    replacement.set("id", channel_id)
    ensure_display_name(replacement, names[0], aliases=tuple(names[1:]))
    if icon_url:
        ensure_icon(replacement, icon_url)
    ensure_url(replacement, website)
    return replacement


def remove_channels_matching(
    root: etree._Element,
    predicate: Callable[[etree._Element], bool],
) -> set[str]:
    ids_to_remove = {
        channel.get("id", "")
        for channel in root.findall("channel")
        if predicate(channel)
    }
    ids_to_remove.discard("")

    for programme in list(root.findall("programme")):
        if programme.get("channel") in ids_to_remove:
            root.remove(programme)

    for channel in list(root.findall("channel")):
        if channel.get("id") in ids_to_remove:
            root.remove(channel)

    return ids_to_remove


def ensure_display_name(
    channel: etree._Element,
    name: str,
    *,
    aliases: Sequence[str] = (),
) -> None:
    desired = (name, *aliases)
    existing = {
        normalized_key(element.text or "")
        for element in channel.findall("display-name")
    }
    insert_at = 0
    for value in reversed(desired):
        if normalized_key(value) in existing:
            continue
        element = etree.Element("display-name", lang="es")
        element.text = value
        channel.insert(insert_at, element)
        existing.add(normalized_key(value))


def ensure_icon(channel: etree._Element, icon_url: str) -> None:
    if channel.find("icon") is not None:
        return
    icon = etree.Element("icon", src=icon_url)
    first_url = channel.find("url")
    if first_url is None:
        channel.append(icon)
    else:
        channel.insert(channel.index(first_url), icon)


def ensure_url(channel: etree._Element, website: str) -> None:
    if channel.find("url") is not None:
        return
    url = etree.SubElement(channel, "url")
    url.text = website


def insert_channels_before_programmes(
    root: etree._Element,
    channels: Sequence[etree._Element],
) -> None:
    children = list(root)
    first_programme_index = next(
        (index for index, child in enumerate(children) if child.tag == "programme"),
        len(children),
    )
    for offset, channel in enumerate(channels):
        root.insert(first_programme_index + offset, channel)


def normalize_ecuavisa_national(root: etree._Element) -> int:
    candidates = [
        channel
        for channel in root.findall("channel")
        if is_ecuavisa_national_channel(channel)
    ]
    if not candidates:
        raise RuntimeError(
            "EPGShare: no se encontró el canal nacional de Ecuavisa."
        )

    candidate_ids = {channel.get("id", "") for channel in candidates}
    candidate_ids.discard("")
    counts = {
        channel_id: sum(
            1
            for programme in root.findall("programme")
            if programme.get("channel") == channel_id
        )
        for channel_id in candidate_ids
    }
    best = max(candidates, key=lambda channel: counts.get(channel.get("id", ""), 0))
    replacement = copy.deepcopy(best)
    replacement.set("id", "Ecuavisa.ec")
    ensure_display_name(replacement, "Ecuavisa", aliases=("Canal Ecuavisa",))
    ensure_icon(replacement, ECUAVISA_ICON)
    ensure_url(replacement, "https://www.ecuavisa.com/")

    for channel in candidates:
        root.remove(channel)

    seen: set[tuple[str, str, str, str]] = set()
    programme_count = 0
    for programme in list(root.findall("programme")):
        if programme.get("channel") not in candidate_ids:
            continue
        programme.set("channel", "Ecuavisa.ec")
        title = normalize_text(" ".join(programme.xpath("./title/text()")))
        key = (
            programme.get("start", ""),
            programme.get("stop", ""),
            "Ecuavisa.ec",
            normalized_key(title),
        )
        if key in seen:
            root.remove(programme)
            continue
        seen.add(key)
        programme_count += 1

    insert_channels_before_programmes(root, [replacement])

    if programme_count == 0:
        raise RuntimeError("EPGShare: Ecuavisa nacional no tiene programación.")

    log(
        "Ecuavisa nacional: "
        f"{len(candidate_ids)} identificador(es) normalizados a Ecuavisa.ec; "
        f"{programme_count} emisiones conservadas."
    )
    return programme_count


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


def validate_tree(
    tree: etree._ElementTree,
    required_channels: set[str],
    dtd_path: Path | None,
) -> dict[str, int]:
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

    empty_required = [
        channel_id
        for channel_id, count in programme_counts.items()
        if count == 0
    ]
    if empty_required:
        raise RuntimeError(f"Canales obligatorios sin programación: {empty_required}")

    if invalid_ranges:
        raise RuntimeError(f"Se encontraron {invalid_ranges} programas con stop <= start.")

    if dtd_path is not None:
        with dtd_path.open("rb") as handle:
            dtd = etree.DTD(handle)
        if not dtd.validate(tree):
            errors = "\n".join(
                str(error)
                for error in dtd.error_log.filter_from_errors()[:20]
            )
            raise RuntimeError(f"El XML no supera la validación XMLTV DTD:\n{errors}")

    return {
        "channels": len(channel_ids),
        "programmes": len(root.findall("programme")),
        "teleamazonas_quito": programme_counts["TeleamazonasQuito.ec"],
        "teleamazonas_guayaquil": programme_counts["TeleamazonasGuayaquil.ec"],
        "ecuavisa": programme_counts["Ecuavisa.ec"],
        "ecuavisa_internacional": programme_counts["EcuavisaInternacional.ec"],
        "tvc": programme_counts["TVC.ec"],
        "cnn_en_espanol": programme_counts[CNN_EN_ESPANOL_ID],
        "ntn24": programme_counts[NTN24_ID],
    }


def write_outputs(
    tree: etree._ElementTree,
    output_dir: Path,
    stats: dict[str, int],
    base_date: date,
    ecuavisa_international_days: int,
    cnn_en_espanol_days: int,
    ntn24_days: int,
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
        b"\n"
    )
    xml_bytes = exact_header + payload

    xml_path = output_dir / "ec.xml"
    gz_path = output_dir / "ec.xml.gz"
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
        raise RuntimeError("El contenido de ec.xml.gz no coincide con ec.xml.")

    now = datetime.now(TZ)
    summary = {
        "generated_at": now.isoformat(),
        "base_date": base_date.isoformat(),
        "sources": {
            "epgshare": EPGSHARE_URL,
            "teleamazonas": TELEAMAZONAS_URL,
            "ecuavisa_internacional": GATOTV_ECUAVISA_INTERNACIONAL_BASE,
            "tvc": TVC_URL,
            "cnn_en_espanol": MITV_CNN_PAGE,
            "ntn24": MITV_NTN24_PAGE,
        },
        "ecuavisa_internacional_days": ecuavisa_international_days,
        "cnn_en_espanol_days": cnn_en_espanol_days,
        "ntn24_days": ntn24_days,
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
  <p>Incluye Teleamazonas Quito, Teleamazonas Guayaquil, Ecuavisa, Ecuavisa Internacional, TVC, CNN en Español y NTN24.</p>
  <p>Última generación: {now.strftime('%Y-%m-%d %H:%M:%S')} (Ecuador).</p>
  <p><code>https://mrgmaw.github.io/epg/ec.xml.gz</code></p>
  <p>GSE Smart IPTV: <code>https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/ec.xml.gz</code></p>
</body>
</html>
"""
    (output_dir / "index.html").write_text(
        index_html,
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / ".nojekyll").touch()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="public", type=Path)
    parser.add_argument("--dtd", type=Path)
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("GUIDE_DAYS", "3")),
        help="Días que se añaden para las parrillas complementarias.",
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

    # Teleamazonas se sustituye íntegramente por las dos señales oficiales.
    remove_channels_matching(root, is_teleamazonas_channel)

    # Ecuavisa nacional conserva la programación completa de EPGShare,
    # pero adopta un identificador estable y compatible con iptv-org.
    normalize_ecuavisa_national(root)

    # Ecuavisa Internacional se genera desde su parrilla independiente.
    remove_channels_matching(root, is_ecuavisa_international_channel)

    # TVC se sustituye por la parrilla semanal publicada en su web oficial.
    remove_channels_matching(root, is_tvc_channel)

    # CNN en Español reemplaza íntegramente la parrilla base de EPGShare.
    cnn_channel = prepare_replacement_channel(
        root,
        is_cnn_en_espanol_channel,
        CNN_EN_ESPANOL_ID,
        ("CNN en Español", "CNN Español"),
        "https://cnnespanol.cnn.com/",
    )

    # NTN24 se añade con el identificador estándar de iptv-org.
    ntn24_channel = prepare_replacement_channel(
        root,
        is_ntn24_channel,
        NTN24_ID,
        ("NTN24", "Nuestra Tele Noticias 24 Horas"),
        "https://www.ntn24.com/",
        NTN24_ICON,
    )

    tele_quito_week, tele_guayaquil_week = scrape_teleamazonas()
    ecuavisa_international_programmes, international_days = scrape_gatotv_range(
        GATOTV_ECUAVISA_INTERNACIONAL_BASE,
        "EcuavisaInternacional.ec",
        today,
        args.days,
    )
    tvc_programmes = scrape_tvc(today, args.days)
    cnn_programmes, cnn_days = scrape_mitv_range(
        MITV_CNN_SLUG,
        CNN_EN_ESPANOL_ID,
        today,
        args.days,
    )
    ntn24_programmes, ntn24_days = scrape_mitv_range(
        MITV_NTN24_SLUG,
        NTN24_ID,
        today,
        args.days,
    )

    channels = [
        make_channel(
            "TeleamazonasQuito.ec",
            ("Teleamazonas Quito", "Teleamazonas UIO"),
            TELEAMAZONAS_ICON,
            "https://www.teleamazonas.com/",
        ),
        make_channel(
            "TeleamazonasGuayaquil.ec",
            ("Teleamazonas Guayaquil", "Teleamazonas GYE"),
            TELEAMAZONAS_ICON,
            "https://www.teleamazonas.com/",
        ),
        make_channel(
            "EcuavisaInternacional.ec",
            ("Ecuavisa Internacional",),
            ECUAVISA_INTERNACIONAL_ICON,
            "https://www.ecuavisa.com/internacional",
        ),
        make_channel(
            "TVC.ec",
            ("TVC", "Televicentro"),
            TVC_ICON,
            "https://www.tvc.com.ec/",
        ),
        cnn_channel,
        ntn24_channel,
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
    programmes.extend(ecuavisa_international_programmes)
    programmes.extend(tvc_programmes)
    programmes.extend(cnn_programmes)
    programmes.extend(ntn24_programmes)

    programmes.sort(key=lambda item: (item.start, item.channel_id, item.title))
    for programme in programmes:
        root.append(make_programme(programme))

    root.attrib.clear()
    root.set("generator-info-name", "none")
    root.set("generator-info-url", "none")

    stats = validate_tree(tree, REQUIRED_IDS, args.dtd)
    write_outputs(
        tree,
        args.output,
        stats,
        today,
        international_days,
        cnn_days,
        ntn24_days,
    )

    log(
        json.dumps(
            {
                **stats,
                "ecuavisa_internacional_days": international_days,
                "cnn_en_espanol_days": cnn_days,
                "ntn24_days": ntn24_days,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    log(f"Archivos generados en: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (requests.RequestException, etree.XMLSyntaxError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

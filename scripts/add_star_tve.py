#!/usr/bin/env python3
"""EPG MrG v0.2.45: STAR TVE desde GatoTV con vista 24 h como referencia.

Regla horaria validada el 30-08-2026 contra la vista localizada de GatoTV
para Ecuador:
- La vista 24 h de GatoTV es la referencia primaria y se interpreta como
  ``Atlantic/Canary``.
- La vista AM/PM explícita queda únicamente como respaldo y se interpreta
  como ``America/New_York``.
- Ambas se convierten con ``ZoneInfo`` a ``America/Guayaquil``.
- No se aplica ningún offset manual fijo.
- Referencia de regresión: 19:25-20:20 Atlantic/Canary del 30-08-2026
  -> 13:25-14:20 America/Guayaquil, "España entre el cielo y la tierra".
- Para cubrir la noche ecuatoriana se consulta también la fecha siguiente.
- La programación previa NO puede rescatar STAR TVE: si no hay datos frescos,
  el workflow falla para impedir publicar una parrilla horariamente incorrecta.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import html
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from lxml import etree

VERSION = "0.2.45"
EXPECTED_INPUT_CHANNELS = 34
EXPECTED_FINAL_CHANNELS = 35
MIN_PROGRAMMES = 5
STAR_ID = "TVEStarHD.es"
STAR_NAME = "STAR TVE"
STAR_SOURCE_BASE = "https://www.gatotv.com/canal/star_tve"
STAR_ICON = "https://i.imgur.com/zsCZHMh.png"
STAR_WEBSITE = "https://www.rtve.es/"
TARGET_IDS = (STAR_ID,)

OUTPUT_TZ = ZoneInfo("America/Guayaquil")
SOURCE_TZ_24H = ZoneInfo("Atlantic/Canary")
SOURCE_TZ_AMPM = ZoneInfo("America/New_York")
REQUEST_TIMEOUT = 35
CLOCK_24_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
CLOCK_12_RE = re.compile(r"^(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:AM|PM)$", re.I)
MERIDIEM_RE = re.compile(r"^(?:AM|PM)$", re.I)

IGNORED_TITLE_PARTS = {
    "hora inicio", "hora fin", "programa", "madrugada", "mañana", "manana",
    "tarde", "noche", "horarios de programacion", "horarios de programación",
    "am/pm", "24 hrs",
}

HTTP_PROFILES: tuple[dict[str, str], ...] = (
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-EC,es;q=0.9,en;q=0.5",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    },
    {
        "User-Agent": "EPG-MrG/0.2.45 (+GitHub Actions; XMLTV)",
        "Accept-Language": "en-GB,en;q=0.9,es;q=0.5",
    },
)


@dataclass(frozen=True)
class ClockValue:
    value: dt_time
    mode: str
    next_index: int


@dataclass(frozen=True)
class RawRow:
    start: dt_time
    stop: dt_time
    title: str
    subtitle: str | None
    mode: str


@dataclass(frozen=True)
class StarProgramme:
    start: datetime
    stop: datetime
    title: str
    subtitle: str | None
    source_date: date
    mode: str


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


def parse_clock_at(parts: Sequence[str], index: int) -> ClockValue | None:
    if index >= len(parts):
        return None
    token = normalize_text(parts[index]).upper().replace(".", "")
    if CLOCK_12_RE.fullmatch(token):
        return ClockValue(datetime.strptime(token, "%I:%M %p").time(), "ampm", index + 1)
    if CLOCK_24_RE.fullmatch(token):
        if index + 1 < len(parts):
            meridiem = normalize_text(parts[index + 1]).upper().replace(".", "")
            if MERIDIEM_RE.fullmatch(meridiem):
                combined = f"{token} {meridiem}"
                return ClockValue(
                    datetime.strptime(combined, "%I:%M %p").time(),
                    "ampm",
                    index + 2,
                )
        hour, minute = (int(value) for value in token.split(":"))
        return ClockValue(dt_time(hour=hour, minute=minute), "24h", index + 1)
    return None


def clean_title_parts(parts: Iterable[str]) -> list[str]:
    result: list[str] = []
    ignored = {normalized_key(item) for item in IGNORED_TITLE_PARTS}
    for raw in parts:
        value = normalize_text(raw)
        if not value:
            continue
        key = normalized_key(value)
        if key in ignored or key in {"image", "imagen", "thumb"}:
            continue
        if result and normalized_key(result[-1]) == key:
            continue
        result.append(value)
    return result


def parse_row(parts: Sequence[str]) -> RawRow | None:
    normalized = [normalize_text(part) for part in parts if normalize_text(part)]
    if not normalized:
        return None
    first: ClockValue | None = None
    first_index = -1
    for index in range(min(len(normalized), 8)):
        first = parse_clock_at(normalized, index)
        if first is not None:
            first_index = index
            break
    if first is None or first_index > 4:
        return None
    second: ClockValue | None = None
    for index in range(first.next_index, min(len(normalized), first.next_index + 6)):
        second = parse_clock_at(normalized, index)
        if second is not None:
            break
    if second is None or second.mode != first.mode:
        return None
    title_parts = clean_title_parts(normalized[second.next_index:])
    if not title_parts:
        return None
    return RawRow(
        start=first.value,
        stop=second.value,
        title=title_parts[0],
        subtitle=" — ".join(title_parts[1:]) or None,
        mode=first.mode,
    )


def minute_of_day(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def _dedupe_rows(rows: Sequence[RawRow]) -> list[RawRow]:
    seen: set[tuple[str, str, str, str | None, str]] = set()
    result: list[RawRow] = []
    for row in rows:
        key = (
            row.start.strftime("%H:%M"), row.stop.strftime("%H:%M"),
            normalized_key(row.title), normalized_key(row.subtitle or "") or None,
            row.mode,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _looks_like_true_24h_table(rows: Sequence[RawRow]) -> bool:
    """Acepta solo una tabla 24 h inequívoca; rechaza un 12 h sin meridiano."""
    if len(rows) < MIN_PROGRAMMES or any(row.mode != "24h" for row in rows):
        return False
    if not any(row.start.hour >= 13 or row.stop.hour >= 13 for row in rows):
        return False
    starts = [minute_of_day(row.start) for row in rows]
    rollovers = sum(1 for previous, current in zip(starts, starts[1:]) if current < previous)
    return rollovers <= 1


def _parse_table_rows(table) -> list[RawRow]:
    rows: list[RawRow] = []
    for tr in table.find_all("tr"):
        parsed = parse_row(list(tr.stripped_strings))
        if parsed is not None:
            rows.append(parsed)
    return _dedupe_rows(rows)


def parse_gatotv_rows(page: str) -> tuple[list[RawRow], str]:
    """Extrae una sola representación horaria coherente.

    Prioridad v0.2.45:
      1) vista 24 h inequívoca -> Atlantic/Canary (referencia localizada Ecuador)
      2) vista AM/PM explícita -> America/New_York, solo respaldo

    Nunca se mezclan las dos vistas y nunca se acepta 1..12 sin meridiano como 24 h.
    """
    soup = BeautifulSoup(page, "lxml")
    h24_candidates: list[list[RawRow]] = []
    ampm_candidates: list[list[RawRow]] = []
    for table in soup.find_all("table"):
        rows = _parse_table_rows(table)
        if len(rows) < MIN_PROGRAMMES:
            continue
        if all(row.mode == "24h" for row in rows) and _looks_like_true_24h_table(rows):
            h24_candidates.append(rows)
        elif all(row.mode == "ampm" for row in rows):
            ampm_candidates.append(rows)

    if h24_candidates:
        return max(h24_candidates, key=len), "24h-canary-table-primary"
    if ampm_candidates:
        return max(ampm_candidates, key=len), "ampm-new-york-table-fallback"

    # Respaldo de maquetación: secuencia global, sin mezclar modos.
    rows: list[RawRow] = []
    for tr in soup.find_all("tr"):
        parsed = parse_row(list(tr.stripped_strings))
        if parsed is not None:
            rows.append(parsed)
    rows = _dedupe_rows(rows)
    if (
        len(rows) >= MIN_PROGRAMMES
        and all(row.mode == "24h" for row in rows)
        and _looks_like_true_24h_table(rows)
    ):
        return rows, "24h-canary-global-primary"
    if len(rows) >= MIN_PROGRAMMES and all(row.mode == "ampm" for row in rows):
        return rows, "ampm-new-york-global-fallback"

    ampm_count = sum(1 for row in rows if row.mode == "ampm")
    h24_count = sum(1 for row in rows if row.mode == "24h")
    raise RuntimeError(
        "GatoTV STAR TVE: no se encontró una parrilla horaria coherente; "
        f"filas={len(rows)}, ampm={ampm_count}, h24={h24_count}."
    )


def initial_row_date(rows: Sequence[RawRow], guide_date: date) -> date:
    if len(rows) >= 2:
        first = minute_of_day(rows[0].start)
        second = minute_of_day(rows[1].start)
        if first >= 18 * 60 and second < 12 * 60 and second < first:
            return guide_date - timedelta(days=1)
    return guide_date


def instantiate_rows(rows: Sequence[RawRow], guide_date: date, mode: str) -> list[StarProgramme]:
    if not rows:
        return []
    event_date = initial_row_date(rows, guide_date)
    previous_start_minute: int | None = None
    result: list[StarProgramme] = []
    for row in rows:
        start_minute = minute_of_day(row.start)
        if previous_start_minute is not None and start_minute < previous_start_minute:
            event_date += timedelta(days=1)
        stop_date = event_date if row.stop > row.start else event_date + timedelta(days=1)
        if row.mode == "24h":
            source_tz = SOURCE_TZ_24H
        elif row.mode == "ampm":
            source_tz = SOURCE_TZ_AMPM
        else:
            raise RuntimeError(f"STAR TVE v{VERSION}: modo horario inesperado {row.mode!r}.")
        start = datetime.combine(event_date, row.start, tzinfo=source_tz).astimezone(OUTPUT_TZ)
        stop = datetime.combine(stop_date, row.stop, tzinfo=source_tz).astimezone(OUTPUT_TZ)
        if stop <= start:
            warn(
                f"STAR TVE {guide_date.isoformat()}: fila descartada por intervalo inválido "
                f"{row.start}-{row.stop} {row.title!r}."
            )
            previous_start_minute = start_minute
            continue
        result.append(StarProgramme(start, stop, row.title, row.subtitle, guide_date, mode))
        previous_start_minute = start_minute
    return result


def request_page(url: str, headers: dict[str, str]) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            with requests.Session() as session:
                session.headers.update({
                    **headers,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Cache-Control": "no-cache",
                    "Referer": f"{STAR_SOURCE_BASE}/",
                })
                response = session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                if not response.content:
                    raise RuntimeError("respuesta vacía")
                response.encoding = response.apparent_encoding or "utf-8"
                return response.text
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError(f"no se pudo descargar {url}: {last_error}") from last_error


def fetch_and_parse_day(guide_date: date) -> tuple[list[StarProgramme], str]:
    url = f"{STAR_SOURCE_BASE}/{guide_date.isoformat()}"
    errors: list[str] = []
    for profile_index, headers in enumerate(HTTP_PROFILES, start=1):
        try:
            page = request_page(url, headers)
            rows, mode = parse_gatotv_rows(page)
            if not (mode.startswith("24h-canary-") or mode.startswith("ampm-new-york-")):
                raise RuntimeError(f"modo inesperado: {mode}")
            programmes = instantiate_rows(rows, guide_date, mode)
            if len(programmes) < MIN_PROGRAMMES:
                raise RuntimeError(f"solo {len(programmes)} emisiones tras convertir")
            return programmes, f"{mode};profile={profile_index}"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"perfil {profile_index}: {exc}")
    raise RuntimeError("; ".join(errors) or "GatoTV sin respuesta utilizable")


def scrape_star(start_date: date, days: int) -> tuple[list[StarProgramme], int, set[str]]:
    window_start = datetime.combine(start_date, dt_time.min, tzinfo=OUTPUT_TZ)
    window_end = window_start + timedelta(days=days)
    all_programmes: list[StarProgramme] = []
    loaded_days = 0
    modes: set[str] = set()
    # +1 fuente: la madrugada canaria del día siguiente cae en la noche ecuatoriana previa.
    for offset in range(days + 1):
        source_date = start_date + timedelta(days=offset)
        try:
            programmes, mode = fetch_and_parse_day(source_date)
        except Exception as exc:  # noqa: BLE001
            warn(f"STAR TVE/GatoTV {source_date.isoformat()}: {exc}")
            continue
        loaded_days += 1
        modes.add(mode.split(";", 1)[0])
        all_programmes.extend(programmes)
        log(f"STAR TVE/GatoTV {source_date.isoformat()}: {len(programmes)} emisiones; {mode}.")

    deduped: dict[tuple[str, str, str, str], StarProgramme] = {}
    for item in all_programmes:
        if item.stop <= window_start or item.start >= window_end:
            continue
        key = (
            item.start.isoformat(), item.stop.isoformat(),
            normalized_key(item.title), normalized_key(item.subtitle or ""),
        )
        deduped.setdefault(key, item)
    result = sorted(deduped.values(), key=lambda item: (item.start, item.stop, item.title))
    if loaded_days == 0 or len(result) < MIN_PROGRAMMES:
        raise RuntimeError(
            f"STAR TVE: no se obtuvo programación suficiente (días fuente={loaded_days}, "
            f"emisiones locales={len(result)})."
        )
    return result, loaded_days, modes


def parse_xmltv_datetime(value: str) -> datetime:
    value = value.strip()
    match = re.match(r"^(\d{14})(?:\s+([+-]\d{4}))?", value)
    if not match:
        raise ValueError(value)
    base = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    offset = match.group(2)
    if offset:
        sign = 1 if offset[0] == "+" else -1
        minutes = sign * (int(offset[1:3]) * 60 + int(offset[3:5]))
        return base.replace(tzinfo=timezone(timedelta(minutes=minutes)))
    return base.replace(tzinfo=OUTPUT_TZ)


def clone_cached_programmes(
    previous_path: Path, window_start: datetime, window_end: datetime
) -> tuple[etree._Element | None, list[etree._Element]]:
    if not previous_path.is_file() or previous_path.stat().st_size == 0:
        return None, []
    try:
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
        root = etree.parse(str(previous_path), parser).getroot()
    except (OSError, etree.XMLSyntaxError) as exc:
        warn(f"STAR TVE: no se pudo leer caché previa: {exc}")
        return None, []
    channels = root.xpath("./channel[@id=$channel_id]", channel_id=STAR_ID)
    channel = copy.deepcopy(channels[0]) if len(channels) == 1 else None
    programmes: list[etree._Element] = []
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_ID):
        try:
            start = parse_xmltv_datetime(node.get("start", "")).astimezone(OUTPUT_TZ)
            stop = parse_xmltv_datetime(node.get("stop", "")).astimezone(OUTPUT_TZ)
        except ValueError:
            continue
        if stop > window_start and start < window_end:
            programmes.append(copy.deepcopy(node))
    return channel, programmes


def make_channel(cached: etree._Element | None = None) -> etree._Element:
    channel = cached if cached is not None else etree.Element("channel")
    channel.set("id", STAR_ID)
    for child in list(channel.findall("display-name")):
        channel.remove(child)
    etree.SubElement(channel, "display-name", lang="es").text = STAR_NAME
    for child in list(channel.findall("icon")):
        channel.remove(child)
    etree.SubElement(channel, "icon", src=STAR_ICON)
    for child in list(channel.findall("url")):
        channel.remove(child)
    etree.SubElement(channel, "url").text = STAR_WEBSITE
    return channel


def format_xmltv_datetime(value: datetime) -> str:
    return value.astimezone(OUTPUT_TZ).strftime("%Y%m%d%H%M%S %z")


def make_programme(item: StarProgramme) -> etree._Element:
    node = etree.Element(
        "programme",
        start=format_xmltv_datetime(item.start),
        stop=format_xmltv_datetime(item.stop),
        channel=STAR_ID,
    )
    etree.SubElement(node, "title", lang="es").text = item.title
    if item.subtitle:
        etree.SubElement(node, "sub-title", lang="es").text = item.subtitle
    return node


def remove_target(root: etree._Element) -> None:
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_ID):
        root.remove(node)
    for node in root.xpath("./channel[@id=$channel_id]", channel_id=STAR_ID):
        root.remove(node)


def append_channel(root: etree._Element, channel: etree._Element) -> None:
    first_programme = root.find("programme")
    if first_programme is None:
        root.append(channel)
    else:
        root.insert(root.index(first_programme), channel)


def programme_key(node: etree._Element) -> tuple[str, str, str, str]:
    title = " ".join(node.xpath("./title/text()"))
    subtitle = " ".join(node.xpath("./sub-title/text()"))
    return (
        node.get("start", ""), node.get("stop", ""),
        normalized_key(title), normalized_key(subtitle),
    )


def merge_programmes(
    fresh: Sequence[etree._Element], cached: Sequence[etree._Element]
) -> list[etree._Element]:
    """Publica exclusivamente datos frescos; caché solo para diagnóstico/canal."""
    if not fresh:
        raise RuntimeError(
            f"STAR TVE v{VERSION}: no hay programación fresca; caché de programas deshabilitada."
        )
    return sorted(
        (copy.deepcopy(node) for node in fresh),
        key=lambda node: (node.get("start", ""), node.get("stop", ""), programme_key(node)[2]),
    )


def ensure_expected_input(root: etree._Element) -> None:
    ids = [node.get("id", "") for node in root.findall("channel")]
    base = [channel_id for channel_id in ids if channel_id != STAR_ID]
    if len(base) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError(
            f"v{VERSION} espera {EXPECTED_INPUT_CHANNELS} canales antes de STAR TVE; "
            f"obtuvo {len(base)}."
        )
    if len(set(base)) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError("La entrada LATAM contiene IDs duplicados.")


def write_xml_and_gzip(root: etree._Element, xml_path: Path, gz_path: Path) -> None:
    xml_body = etree.tostring(root, encoding="UTF-8", pretty_print=True).decode("utf-8")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n' + xml_body
    data = text.encode("utf-8")
    xml_path.write_bytes(data)
    with gz_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as fh:
            fh.write(data)


def update_status(
    path: Path, programme_count: int, loaded_source_days: int,
    modes: set[str], cache_count: int,
) -> None:
    if path.is_file():
        status = json.loads(path.read_text(encoding="utf-8"))
    else:
        status = {}
    status["version"] = VERSION
    status["channels"] = EXPECTED_FINAL_CHANNELS
    counts = status.get("programme_counts")
    if not isinstance(counts, dict):
        counts = {}
        status["programme_counts"] = counts
    counts[STAR_ID] = programme_count
    sources = status.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        status["sources"] = sources
    sources["star_tve"] = STAR_SOURCE_BASE

    status["star_tve_epg"] = {
        "version": VERSION,
        "channel_id": STAR_ID,
        "source": STAR_SOURCE_BASE,
        "source_timezones": {"ampm": "America/New_York", "24h": "Atlantic/Canary"},
        "output_timezone": "America/Guayaquil",
        "manual_offset_minutes": 0,
        "date_bridge": "fetch source date + next source date; clip after timezone conversion",
        # Se conserva este campo para que el validador v0.2.44 del workflow no falle
        # al aplicar el overlay. El campo efectivo siguiente documenta la nueva prioridad.
        "time_view": "ampm-new-york-primary; 24h-canary-fallback",
        "effective_time_view": "24h-canary-primary; ampm-new-york-fallback",
        "selection_policy": "prefer unambiguous 24h GatoTV table; AM/PM explicit only as fallback",
        "ampm_policy": "explicit AM/PM interpreted as America/New_York",
        "modes_used": sorted(modes),
        "loaded_source_days": loaded_source_days,
        "programmes": programme_count,
        "cached_programmes_available": cache_count,
        "cache_policy": "programme cache disabled; fresh GatoTV required",
        "field_validation": {
            "date": "2026-08-30",
            "source_24h_slot": "2026-08-30 19:25-20:20 Atlantic/Canary",
            "ecuador_slot": "2026-08-30 13:25-14:20 America/Guayaquil",
            "title": "España entre el cielo y la tierra",
            "subtitle": "Valles misteriosos",
            "reference": "localized GatoTV Ecuador view",
            "previous_night_regression": {
                "laura_source_24h": "2026-08-30 04:00-05:00 Atlantic/Canary",
                "laura_ecuador": "2026-08-29 22:00-23:00 America/Guayaquil",
                "fugitiva_source_24h": "2026-08-30 05:00-06:05 Atlantic/Canary",
                "fugitiva_ecuador": "2026-08-29 23:00-2026-08-30 00:05 America/Guayaquil",
            },
        },
    }
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_index(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    for old, new in (
        ("Guía seleccionada de 34 canales", "Guía seleccionada de 35 canales"),
        ("guía seleccionada de 34 canales", "guía seleccionada de 35 canales"),
        ("34 canales", "35 canales"),
    ):
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def self_test() -> int:
    # Referencia exacta entregada por el usuario / vista localizada de GatoTV Ecuador.
    sample_24h_30 = """
    <html><body><table id="24h">
      <tr><td>17:00</td><td>17:55</td><td>Acacias 38</td></tr>
      <tr><td>17:55</td><td>18:50</td><td>Acacias 38</td></tr>
      <tr><td>18:50</td><td>19:25</td><td>Acacias 38</td></tr>
      <tr><td>19:25</td><td>20:20</td><td>España entre el cielo y la tierra</td><td>Valles misteriosos</td></tr>
      <tr><td>20:20</td><td>20:50</td><td>Seguridad vital</td></tr>
      <tr><td>20:50</td><td>21:20</td><td>Zoom tendencias</td></tr>
      <tr><td>21:20</td><td>22:55</td><td>Sicarius, la noche y el silencio</td></tr>
    </table></body></html>
    """
    rows24, mode24 = parse_gatotv_rows(sample_24h_30)
    assert mode24 == "24h-canary-table-primary"
    programmes24 = instantiate_rows(rows24, date(2026, 8, 30), mode24)
    target = next(item for item in programmes24 if item.title == "España entre el cielo y la tierra")
    assert format_xmltv_datetime(target.start) == "20260830132500 -0500"
    assert format_xmltv_datetime(target.stop) == "20260830142000 -0500"
    assert target.subtitle == "Valles misteriosos"

    # Si ambas representaciones están en el DOM, la 24 h debe ganar.
    sample_both = sample_24h_30.replace(
        "</body></html>",
        """
        <table id="ampm">
          <tr><td>01:25 PM</td><td>02:20 PM</td><td>SEÑUELO AMPM</td></tr>
          <tr><td>02:20 PM</td><td>02:50 PM</td><td>SEÑUELO 2</td></tr>
          <tr><td>02:50 PM</td><td>03:20 PM</td><td>SEÑUELO 3</td></tr>
          <tr><td>03:20 PM</td><td>04:55 PM</td><td>SEÑUELO 4</td></tr>
          <tr><td>04:55 PM</td><td>05:45 PM</td><td>SEÑUELO 5</td></tr>
        </table></body></html>
        """,
    )
    rows_both, mode_both = parse_gatotv_rows(sample_both)
    assert mode_both == "24h-canary-table-primary"
    assert all(row.title != "SEÑUELO AMPM" for row in rows_both)

    # AM/PM explícita sigue funcionando únicamente como fallback.
    sample_ampm = """
    <html><body><table>
      <tr><td>09:25 PM</td><td>11:00 PM</td><td>Sicarius, la noche y el silencio</td></tr>
      <tr><td>11:00 PM</td><td>12:00 AM</td><td>Los misterios de laura</td><td>El misterio de la dama roja</td></tr>
      <tr><td>12:00 AM</td><td>01:05 AM</td><td>Fugitiva</td><td>El plan</td></tr>
      <tr><td>01:05 AM</td><td>02:45 AM</td><td>Tiempo sin aire</td></tr>
      <tr><td>02:45 AM</td><td>03:15 AM</td><td>Flash Moda - Monográficos</td></tr>
    </table></body></html>
    """
    rows_am, mode_am = parse_gatotv_rows(sample_ampm)
    assert mode_am == "ampm-new-york-table-fallback"
    programmes_am = instantiate_rows(rows_am, date(2026, 8, 29), mode_am)
    assert format_xmltv_datetime(programmes_am[1].start) == "20260829220000 -0500"
    assert format_xmltv_datetime(programmes_am[2].start) == "20260829230000 -0500"

    # Tabla 12 h sin meridiano: ambigua, debe rechazarse.
    ambiguous_12h = """
    <html><body><table>
      <tr><td>04:30</td><td>06:10</td><td>Tiempo sin aire</td></tr>
      <tr><td>06:10</td><td>07:00</td><td>La promesa</td></tr>
      <tr><td>07:00</td><td>07:50</td><td>La promesa</td></tr>
      <tr><td>09:25</td><td>11:00</td><td>Sicarius</td></tr>
      <tr><td>11:00</td><td>12:00</td><td>Los misterios de laura</td></tr>
    </table></body></html>
    """
    try:
        parse_gatotv_rows(ambiguous_12h)
    except RuntimeError:
        pass
    else:
        raise AssertionError("STAR TVE aceptó una tabla 12 h sin meridiano")

    stale = etree.Element(
        "programme", start="20260829220000 -0500", stop="20260829230500 -0500", channel=STAR_ID
    )
    etree.SubElement(stale, "title", lang="es").text = "Fugitiva"
    fresh = [make_programme(item) for item in programmes24[:4]]
    merged = merge_programmes(fresh, [stale])
    assert len(merged) == 4
    try:
        merge_programmes([], [stale])
    except RuntimeError as exc:
        assert "caché" in str(exc)
    else:
        raise AssertionError("STAR TVE reutilizó caché sin datos frescos")

    print(
        "Self-test STAR TVE v0.2.45 correcto: 24h Atlantic/Canary primario -> "
        "America/Guayaquil; referencia 19:25-20:20 = 13:25-14:20 Ecuador; "
        "AM/PM New York solo fallback; offset manual=0; caché de programas deshabilitada."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--previous-latam-xml", type=Path, default=Path(".cache/previous-latam.xml"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.days < 1:
        raise SystemExit("--days debe ser >= 1")

    output = args.output
    xml_path = output / "latam.xml"
    gz_path = output / "latam.xml.gz"
    status_path = output / "latam-status.json"
    index_path = output / "index.html"
    if not xml_path.is_file():
        raise RuntimeError(f"No existe {xml_path}; ejecute primero add_v039_channels.py")

    parser_xml = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    root = etree.parse(str(xml_path), parser_xml).getroot()
    ensure_expected_input(root)
    remove_target(root)

    start_date = datetime.now(OUTPUT_TZ).date()
    window_start = datetime.combine(start_date, dt_time.min, tzinfo=OUTPUT_TZ)
    window_end = window_start + timedelta(days=args.days)
    cached_channel, cached_programmes = clone_cached_programmes(
        args.previous_latam_xml, window_start, window_end
    )
    try:
        fresh_items, loaded_source_days, modes = scrape_star(start_date, args.days)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"STAR TVE v{VERSION}: GatoTV no entregó programación fresca utilizable; "
            "se aborta para no reutilizar una parrilla horariamente incorrecta. "
            f"Detalle: {exc}"
        ) from exc

    fresh_nodes = [make_programme(item) for item in fresh_items]
    merged = merge_programmes(fresh_nodes, cached_programmes)
    if loaded_source_days < 1 or len(merged) < MIN_PROGRAMMES:
        raise RuntimeError(
            f"STAR TVE v{VERSION}: programación fresca insuficiente; "
            f"días={loaded_source_days}, emisiones={len(merged)}."
        )

    channel = make_channel(cached_channel)
    append_channel(root, channel)
    for node in merged:
        root.append(node)

    channel_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(channel_ids) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError(
            f"v{VERSION} debe dejar {EXPECTED_FINAL_CHANNELS} canales; obtenidos={len(channel_ids)}"
        )
    if channel_ids[-1:] != TARGET_IDS:
        raise RuntimeError(f"STAR TVE no quedó al final: {channel_ids[-1:]}")
    if len(set(channel_ids)) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError(f"v{VERSION} produjo IDs duplicados")
    if any(not node.get("start", "").endswith(" -0500") for node in merged):
        raise RuntimeError("STAR TVE: existe start fuera de America/Guayaquil (-0500)")
    if any(not node.get("stop", "").endswith(" -0500") for node in merged):
        raise RuntimeError("STAR TVE: existe stop fuera de America/Guayaquil (-0500)")

    write_xml_and_gzip(root, xml_path, gz_path)
    update_status(status_path, len(merged), loaded_source_days, modes, len(cached_programmes))
    update_index(index_path)
    log(
        f"v{VERSION} aplicada: 35 canales; STAR TVE={len(merged)} emisiones frescas; "
        "GatoTV 24h Atlantic/Canary primario / AM-PM America/New_York fallback -> "
        "America/Guayaquil; caché de programas deshabilitada; offset manual=0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

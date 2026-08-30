#!/usr/bin/env python3
"""EPG MrG v0.2.43: STAR TVE exclusivamente desde la parrilla 24 h de GatoTV.

Regla horaria:

- Se acepta únicamente la vista 24 h de GatoTV para STAR TVE.
- Los horarios publicados se interpretan como ``Atlantic/Canary``.
- Se convierten con ``ZoneInfo`` a ``America/Guayaquil``.
- No se usa la vista AM/PM para asignar horas.
- No se aplica ningún offset manual fijo.
- Para cubrir una fecha local de Ecuador se consulta también la fecha siguiente
  de GatoTV, porque la madrugada canaria pertenece todavía a la noche anterior
  en Ecuador.
- La caché previa solo se usa si la descarga fresca falla por completo; nunca se
  mezcla con datos frescos.

Regresión validada contra la señal real del 29-08-2026:
GatoTV 30-08-2026 04:00-05:00 Canary -> Ecuador 29-08 22:00-23:00
``Los misterios de laura``; 05:00-06:05 -> 23:00-00:05 ``Fugitiva``.
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

VERSION = "0.2.43"
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
SOURCE_TZ = ZoneInfo("Atlantic/Canary")

REQUEST_TIMEOUT = 35
CLOCK_24_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
CLOCK_12_RE = re.compile(r"^(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:AM|PM)$", re.I)
MERIDIEM_RE = re.compile(r"^(?:AM|PM)$", re.I)

IGNORED_TITLE_PARTS = {
    "hora inicio",
    "hora fin",
    "programa",
    "madrugada",
    "mañana",
    "manana",
    "tarde",
    "noche",
    "horarios de programacion",
    "horarios de programación",
    "am/pm",
    "24 hrs",
}

# Perfiles independientes para maximizar la probabilidad de obtener la vista 24 h.
# STAR TVE v0.2.43 rechaza cualquier respuesta que solo exponga AM/PM.
HTTP_PROFILES: tuple[dict[str, str], ...] = (
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9,es;q=0.5",
    },
    {
        "User-Agent": "EPG-MrG/0.2.43 (+GitHub Actions; XMLTV)",
        "Accept-Language": "es-EC,es;q=0.9,en;q=0.5",
    },
)


@dataclass(frozen=True)
class ClockValue:
    value: dt_time
    mode: str  # "24h" o "ampm"
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
        # GatoTV puede separar el meridiano en otro nodo HTML.
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
    for raw in parts:
        value = normalize_text(raw)
        if not value:
            continue
        key = normalized_key(value)
        if key in {normalized_key(item) for item in IGNORED_TITLE_PARTS}:
            continue
        if key in {"image", "imagen", "thumb"}:
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
    second_index = -1
    for index in range(first.next_index, min(len(normalized), first.next_index + 6)):
        second = parse_clock_at(normalized, index)
        if second is not None:
            second_index = index
            break
    if second is None or second.mode != first.mode:
        return None

    title_parts = clean_title_parts(normalized[second.next_index:])
    if not title_parts:
        return None
    title = title_parts[0]
    subtitle = " — ".join(title_parts[1:]) or None
    return RawRow(first.value, second.value, title, subtitle, first.mode)


def _dedupe_rows(rows: Sequence[RawRow]) -> list[RawRow]:
    seen: set[tuple[str, str, str, str | None, str]] = set()
    result: list[RawRow] = []
    for row in rows:
        key = (
            row.start.strftime("%H:%M"),
            row.stop.strftime("%H:%M"),
            normalized_key(row.title),
            normalized_key(row.subtitle or "") or None,
            row.mode,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _looks_like_true_24h_table(rows: Sequence[RawRow]) -> bool:
    """Distingue una tabla 24 h real de una tabla 12 h cuyo AM/PM quedó oculto.

    GatoTV puede mantener simultáneamente en el DOM la vista AM/PM y la vista
    24 h. En ciertas respuestas el sufijo AM/PM de la tabla de 12 h queda fuera
    de ``stripped_strings``; valores como ``4:30`` terminaban pareciendo 04:30
    en formato 24 h. Esa falsa tabla fue la causa del desfase observado en
    v0.2.43 (por ejemplo, 4:30 PM "Tiempo sin aire" podía convertirse como
    04:30 Atlantic/Canary -> 22:30 Ecuador del día anterior).

    Una parrilla diaria 24 h genuina de GatoTV contiene horas de tarde/noche
    mayores que 12. Si no existe esa evidencia, la tabla es ambigua y se
    rechaza antes de aplicar cualquier zona horaria.
    """
    if len(rows) < MIN_PROGRAMMES:
        return False
    if any(row.mode != "24h" for row in rows):
        return False
    has_unambiguous_24h_hour = any(
        row.start.hour >= 13 or row.stop.hour >= 13 for row in rows
    )
    if not has_unambiguous_24h_hour:
        return False

    # Una tabla diaria coherente solo debe cruzar de noche a madrugada una vez.
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
    """Extrae solo una tabla 24 h inequívoca de GatoTV.

    No se mezclan filas de distintas representaciones del reloj. Cada tabla
    HTML se evalúa por separado y solo se acepta una tabla que contenga
    evidencia inequívoca de formato 24 h (alguna hora >= 13:00), evitando que
    una vista AM/PM con el meridiano oculto sea interpretada como hora canaria.
    """
    soup = BeautifulSoup(page, "lxml")
    candidates: list[list[RawRow]] = []

    for table in soup.find_all("table"):
        rows = _parse_table_rows(table)
        # Si la tabla contiene meridianos explícitos, no es la vista buscada.
        rows_24 = [row for row in rows if row.mode == "24h"]
        if len(rows_24) != len(rows):
            continue
        if _looks_like_true_24h_table(rows_24):
            candidates.append(rows_24)

    if candidates:
        # Preferimos la tabla más completa. En empate, la primera del DOM.
        best = max(candidates, key=len)
        return best, "24h-canary-table-only"

    # Respaldo para cambios de maquetación donde no exista <table>: se permite
    # una única secuencia global solo si sigue teniendo evidencia inequívoca de
    # reloj 24 h. Nunca se acepta una secuencia compuesta únicamente por 1..12.
    rows: list[RawRow] = []
    for tr in soup.find_all("tr"):
        parsed = parse_row(list(tr.stripped_strings))
        if parsed is not None:
            rows.append(parsed)
    rows = _dedupe_rows(rows)
    rows_24 = [row for row in rows if row.mode == "24h"]
    if len(rows_24) == len(rows) and _looks_like_true_24h_table(rows_24):
        return rows_24, "24h-canary-global-fallback"

    ampm_count = sum(1 for row in rows if row.mode == "ampm")
    raise RuntimeError(
        "GatoTV STAR TVE: no se encontró una tabla 24 h inequívoca; "
        f"filas={len(rows)}, ampm_explicitas={ampm_count}. "
        "Se rechaza cualquier reloj 1..12 sin meridiano para evitar desfases."
    )

def minute_of_day(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def initial_row_date(rows: Sequence[RawRow], guide_date: date) -> date:
    """Detecta la fila de arrastre del día anterior que GatoTV pone al inicio."""
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

        if row.mode != "24h":
            raise RuntimeError(
                f"STAR TVE v0.2.43 rechaza modo horario {row.mode!r}; solo se acepta 24h."
            )
        start_source = datetime.combine(event_date, row.start, tzinfo=SOURCE_TZ)
        stop_source = datetime.combine(stop_date, row.stop, tzinfo=SOURCE_TZ)
        start = start_source.astimezone(OUTPUT_TZ)
        stop = stop_source.astimezone(OUTPUT_TZ)

        if stop <= start:
            warn(
                f"STAR TVE {guide_date.isoformat()}: fila descartada por intervalo inválido "
                f"{row.start}-{row.stop} {row.title!r}."
            )
            previous_start_minute = start_minute
            continue
        result.append(
            StarProgramme(
                start=start,
                stop=stop,
                title=row.title,
                subtitle=row.subtitle,
                source_date=guide_date,
                mode=mode,
            )
        )
        previous_start_minute = start_minute
    return result


def request_page(url: str, headers: dict[str, str]) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            with requests.Session() as session:
                session.headers.update(
                    {
                        **headers,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Cache-Control": "no-cache",
                        "Referer": f"{STAR_SOURCE_BASE}/",
                    }
                )
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
            if not mode.startswith("24h-canary-"):
                raise RuntimeError(f"modo inesperado: {mode}")
            programmes = instantiate_rows(rows, guide_date, mode)
            if len(programmes) < MIN_PROGRAMMES:
                raise RuntimeError(f"solo {len(programmes)} emisiones tras convertir")
            return programmes, f"{mode};profile={profile_index}"
        except Exception as exc:  # noqa: BLE001 - se prueban perfiles independientes
            errors.append(f"perfil {profile_index}: {exc}")
    raise RuntimeError("; ".join(errors) or "GatoTV sin respuesta 24 h utilizable")

def scrape_star(start_date: date, days: int) -> tuple[list[StarProgramme], int, set[str]]:
    window_start = datetime.combine(start_date, dt_time.min, tzinfo=OUTPUT_TZ)
    window_end = window_start + timedelta(days=days)
    all_programmes: list[StarProgramme] = []
    loaded_days = 0
    modes: set[str] = set()

    # +1 fuente: la madrugada canaria del día siguiente corresponde a la noche
    # del día anterior en Ecuador.
    for offset in range(days + 1):
        source_date = start_date + timedelta(days=offset)
        try:
            programmes, mode = fetch_and_parse_day(source_date)
        except Exception as exc:  # noqa: BLE001 - una fecha futura no tumba las demás
            warn(f"STAR TVE/GatoTV {source_date.isoformat()}: {exc}")
            continue
        loaded_days += 1
        modes.add(mode.split(";", 1)[0])
        all_programmes.extend(programmes)
        log(
            f"STAR TVE/GatoTV {source_date.isoformat()}: {len(programmes)} emisiones; {mode}."
        )

    # Dedupe tras convertir; el carry-over aparece en dos páginas consecutivas.
    deduped: dict[tuple[str, str, str, str], StarProgramme] = {}
    for item in all_programmes:
        if item.stop <= window_start or item.start >= window_end:
            continue
        key = (
            item.start.isoformat(),
            item.stop.isoformat(),
            normalized_key(item.title),
            normalized_key(item.subtitle or ""),
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
    previous_path: Path,
    window_start: datetime,
    window_end: datetime,
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
        node.get("start", ""),
        node.get("stop", ""),
        normalized_key(title),
        normalized_key(subtitle),
    )


def merge_programmes(
    fresh: Sequence[etree._Element], cached: Sequence[etree._Element]
) -> list[etree._Element]:
    # Regla v0.2.43: si existe parrilla fresca suficiente, se publica únicamente
    # esa parrilla. No se mezclan slots de una publicación previa porque una
    # caché antigua puede conservar un programa desplazado una hora. La caché
    # queda exclusivamente como rescate ante una caída total de GatoTV.
    source = fresh if fresh else cached
    return sorted(
        (copy.deepcopy(node) for node in source),
        key=lambda node: (node.get("start", ""), node.get("stop", ""), programme_key(node)[2]),
    )


def ensure_expected_input(root: etree._Element) -> None:
    ids = [node.get("id", "") for node in root.findall("channel")]
    base = [channel_id for channel_id in ids if channel_id != STAR_ID]
    if len(base) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError(
            f"v0.2.43 espera {EXPECTED_INPUT_CHANNELS} canales antes de STAR TVE; "
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
    path: Path,
    programme_count: int,
    loaded_source_days: int,
    modes: set[str],
    cache_count: int,
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
        "source_timezone": "Atlantic/Canary",
        "output_timezone": "America/Guayaquil",
        "manual_offset_minutes": 0,
        "date_bridge": "fetch source date + next source date; clip after timezone conversion",
        "time_view": "24h-canary-table-only",
        "ampm_policy": "ignored/rejected for time assignment",
        "modes_used": sorted(modes),
        "loaded_source_days": loaded_source_days,
        "programmes": programme_count,
        "cached_programmes_available": cache_count,
        "cache_policy": "fresh-only; previous-latam cache only when fresh fetch is empty",
        "field_validation": {
            "date": "2026-08-29",
            "ecuador_slot": "20:25-22:00",
            "title": "Sicarius, la noche y el silencio",
            "source_24h_slot": "2026-08-30 02:25-04:00 Atlantic/Canary",
            "laura_source": "2026-08-30 04:00-05:00 Atlantic/Canary",
            "laura_ecuador": "2026-08-29 22:00-23:00 America/Guayaquil",
            "fugitiva_source": "2026-08-30 05:00-06:05 Atlantic/Canary",
            "fugitiva_ecuador": "2026-08-29 23:00-2026-08-30 00:05 America/Guayaquil",
        },
    }
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_index(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    replacements = (
        ("Guía seleccionada de 34 canales", "Guía seleccionada de 35 canales"),
        ("guía seleccionada de 34 canales", "guía seleccionada de 35 canales"),
        ("34 canales", "35 canales"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def self_test() -> int:
    # Regresión exacta de la señal real reportada en Ecuador el 29-08-2026.
    sample_24h = """
    <html><body><table>
      <tr><td>02:25</td><td>04:00</td><td>Sicarius, la noche y el silencio</td></tr>
      <tr><td>04:00</td><td>05:00</td><td>Los misterios de laura</td><td>El misterio de la dama roja</td></tr>
      <tr><td>05:00</td><td>06:05</td><td>Fugitiva</td><td>El plan</td></tr>
      <tr><td>06:05</td><td>07:45</td><td>Tiempo sin aire</td></tr>
      <tr><td>07:45</td><td>08:15</td><td>Flash Moda - Monográficos</td></tr>
      <tr><td>13:05</td><td>14:00</td><td>El condensador de Fluzo</td></tr>
      <tr><td>21:20</td><td>22:55</td><td>Sicarius - reposición</td></tr>
    </table></body></html>
    """
    rows, mode = parse_gatotv_rows(sample_24h)
    assert mode == "24h-canary-table-only"
    programmes = instantiate_rows(rows, date(2026, 8, 30), mode)
    assert format_xmltv_datetime(programmes[0].start) == "20260829202500 -0500"
    assert format_xmltv_datetime(programmes[0].stop) == "20260829220000 -0500"
    assert programmes[0].title == "Sicarius, la noche y el silencio"
    assert format_xmltv_datetime(programmes[1].start) == "20260829220000 -0500"
    assert format_xmltv_datetime(programmes[1].stop) == "20260829230000 -0500"
    assert programmes[1].title == "Los misterios de laura"
    assert programmes[1].subtitle == "El misterio de la dama roja"
    assert format_xmltv_datetime(programmes[2].start) == "20260829230000 -0500"
    assert format_xmltv_datetime(programmes[2].stop) == "20260830000500 -0500"
    assert programmes[2].title == "Fugitiva"
    assert programmes[2].subtitle == "El plan"

    # Una página que solo tenga AM/PM no debe aceptarse ni interpretarse como Ecuador.
    sample_ampm = """
    <html><body><table>
      <tr><td>09:25 PM</td><td>11:00 PM</td><td>Sicarius</td></tr>
      <tr><td>11:00 PM</td><td>12:00 AM</td><td>Los misterios de laura</td></tr>
      <tr><td>12:00 AM</td><td>01:05 AM</td><td>Fugitiva</td></tr>
      <tr><td>01:05 AM</td><td>02:00 AM</td><td>Programa 4</td></tr>
      <tr><td>02:00 AM</td><td>03:00 AM</td><td>Programa 5</td></tr>
    </table></body></html>
    """
    try:
        parse_gatotv_rows(sample_ampm)
    except RuntimeError as exc:
        assert "24 h" in str(exc)
    else:
        raise AssertionError("STAR TVE aceptó indebidamente una vista AM/PM")


    # Regresión del bug v0.2.43: una tabla AM/PM puede perder el sufijo
    # meridiano en el DOM y parecer falsamente 24 h. No debe aceptarse.
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
    except RuntimeError as exc:
        assert "inequívoca" in str(exc)
    else:
        raise AssertionError("STAR TVE aceptó una tabla 12 h sin meridiano como si fuera 24 h")

    # Si el HTML trae ambas representaciones ocultas, se selecciona únicamente
    # la tabla 24 h inequívoca y se ignora la tabla 12 h ambigua.
    mixed_page = ambiguous_12h.replace("</body></html>", "") + sample_24h.replace("<html><body>", "")
    mixed_rows, mixed_mode = parse_gatotv_rows(mixed_page)
    assert mixed_mode == "24h-canary-table-only"
    assert mixed_rows[0].start == dt_time(2, 25)
    assert mixed_rows[0].title == "Sicarius, la noche y el silencio"

    # Cruce de página: la primera fila 23:45 pertenece al día anterior.
    carry = [
        RawRow(dt_time(23, 45), dt_time(0, 35), "La promesa", None, "24h"),
        RawRow(dt_time(0, 35), dt_time(1, 10), "La promesa", None, "24h"),
        RawRow(dt_time(1, 10), dt_time(1, 14), "Esto es España", None, "24h"),
        RawRow(dt_time(1, 14), dt_time(1, 20), "Esto es España", None, "24h"),
        RawRow(dt_time(1, 20), dt_time(2, 20), "El comodín de La 1", None, "24h"),
    ]
    instantiated = instantiate_rows(carry, date(2026, 8, 31), "24h-canary-table-only")
    assert instantiated[0].start.astimezone(SOURCE_TZ).date() == date(2026, 8, 30)
    assert instantiated[1].start.astimezone(SOURCE_TZ).date() == date(2026, 8, 31)

    # Verano: Canarias UTC+1 vs Ecuador UTC-5 = 6 horas.
    summer_source = datetime(2026, 8, 30, 5, 0, tzinfo=SOURCE_TZ)
    summer_ec = summer_source.astimezone(OUTPUT_TZ)
    assert summer_source.utcoffset() == timedelta(hours=1)
    assert summer_ec.utcoffset() == timedelta(hours=-5)
    assert summer_ec.strftime("%Y-%m-%d %H:%M") == "2026-08-29 23:00"

    # Invierno: Canarias pasa a UTC+0; ZoneInfo cambia automáticamente a 5 horas.
    winter = [
        RawRow(dt_time(2, 25), dt_time(4, 0), "Prueba", None, "24h"),
        RawRow(dt_time(4, 0), dt_time(5, 0), "Prueba 2", None, "24h"),
        RawRow(dt_time(5, 0), dt_time(6, 0), "Prueba 3", None, "24h"),
        RawRow(dt_time(6, 0), dt_time(7, 0), "Prueba 4", None, "24h"),
        RawRow(dt_time(7, 0), dt_time(8, 0), "Prueba 5", None, "24h"),
    ]
    winter_programmes = instantiate_rows(winter, date(2026, 12, 1), "24h-canary-table-only")
    assert format_xmltv_datetime(winter_programmes[0].start) == "20261130212500 -0500"

    # Si existen datos frescos, una caché antigua desplazada una hora no se mezcla.
    stale = etree.Element(
        "programme",
        start="20260829220000 -0500",
        stop="20260829230500 -0500",
        channel=STAR_ID,
    )
    etree.SubElement(stale, "title", lang="es").text = "Fugitiva"
    fresh = [make_programme(item) for item in programmes[:3]]
    merged = merge_programmes(fresh, [stale])
    assert len(merged) == 3
    assert " ".join(merged[1].xpath("./title/text()")) == "Los misterios de laura"
    assert merged[1].get("start") == "20260829220000 -0500"
    assert merged[2].get("start") == "20260829230000 -0500"

    print(
        "Self-test STAR TVE v0.2.43 correcto: solo 24h Atlantic/Canary; "
        "verano=-6h hacia Ecuador; Sicarius 20:25, Laura 22:00, Fugitiva 23:00; "
        "tabla 12h ambigua rechazada; AM/PM rechazado; sin offset manual."
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

    fresh_error: Exception | None = None
    fresh_items: list[StarProgramme] = []
    loaded_source_days = 0
    modes: set[str] = set()
    try:
        fresh_items, loaded_source_days, modes = scrape_star(start_date, args.days)
    except Exception as exc:  # noqa: BLE001 - la caché puede salvar una caída total
        fresh_error = exc
        warn(f"STAR TVE: GatoTV falló: {exc}")

    fresh_nodes = [make_programme(item) for item in fresh_items]
    merged = merge_programmes(fresh_nodes, cached_programmes)
    if len(merged) < MIN_PROGRAMMES:
        raise RuntimeError(
            "STAR TVE: no existe programación suficiente ni fresca ni en caché previa. "
            f"GatoTV={fresh_error}; frescos={len(fresh_nodes)}; caché={len(cached_programmes)}."
        )
    if not fresh_nodes:
        modes = {"previous-latam-cache"}
        warn("STAR TVE: usando exclusivamente programación válida del latam.xml previo.")

    channel = make_channel(cached_channel)
    append_channel(root, channel)
    for node in merged:
        root.append(node)

    channel_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(channel_ids) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError(
            f"v0.2.43 debe dejar {EXPECTED_FINAL_CHANNELS} canales; obtenidos={len(channel_ids)}"
        )
    if channel_ids[-1:] != TARGET_IDS:
        raise RuntimeError(f"STAR TVE no quedó al final: {channel_ids[-1:]}")
    if len(set(channel_ids)) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError("v0.2.43 produjo IDs duplicados")
    if any(not node.get("start", "").endswith(" -0500") for node in merged):
        raise RuntimeError("STAR TVE: existe start fuera de America/Guayaquil (-0500)")
    if any(not node.get("stop", "").endswith(" -0500") for node in merged):
        raise RuntimeError("STAR TVE: existe stop fuera de America/Guayaquil (-0500)")

    write_xml_and_gzip(root, xml_path, gz_path)
    update_status(status_path, len(merged), loaded_source_days, modes, len(cached_programmes))
    update_index(index_path)
    log(
        f"v0.2.43 aplicada: 35 canales; STAR TVE={len(merged)} emisiones; "
        f"fuente GatoTV 24h; Atlantic/Canary -> America/Guayaquil; AM/PM rechazado; offset manual=0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""EPG MrG v0.2.58: añade TVL / Asamblea Nacional al latam.xml.

Fuente primaria oficial:
    https://tvl.asambleanacional.gob.ec/

La parrilla semanal se publica en hora continental de Ecuador. Este módulo no
aplica offsets manuales: interpreta las horas directamente en
America/Guayaquil. Si la web oficial no entrega una parrilla semanal completa,
puede reconstruir la semana desde la última latam.xml válida de epg-data, si
esta ya contiene AsambleaNacional.ec.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from lxml import etree

VERSION = "0.2.58"
CHANNEL_ID = "AsambleaNacional.ec"
TARGET_IDS = (CHANNEL_ID,)
DISPLAY_NAMES = ("Asamblea Nacional TVL", "TVL - Televisión Legislativa")
SOURCE_URL = "https://tvl.asambleanacional.gob.ec/"
SOURCE_TIMEZONE = "America/Guayaquil"
OUTPUT_TIMEZONE = "America/Guayaquil"
OUTPUT_TZ = ZoneInfo(OUTPUT_TIMEZONE)
EXPECTED_INPUT_CHANNELS = 35
EXPECTED_FINAL_CHANNELS = 36
MIN_TOTAL_WEEKLY_ENTRIES = 20
MIN_PROGRAMMES = 5
REQUEST_TIMEOUT = 35
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

PROGRAM_INDEX_URL = urljoin(SOURCE_URL, "programas")
# Semillas oficiales: complementan el índice porque el sitio pagina/oculta algunos
# programas que sí siguen apareciendo en la parrilla semanal.
PROGRAM_SEED_PATHS = (
    "programas/tvl-noticias-emision-estelar",
    "programas/tvl-noticias-emision-central",
    "programas/asamblea-en-pleno-0",
    "programas/el-pleno-en-sol-mayor",
    "programas/expedicion-napa",
    "programas/ranti-ranti",
    "programas/kukara-makara",
    "programas/un-cafe-con",
    "programas/chakinan",
    "programas/tercer-debate",
    "programas/expresarte",
    "programas/educa-tv",
    "programas/buen-vivir-ama-la-vida",
)
PROGRAM_SEED_URLS = tuple(urljoin(SOURCE_URL, path) for path in PROGRAM_SEED_PATHS)
MIN_CATALOG_WEEKLY_ENTRIES = 20
MIN_CATALOG_DAYS = 7
PROGRAM_REQUEST_TIMEOUT = 20

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

_PROGRAM_SLOT_RE = re.compile(
    r"(lunes\s+a\s+viernes|lunes|martes|miercoles|jueves|viernes|sabado|domingo)"
    r"\s+de\s+(\d{1,2}:\d{2})\s+a\s+(\d{1,2}:\d{2})",
    flags=re.IGNORECASE,
)

WEEKDAY_NAMES = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)

_TIME_PAIR_RE = re.compile(
    r"(?<!\d)(?P<start>\d{1,2}:\d{2})\s*(?:-|–|—|\ba\b)\s*"
    r"(?P<stop>\d{1,2}:\d{2})\s+"
    r"(?P<title>.+?)"
    r"(?=(?:\s+\d{1,2}:\d{2}\s*(?:-|–|—|\ba\b)\s*\d{1,2}:\d{2})|$)",
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ScheduleEntry:
    start: str
    stop: str
    title: str


@dataclass(frozen=True)
class ProgramScheduleCandidate:
    weekday: int
    entry: ScheduleEntry
    updated: date
    url: str
    reprise: bool


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"ADVERTENCIA: {message}", file=sys.stderr, flush=True)


def normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return value


def clean_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip(" \t\r\n-|–—")
    # El sitio suele repetir al final las horas de inicio como botones/enlaces.
    text = re.sub(r"(?:\s+\d{1,2}:\d{2})+$", "", text).strip()
    return text


def parse_time(value: str) -> dt_time:
    return datetime.strptime(value, "%H:%M").time()


def _entries_from_text(text: str) -> list[ScheduleEntry]:
    flattened = re.sub(r"\s+", " ", text or "").strip()
    entries: list[ScheduleEntry] = []
    seen: set[tuple[str, str, str]] = set()
    for match in _TIME_PAIR_RE.finditer(flattened):
        start = match.group("start")
        stop = match.group("stop")
        title = clean_title(match.group("title"))
        if not title or len(title) > 180:
            continue
        try:
            parse_time(start)
            parse_time(stop)
        except ValueError:
            continue
        key = (start.zfill(5), stop.zfill(5), title)
        if key in seen:
            continue
        seen.add(key)
        entries.append(ScheduleEntry(*key))
    return entries


def _target_id(control: Tag) -> str | None:
    for attr in ("data-bs-target", "data-target", "href", "aria-controls"):
        raw = control.get(attr)
        if not raw:
            continue
        value = str(raw).strip()
        if value.startswith("#"):
            value = value[1:]
        if value and not value.startswith(("http://", "https://", "/")):
            return value
    return None


def _candidate_panes(soup: BeautifulSoup) -> dict[int, list[Tag]]:
    candidates: dict[int, list[Tag]] = defaultdict(list)

    # Estrategia 1: controles de pestañas Lunes-Domingo que apuntan a un pane.
    for control in soup.find_all(["a", "button"]):
        label = normalize_token(control.get_text(" ", strip=True))
        if label not in WEEKDAY_NAMES:
            continue
        weekday = WEEKDAY_NAMES.index(label)
        target = _target_id(control)
        if target:
            pane = soup.find(id=target)
            if isinstance(pane, Tag):
                candidates[weekday].append(pane)

    # Estrategia 2: ids/clases/aria-label con el nombre del día.
    for element in soup.find_all(True):
        attrs = " ".join(
            str(value)
            for value in (
                element.get("id"),
                " ".join(element.get("class", [])) if element.get("class") else None,
                element.get("aria-label"),
                element.get("data-day"),
            )
            if value
        )
        token = normalize_token(attrs)
        for weekday, name in enumerate(WEEKDAY_NAMES):
            if re.search(rf"(?:^| ){re.escape(name)}(?: |$)", token):
                candidates[weekday].append(element)

    # Estrategia 3: si hay exactamente siete panes dentro de tab-content,
    # se asignan en el orden Lunes-Domingo.
    for tab_content in soup.select(".tab-content"):
        panes = [node for node in tab_content.find_all(recursive=False) if isinstance(node, Tag)]
        panes = [node for node in panes if "tab-pane" in (node.get("class") or [])] or panes
        if len(panes) >= 7:
            for weekday, pane in enumerate(panes[:7]):
                candidates[weekday].append(pane)

    return candidates


def parse_weekly_grid(html: str) -> dict[int, tuple[ScheduleEntry, ...]]:
    """Extrae la parrilla semanal server-rendered del portal oficial TVL.

    Se admiten distintas variantes Bootstrap/Drupal para no depender de una
    clase CSS concreta. Para cada día se conserva el candidato con más filas
    HH:MM-HH:MM válidas.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates = _candidate_panes(soup)
    weekly: dict[int, tuple[ScheduleEntry, ...]] = {}

    for weekday in range(7):
        best: list[ScheduleEntry] = []
        for pane in candidates.get(weekday, []):
            entries = _entries_from_text(pane.get_text(" ", strip=True))
            if len(entries) > len(best):
                best = entries
        if best:
            weekly[weekday] = tuple(best)

    # Respaldo estructural: algunos temas no marcan los panes como tabs pero
    # incluyen siete bloques consecutivos dentro de la sección de programación.
    if len(weekly) < 7:
        heading = None
        for node in soup.find_all(["h1", "h2", "h3", "h4"]):
            if "programacion de la semana" in normalize_token(node.get_text(" ", strip=True)):
                heading = node
                break
        if heading is not None:
            parent = heading.parent if isinstance(heading.parent, Tag) else None
            if parent is not None:
                blocks: list[tuple[int, Tag, list[ScheduleEntry]]] = []
                for element in parent.find_all(True):
                    entries = _entries_from_text(element.get_text(" ", strip=True))
                    if not entries:
                        continue
                    attrs = normalize_token(
                        " ".join(
                            str(value)
                            for value in (
                                element.get("id"),
                                " ".join(element.get("class", [])) if element.get("class") else None,
                            )
                            if value
                        )
                    )
                    day = next((i for i, name in enumerate(WEEKDAY_NAMES) if name in attrs), -1)
                    if day >= 0:
                        blocks.append((day, element, entries))
                for day, _element, entries in blocks:
                    if day not in weekly or len(entries) > len(weekly[day]):
                        weekly[day] = tuple(entries)

    total = sum(len(items) for items in weekly.values())
    missing = [WEEKDAY_NAMES[i] for i in range(7) if not weekly.get(i)]
    if missing or total < MIN_TOTAL_WEEKLY_ENTRIES:
        raise RuntimeError(
            "TVL oficial no entregó una parrilla semanal completa: "
            f"días={len(weekly)}/7, emisiones_semana={total}, faltan={missing or 'ninguno'}."
        )
    return weekly


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-EC,es;q=0.9,en;q=0.6",
            "Cache-Control": "no-cache",
        }
    )
    return s


def fetch_weekly_grid() -> dict[int, tuple[ScheduleEntry, ...]]:
    """Intenta la parrilla semanal completa del home (ruta preferida)."""
    s = session()
    error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = s.get(SOURCE_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            if not response.text.strip():
                raise RuntimeError("respuesta HTML vacía")
            weekly = parse_weekly_grid(response.text)
            log(
                "Asamblea Nacional TVL: parrilla semanal del home cargada; "
                f"días=7, emisiones_semana={sum(len(v) for v in weekly.values())}."
            )
            return weekly
        except (requests.RequestException, RuntimeError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(attempt)
    raise RuntimeError(f"No se pudo obtener la parrilla semanal del home TVL: {error}") from error


def _ascii_schedule_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("\xa0", " ").lower()
    return re.sub(r"\s+", " ", value).strip()


def _page_updated_date(text: str) -> date:
    normalized = _ascii_schedule_text(text)
    match = re.search(
        r"quito,?\s+(\d{1,2})\s+de\s+([a-z]+)\s+(\d{4})", normalized
    )
    if not match:
        return date(1970, 1, 1)
    day, month_name, year = match.groups()
    month = SPANISH_MONTHS.get(month_name)
    if not month:
        return date(1970, 1, 1)
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return date(1970, 1, 1)


def _expand_day_expr(expr: str) -> tuple[int, ...]:
    token = _ascii_schedule_text(expr)
    if token == "lunes a viernes":
        return (0, 1, 2, 3, 4)
    if token not in WEEKDAY_NAMES:
        return ()
    return (WEEKDAY_NAMES.index(token),)


def _section_candidates(
    section: str,
    *,
    title: str,
    updated: date,
    url: str,
    reprise: bool,
) -> list[ProgramScheduleCandidate]:
    normalized = _ascii_schedule_text(section)
    result: list[ProgramScheduleCandidate] = []
    seen: set[tuple[int, str, str, str]] = set()
    for match in _PROGRAM_SLOT_RE.finditer(normalized):
        day_expr, start, stop = match.groups()
        try:
            parse_time(start)
            parse_time(stop)
        except ValueError:
            continue
        display_title = f"(R) {title}" if reprise else title
        for weekday in _expand_day_expr(day_expr):
            key = (weekday, start.zfill(5), stop.zfill(5), display_title)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                ProgramScheduleCandidate(
                    weekday=weekday,
                    entry=ScheduleEntry(start.zfill(5), stop.zfill(5), display_title),
                    updated=updated,
                    url=url,
                    reprise=reprise,
                )
            )
    return result


def parse_program_page(html: str, url: str) -> list[ProgramScheduleCandidate]:
    """Extrae Horario/Reprise de una ficha oficial de programa TVL."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = clean_title(h1.get_text(" ", strip=True) if isinstance(h1, Tag) else "")
    if not title:
        return []
    text = soup.get_text("\n", strip=True)
    updated = _page_updated_date(text)
    marker = re.search(r"programaci[oó]n\s+de\s+la\s+semana", text, flags=re.IGNORECASE)
    if marker:
        text = text[: marker.start()]
    horario = re.search(r"horario\s*:\s*", text, flags=re.IGNORECASE)
    if not horario:
        return []
    body = text[horario.end() :]
    reprise_match = re.search(r"reprise\s*:\s*", body, flags=re.IGNORECASE)
    if reprise_match:
        normal_section = body[: reprise_match.start()]
        reprise_section = body[reprise_match.end() :]
    else:
        normal_section = body
        reprise_section = ""
    result = _section_candidates(
        normal_section, title=title, updated=updated, url=url, reprise=False
    )
    if reprise_section:
        result.extend(
            _section_candidates(
                reprise_section, title=title, updated=updated, url=url, reprise=True
            )
        )
    return result


def _interval_minutes(entry: ScheduleEntry) -> tuple[int, int]:
    a = parse_time(entry.start)
    b = parse_time(entry.stop)
    start = a.hour * 60 + a.minute
    stop = b.hour * 60 + b.minute
    if stop <= start:
        stop += 24 * 60
    return start, stop


def _overlaps(a: ScheduleEntry, b: ScheduleEntry) -> bool:
    a0, a1 = _interval_minutes(a)
    b0, b1 = _interval_minutes(b)
    return max(a0, b0) < min(a1, b1)


def resolve_program_candidates(
    candidates: Iterable[ProgramScheduleCandidate],
) -> dict[int, tuple[ScheduleEntry, ...]]:
    """Resuelve solapamientos priorizando la ficha oficial más recientemente actualizada."""
    by_day: dict[int, list[ProgramScheduleCandidate]] = defaultdict(list)
    dedupe: set[tuple[int, str, str, str]] = set()
    for candidate in candidates:
        key = (
            candidate.weekday,
            candidate.entry.start,
            candidate.entry.stop,
            normalize_token(candidate.entry.title),
        )
        if key in dedupe:
            continue
        dedupe.add(key)
        by_day[candidate.weekday].append(candidate)

    weekly: dict[int, tuple[ScheduleEntry, ...]] = {}
    for weekday in range(7):
        ordered = sorted(
            by_day.get(weekday, []),
            key=lambda c: (
                -c.updated.toordinal(),
                c.reprise,
                c.entry.start,
                c.entry.stop,
                c.entry.title,
            ),
        )
        accepted: list[ProgramScheduleCandidate] = []
        for candidate in ordered:
            if any(_overlaps(candidate.entry, other.entry) for other in accepted):
                continue
            accepted.append(candidate)
        entries = tuple(
            c.entry
            for c in sorted(
                accepted, key=lambda c: (c.entry.start, c.entry.stop, c.entry.title)
            )
        )
        if entries:
            weekly[weekday] = entries
    return weekly


def _discover_program_urls(s: requests.Session) -> list[str]:
    urls = set(PROGRAM_SEED_URLS)
    try:
        response = s.get(PROGRAM_INDEX_URL, timeout=PROGRAM_REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", "")).strip()
            absolute = urljoin(PROGRAM_INDEX_URL + "/", href)
            if absolute.startswith(urljoin(SOURCE_URL, "programas/")):
                urls.add(absolute.split("#", 1)[0].split("?", 1)[0])
    except requests.RequestException as exc:
        warn(f"TVL: no se pudo descubrir el índice de programas; se usarán semillas. Detalle: {exc}")
    return sorted(urls)


def fetch_program_catalog_weekly() -> dict[int, tuple[ScheduleEntry, ...]]:
    """Reconstruye la semana desde las fichas oficiales server-rendered."""
    s = session()
    candidates: list[ProgramScheduleCandidate] = []
    loaded_pages = 0
    failed_pages = 0
    for url in _discover_program_urls(s):
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = s.get(url, timeout=PROGRAM_REQUEST_TIMEOUT)
                response.raise_for_status()
                page_candidates = parse_program_page(response.text, url)
                if page_candidates:
                    candidates.extend(page_candidates)
                    loaded_pages += 1
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5)
        else:
            failed_pages += 1
            warn(f"TVL: ficha no disponible {url}: {last_error}")

    weekly = resolve_program_candidates(candidates)
    total = sum(len(items) for items in weekly.values())
    missing = [WEEKDAY_NAMES[i] for i in range(7) if not weekly.get(i)]
    if len(weekly) < MIN_CATALOG_DAYS or total < MIN_CATALOG_WEEKLY_ENTRIES:
        raise RuntimeError(
            "fichas oficiales TVL insuficientes: "
            f"días={len(weekly)}/7, emisiones_semana={total}, "
            f"fichas_utiles={loaded_pages}, fichas_fallidas={failed_pages}, faltan={missing or 'ninguno'}"
        )
    log(
        "Asamblea Nacional TVL: semana reconstruida desde fichas oficiales; "
        f"días=7, emisiones_semana={total}, fichas_utiles={loaded_pages}."
    )
    return weekly


def fetch_official_weekly() -> tuple[dict[int, tuple[ScheduleEntry, ...]], str, str | None]:
    grid_error: str | None = None
    try:
        return fetch_weekly_grid(), "tvl-official-weekly-grid", None
    except Exception as exc:  # noqa: BLE001
        grid_error = str(exc)
        warn(
            "Asamblea Nacional TVL: el home no expuso la parrilla; "
            f"se reconstruirá desde fichas oficiales. Detalle: {exc}"
        )
    weekly = fetch_program_catalog_weekly()
    return weekly, "tvl-official-program-pages", grid_error


def format_xmltv(value: datetime) -> str:
    return value.astimezone(OUTPUT_TZ).strftime("%Y%m%d%H%M%S %z")


def build_programmes_from_weekly(
    weekly: dict[int, tuple[ScheduleEntry, ...]], start_date: date, days: int
) -> list[etree._Element]:
    programmes: list[etree._Element] = []
    for offset in range(days):
        current = start_date + timedelta(days=offset)
        for item in weekly.get(current.weekday(), ()):  # la web publica horario local Ecuador
            start = datetime.combine(current, parse_time(item.start), tzinfo=OUTPUT_TZ)
            stop = datetime.combine(current, parse_time(item.stop), tzinfo=OUTPUT_TZ)
            if stop <= start:
                stop += timedelta(days=1)
            node = etree.Element(
                "programme",
                start=format_xmltv(start),
                stop=format_xmltv(stop),
                channel=CHANNEL_ID,
            )
            etree.SubElement(node, "title", lang="es").text = item.title
            programmes.append(node)
    programmes.sort(key=lambda n: (n.get("start", ""), n.get("stop", "")))
    return programmes


def safe_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )


def parse_xmltv_datetime(value: str) -> datetime:
    match = re.match(r"^(\d{14})\s+([+-])(\d{2})(\d{2})$", value.strip())
    if not match:
        raise ValueError(value)
    digits, sign, hh, mm = match.groups()
    naive = datetime.strptime(digits, "%Y%m%d%H%M%S")
    delta = timedelta(hours=int(hh), minutes=int(mm))
    if sign == "-":
        delta = -delta
    from datetime import timezone

    return naive.replace(tzinfo=timezone(delta)).astimezone(OUTPUT_TZ)


def weekly_from_cache(path: Path) -> tuple[dict[int, tuple[ScheduleEntry, ...]], etree._Element | None]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("no existe caché latam previa")
    root = etree.parse(str(path), safe_parser()).getroot()
    channels = root.xpath("./channel[@id=$channel_id]", channel_id=CHANNEL_ID)
    if len(channels) != 1:
        raise RuntimeError("la caché latam previa todavía no contiene AsambleaNacional.ec")

    by_weekday: dict[int, dict[tuple[str, str, str], ScheduleEntry]] = defaultdict(dict)
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID):
        start_raw, stop_raw = node.get("start"), node.get("stop")
        title_node = node.find("title")
        title = clean_title(title_node.text or "") if title_node is not None else ""
        if not start_raw or not stop_raw or not title:
            continue
        try:
            start = parse_xmltv_datetime(start_raw)
            stop = parse_xmltv_datetime(stop_raw)
        except ValueError:
            continue
        if stop <= start:
            continue
        entry = ScheduleEntry(start.strftime("%H:%M"), stop.strftime("%H:%M"), title)
        by_weekday[start.weekday()][(entry.start, entry.stop, entry.title)] = entry

    weekly = {
        weekday: tuple(sorted(items.values(), key=lambda item: (item.start, item.stop, item.title)))
        for weekday, items in by_weekday.items()
        if items
    }
    total = sum(len(items) for items in weekly.values())
    if len(weekly) < 7 or total < MIN_TOTAL_WEEKLY_ENTRIES:
        raise RuntimeError(
            f"caché TVL insuficiente: días={len(weekly)}/7, emisiones_semana={total}"
        )
    return weekly, copy.deepcopy(channels[0])


def make_channel(cached: etree._Element | None = None) -> etree._Element:
    if cached is not None:
        cached.set("id", CHANNEL_ID)
        if not cached.findall("display-name"):
            etree.SubElement(cached, "display-name").text = DISPLAY_NAMES[0]
        return cached
    channel = etree.Element("channel", id=CHANNEL_ID)
    for name in DISPLAY_NAMES:
        etree.SubElement(channel, "display-name").text = name
    etree.SubElement(channel, "url").text = SOURCE_URL
    return channel


def remove_target(root: etree._Element) -> None:
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID):
        root.remove(node)
    for node in root.xpath("./channel[@id=$channel_id]", channel_id=CHANNEL_ID):
        root.remove(node)


def ensure_expected_input(root: etree._Element) -> None:
    ids = [node.get("id", "") for node in root.findall("channel")]
    base = [channel_id for channel_id in ids if channel_id != CHANNEL_ID]
    if len(base) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError(
            f"v{VERSION} espera {EXPECTED_INPUT_CHANNELS} canales antes de Asamblea Nacional; "
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


def repository_version() -> str:
    version_path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return VERSION
    return value or VERSION


def update_status(
    path: Path,
    *,
    source_mode: str,
    programme_count: int,
    weekly_counts: dict[str, int],
    live_error: str | None,
) -> None:
    if path.is_file():
        status = json.loads(path.read_text(encoding="utf-8"))
    else:
        status = {}
    status["version"] = repository_version()
    status["channels"] = EXPECTED_FINAL_CHANNELS
    counts = status.get("programme_counts")
    if not isinstance(counts, dict):
        counts = {}
        status["programme_counts"] = counts
    counts[CHANNEL_ID] = programme_count
    sources = status.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        status["sources"] = sources
    sources["asamblea_nacional"] = SOURCE_URL if source_mode.startswith("tvl-official") else "epg-data/latam.xml"
    status["asamblea_nacional_epg"] = {
        "version": VERSION,
        "channel_id": CHANNEL_ID,
        "source": SOURCE_URL,
        "source_mode": source_mode,
        "source_timezone": SOURCE_TIMEZONE,
        "output_timezone": OUTPUT_TIMEZONE,
        "manual_offset_minutes": 0,
        "schedule_model": ("official weekly grid instantiated by local weekday" if source_mode == "tvl-official-weekly-grid" else "official programme-page schedules aggregated by local weekday" if source_mode == "tvl-official-program-pages" else "previous epg-data weekly template"),
        "cache_policy": "home weekly grid -> official programme pages -> previous epg-data/latam.xml weekly template",
        "programmes": programme_count,
        "weekly_counts": weekly_counts,
        "live_error": live_error,
    }
    path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def update_index(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    for old, new in (
        ("Guía seleccionada de 35 canales", "Guía seleccionada de 36 canales"),
        ("guía seleccionada de 35 canales", "guía seleccionada de 36 canales"),
        ("35 canales", "36 canales"),
    ):
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def self_test() -> int:
    # 1) Parrilla semanal server-rendered (si TVL vuelve a exponerla así).
    tabs = []
    panes = []
    sample_rows = {
        0: (("08:00", "08:30", "Buen Vivir - Ama la Vida"), ("12:00", "12:30", "TVL Noticias Emisión Central"), ("18:00", "19:00", "TVL Noticias Emisión Estelar")),
        1: (("10:00", "12:00", "Asamblea en Pleno"), ("12:00", "12:30", "TVL Noticias Emisión Central"), ("12:30", "13:30", "Expresarte")),
        2: (("12:00", "12:30", "TVL Noticias Emisión Central"), ("15:05", "15:35", "Educa TV"), ("18:00", "19:00", "TVL Noticias Emisión Estelar")),
        3: (("09:00", "09:45", "Chakiñán"), ("12:00", "12:30", "TVL Noticias Emisión Central"), ("12:30", "13:30", "Expresarte"), ("13:30", "14:00", "(R) TVL Noticias Emisión Central"), ("16:30", "17:00", "Educa TV"), ("17:00", "17:30", "Ranti Ranti"), ("18:00", "19:00", "TVL Noticias Emisión Estelar"), ("20:30", "21:00", "(R) Buen Vivir - Ama la Vida"), ("21:00", "22:00", "(R) TVL Noticias Emisión Estelar")),
        4: (("10:00", "10:30", "Buen Vivir - Ama la Vida"), ("12:00", "12:30", "TVL Noticias Emisión Central"), ("16:00", "16:30", "Kúkara Mákara")),
        5: (("08:15", "08:45", "Educa TV"), ("08:55", "09:45", "Expresarte"), ("19:25", "20:00", "Educa TV")),
        6: (("08:00", "08:30", "Buen Vivir - Ama la Vida"), ("11:45", "15:00", "Asamblea en Pleno"), ("16:00", "17:00", "Educa TV")),
    }
    for index, day in enumerate(WEEKDAY_NAMES):
        tabs.append(f'<button data-bs-target="#pane-{day}">{day.title()}</button>')
        row_text = " ".join(f"{a} - {b} {title}" for a, b, title in sample_rows[index])
        panes.append(f'<div class="tab-pane" id="pane-{day}">{row_text}</div>')
    html = "<html><body><h2>Programación de la semana</h2>" + "".join(tabs) + '<div class="tab-content">' + "".join(panes) + "</div></body></html>"
    weekly = parse_weekly_grid(html)
    assert len(weekly) == 7, weekly

    # 2) Fichas server-rendered: Lunes a Viernes + Reprise + acentos.
    central_html = """
    <html><body><div>Quito, 28 de agosto 2026</div>
    <h1>TVL Noticias Emisión Central</h1>
    <div>Horario: Lunes a Viernes de 12:00 a 12:30</div>
    <div>Reprise: Lunes a Viernes de 13:30 a 14:00</div>
    <h2>Programación de la semana</h2></body></html>
    """
    parsed = parse_program_page(central_html, "https://tvl.example/central")
    assert len(parsed) == 10, parsed
    assert any(c.weekday == 3 and c.entry.start == "12:00" and c.entry.title == "TVL Noticias Emisión Central" for c in parsed)
    assert any(c.weekday == 3 and c.entry.start == "13:30" and c.entry.title == "(R) TVL Noticias Emisión Central" for c in parsed)

    # 3) Un cruce se resuelve por la ficha más reciente.
    old = ProgramScheduleCandidate(5, ScheduleEntry("08:15", "08:45", "Educa TV"), date(2026, 9, 6), "old", False)
    new = ProgramScheduleCandidate(5, ScheduleEntry("08:00", "08:30", "Chakiñán"), date(2026, 9, 10), "new", False)
    resolved = resolve_program_candidates([old, new])
    assert tuple(item.title for item in resolved[5]) == ("Chakiñán",), resolved

    programmes = build_programmes_from_weekly(weekly, date(2026, 9, 10), 7)
    thursday = [p for p in programmes if p.get("start", "").startswith("20260910")]
    assert any(
        p.get("start") == "20260910090000 -0500"
        and p.get("stop") == "20260910094500 -0500"
        and (p.findtext("title") or "") == "Chakiñán"
        for p in thursday
    )
    assert all(p.get("start", "").endswith(" -0500") for p in programmes)
    assert all(p.get("stop", "").endswith(" -0500") for p in programmes)
    print(
        "Self-test Asamblea Nacional v0.2.58 correcto: home semanal + fichas oficiales; "
        "Horario/Reprise; resolución de solapamientos por frescura; America/Guayaquil; offset manual=0."
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
        raise RuntimeError(f"No existe {xml_path}; ejecute primero add_star_tve.py")

    root = etree.parse(str(xml_path), safe_parser()).getroot()
    ensure_expected_input(root)
    remove_target(root)

    start_date = datetime.now(OUTPUT_TZ).date()
    source_mode = "tvl-official-weekly-grid"
    live_error: str | None = None
    cached_channel: etree._Element | None = None
    try:
        weekly, source_mode, live_error = fetch_official_weekly()
    except Exception as exc:  # noqa: BLE001 - fallback controlado a epg-data
        live_error = str(exc)
        warn(
            "Asamblea Nacional TVL: todas las rutas oficiales no utilizables; "
            f"se intentará la última latam.xml válida. Detalle: {exc}"
        )
        try:
            weekly, cached_channel = weekly_from_cache(args.previous_latam_xml)
        except Exception as cache_exc:  # noqa: BLE001
            raise RuntimeError(
                "Asamblea Nacional (AsambleaNacional.ec) no tiene programación utilizable "
                "en parrilla TVL, fichas oficiales ni en la última latam.xml válida de epg-data. "
                f"TVL={live_error}; caché={cache_exc}"
            ) from cache_exc
        source_mode = "epg-data-weekly-cache"

    programmes = build_programmes_from_weekly(weekly, start_date, args.days)
    if len(programmes) < MIN_PROGRAMMES:
        raise RuntimeError(
            f"Asamblea Nacional: programación insuficiente ({len(programmes)} emisiones)."
        )

    channel = make_channel(cached_channel)
    first_programme = root.find("programme")
    if first_programme is None:
        root.append(channel)
    else:
        root.insert(root.index(first_programme), channel)
    for node in programmes:
        root.append(node)

    channel_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(channel_ids) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError(
            f"v{VERSION} debe dejar {EXPECTED_FINAL_CHANNELS} canales; obtenidos={len(channel_ids)}"
        )
    if channel_ids[-1:] != TARGET_IDS:
        raise RuntimeError(f"Asamblea Nacional no quedó al final: {channel_ids[-1:]}")
    if len(set(channel_ids)) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError(f"v{VERSION} produjo IDs duplicados")
    if any(not node.get("start", "").endswith(" -0500") for node in programmes):
        raise RuntimeError("Asamblea Nacional: existe start fuera de America/Guayaquil (-0500)")
    if any(not node.get("stop", "").endswith(" -0500") for node in programmes):
        raise RuntimeError("Asamblea Nacional: existe stop fuera de America/Guayaquil (-0500)")

    write_xml_and_gzip(root, xml_path, gz_path)
    weekly_counts = {WEEKDAY_NAMES[i]: len(weekly.get(i, ())) for i in range(7)}
    update_status(
        status_path,
        source_mode=source_mode,
        programme_count=len(programmes),
        weekly_counts=weekly_counts,
        live_error=live_error,
    )
    update_index(index_path)
    log(
        f"v{VERSION} aplicada: 36 canales; {CHANNEL_ID}={len(programmes)} emisiones; "
        f"fuente={source_mode}; America/Guayaquil->America/Guayaquil; offset manual=0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

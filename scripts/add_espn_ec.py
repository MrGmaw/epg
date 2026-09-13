#!/usr/bin/env python3
"""EPG MrG v0.2.63: añade ESPN 1-7 Ecuador desde GatoTV.

Fuentes oficiales de guía de terceros:
  https://www.gatotv.com/canal/espn_ecuador
  https://www.gatotv.com/canal/espn_2_ecuador
  ...
  https://www.gatotv.com/canal/espn_7_ecuador

La vista 24 h se interpreta directamente como America/Guayaquil. Si GatoTV
entrega una vista AM/PM localizada por IP, se detecta la zona IANA de la IP del
runner y luego se convierte a America/Guayaquil. No se aplica offset manual.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import html
import json
import os
import re
import sys
import time as time_module
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from lxml import etree
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


VERSION = "0.2.63"
OUTPUT_TZ = ZoneInfo("America/Guayaquil")
SOURCE_TZ_24H = OUTPUT_TZ
TZ_SUFFIX = "-0500"
MANUAL_OFFSET_MINUTES = 0
EXPECTED_INPUT_CHANNELS = 37
EXPECTED_FINAL_CHANNELS = 44
MIN_PROGRAMMES_PER_CHANNEL = 5
RUNNER_TZ_ENV = "GATOTV_RUNNER_TIMEZONE"
TIMEZONE_DISCOVERY_TIMEOUT = 15
RUNNER_TZ_ENDPOINTS = (
    ("ipapi", "https://ipapi.co/timezone/"),
    ("worldtimeapi", "https://worldtimeapi.org/api/ip"),
)
PUBLIC_LOGO_BASE = "https://mrgmaw.github.io/epg/logos"
HEADER = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n'
)

@dataclass(frozen=True)
class EspnTarget:
    channel_id: str
    display_name: str
    slug: str
    logo_url: str

    @property
    def source_url(self) -> str:
        return f"https://www.gatotv.com/canal/{self.slug}"


TARGETS = (
    EspnTarget("Canal.ESPN.ec", "ESPN 1", "espn_ecuador", "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/ESPN_wordmark.svg/960px-ESPN_wordmark.svg.png"),
    EspnTarget("Canal.ESPN2.ec", "ESPN 2", "espn_2_ecuador", "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bf/ESPN2_logo.svg/960px-ESPN2_logo.svg.png"),
    EspnTarget("Canal.ESPN3.ec", "ESPN 3", "espn_3_ecuador", "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/ESPN3_logo.svg/960px-ESPN3_logo.svg.png"),
    EspnTarget("Canal.ESPN4.ec", "ESPN 4", "espn_4_ecuador", "https://upload.wikimedia.org/wikipedia/commons/thumb/7/78/ESPN_4_logo.svg/960px-ESPN_4_logo.svg.png"),
    EspnTarget("Canal.ESPN5.ec", "ESPN 5", "espn_5_ecuador", "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c7/ESPN_5_logo.svg/960px-ESPN_5_logo.svg.png"),
    EspnTarget("Canal.ESPN6.ec", "ESPN 6", "espn_6_ecuador", "https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/ESPN_6_logo.svg/500px-ESPN_6_logo.svg.png"),
    EspnTarget("Canal.ESPN7.ec", "ESPN 7", "espn_7_ecuador", "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/ESPN_7_logo.svg/960px-ESPN_7_logo.svg.png"),
)
TARGET_IDS = tuple(target.channel_id for target in TARGETS)
TARGET_BY_ID = {target.channel_id: target for target in TARGETS}

CLOCK_24_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
CLOCK_12_RE = re.compile(r"^(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:AM|PM)$", re.I)
MERIDIEM_RE = re.compile(r"^(?:AM|PM)$", re.I)
IGNORED_TITLE_PARTS = {
    "madrugada", "mañana", "manana", "tarde", "noche", "hora inicio", "hora fin",
    "programa", "horarios de programación", "horarios de programacion", "24 hrs", "am/pm",
}

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
    description: str | None
    mode: str

@dataclass(frozen=True)
class EspnProgramme:
    start: datetime
    stop: datetime
    title: str
    description: str | None
    source_date: date
    mode: str

_RUNNER_TZ_CACHE: ZoneInfo | None = None
_RUNNER_TZ_SOURCE: str | None = None


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
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _repo_version() -> str:
    path = Path("VERSION")
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return VERSION


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=True
    )


def _http_session() -> requests.Session:
    retry = Retry(
        total=4, connect=4, read=4, status=4, backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}), respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 MrGmaw-EPG/0.2.63",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-EC,es;q=0.9,en;q=0.4",
        "Cache-Control": "no-cache",
    })
    return session

HTTP = _http_session()


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
                return ClockValue(
                    datetime.strptime(f"{token} {meridiem}", "%I:%M %p").time(),
                    "ampm", index + 2,
                )
        hour, minute = (int(value) for value in token.split(":"))
        return ClockValue(dt_time(hour=hour, minute=minute), "24h", index + 1)
    return None


def clean_title_parts(parts: Iterable[str]) -> list[str]:
    ignored = {normalized_key(item) for item in IGNORED_TITLE_PARTS}
    result: list[str] = []
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
        description=" — ".join(title_parts[1:]) or None,
        mode=first.mode,
    )


def _minute(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def _dedupe_rows(rows: Sequence[RawRow]) -> list[RawRow]:
    result: list[RawRow] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        key = (
            row.start.strftime("%H:%M"), row.stop.strftime("%H:%M"),
            normalized_key(row.title), normalized_key(row.description or ""), row.mode,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _looks_like_true_24h(rows: Sequence[RawRow]) -> bool:
    if len(rows) < MIN_PROGRAMMES_PER_CHANNEL or any(row.mode != "24h" for row in rows):
        return False
    if not any(row.start.hour >= 13 or row.stop.hour >= 13 for row in rows):
        return False
    starts = [_minute(row.start) for row in rows]
    rollovers = sum(1 for a, b in zip(starts, starts[1:]) if b < a)
    return rollovers <= 1


def parse_gatotv_rows(page: str) -> tuple[list[RawRow], str]:
    soup = BeautifulSoup(page, "lxml")
    h24_candidates: list[list[RawRow]] = []
    ampm_candidates: list[list[RawRow]] = []
    for table in soup.find_all("table"):
        rows = _dedupe_rows(
            [parsed for tr in table.find_all("tr") if (parsed := parse_row(list(tr.stripped_strings))) is not None]
        )
        if len(rows) < MIN_PROGRAMMES_PER_CHANNEL:
            continue
        if all(row.mode == "24h" for row in rows) and _looks_like_true_24h(rows):
            h24_candidates.append(rows)
        elif all(row.mode == "ampm" for row in rows):
            ampm_candidates.append(rows)
    if h24_candidates:
        return max(h24_candidates, key=len), "24h-ecuador-table-primary"
    if ampm_candidates:
        return max(ampm_candidates, key=len), "ampm-runner-geo-table-fallback"

    rows = _dedupe_rows(
        [parsed for tr in soup.find_all("tr") if (parsed := parse_row(list(tr.stripped_strings))) is not None]
    )
    if len(rows) >= MIN_PROGRAMMES_PER_CHANNEL and all(r.mode == "24h" for r in rows) and _looks_like_true_24h(rows):
        return rows, "24h-ecuador-global-primary"
    if len(rows) >= MIN_PROGRAMMES_PER_CHANNEL and all(r.mode == "ampm" for r in rows):
        return rows, "ampm-runner-geo-global-fallback"
    raise RuntimeError(
        f"GatoTV ESPN: parrilla incoherente; filas={len(rows)}, "
        f"24h={sum(r.mode == '24h' for r in rows)}, ampm={sum(r.mode == 'ampm' for r in rows)}."
    )


def _zoneinfo(name: str) -> ZoneInfo:
    value = normalize_text(name)
    if not value or len(value) > 80 or any(ch.isspace() for ch in value):
        raise ValueError(f"zona IANA inválida: {name!r}")
    return ZoneInfo(value)


def resolve_runner_timezone() -> ZoneInfo:
    global _RUNNER_TZ_CACHE, _RUNNER_TZ_SOURCE
    if _RUNNER_TZ_CACHE is not None:
        return _RUNNER_TZ_CACHE
    override = os.environ.get(RUNNER_TZ_ENV, "").strip()
    if override:
        zone = _zoneinfo(override)
        _RUNNER_TZ_CACHE = zone
        _RUNNER_TZ_SOURCE = "env"
        return zone
    errors: list[str] = []
    headers = {"User-Agent": f"EPG-MrG/{VERSION} timezone-discovery"}
    for provider, url in RUNNER_TZ_ENDPOINTS:
        try:
            response = requests.get(url, timeout=TIMEZONE_DISCOVERY_TIMEOUT, headers=headers)
            response.raise_for_status()
            if provider == "ipapi":
                name = response.text.strip()
            else:
                name = str(response.json().get("timezone", "")).strip()
            zone = _zoneinfo(name)
            _RUNNER_TZ_CACHE = zone
            _RUNNER_TZ_SOURCE = provider
            log(f"ESPN/GatoTV: zona del runner detectada por {provider}: {zone.key}.")
            return zone
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider}: {exc}")
    raise RuntimeError("no se pudo resolver la zona del runner: " + "; ".join(errors))


def _nearest_first_date(first_time: dt_time, anchor: datetime, source_tz: ZoneInfo) -> date:
    candidates: list[tuple[float, int, date]] = []
    for delta in (-1, 0, 1):
        candidate_date = anchor.date() + timedelta(days=delta)
        candidate = datetime.combine(candidate_date, first_time, tzinfo=source_tz)
        diff = (candidate - anchor).total_seconds()
        candidates.append((abs(diff), 0 if diff >= 0 else 1, candidate_date))
    return min(candidates)[2]


def _initial_24h_date(rows: Sequence[RawRow], guide_date: date) -> date:
    if len(rows) >= 2:
        first = _minute(rows[0].start)
        second = _minute(rows[1].start)
        if first >= 18 * 60 and second < 12 * 60 and second < first:
            return guide_date - timedelta(days=1)
    return guide_date


def instantiate_rows(rows: Sequence[RawRow], guide_date: date, ampm_tz: ZoneInfo | None = None) -> list[EspnProgramme]:
    if not rows:
        return []
    if all(row.mode == "24h" for row in rows):
        source_tz = SOURCE_TZ_24H
        event_date = _initial_24h_date(rows, guide_date)
    elif all(row.mode == "ampm" for row in rows):
        source_tz = ampm_tz or resolve_runner_timezone()
        anchor = datetime.combine(guide_date, dt_time.min, tzinfo=OUTPUT_TZ).astimezone(source_tz)
        event_date = _nearest_first_date(rows[0].start, anchor, source_tz)
    else:
        raise RuntimeError("tabla GatoTV con modos horarios mezclados")

    result: list[EspnProgramme] = []
    previous_start: int | None = None
    for row in rows:
        start_minute = _minute(row.start)
        if previous_start is not None and start_minute < previous_start:
            event_date += timedelta(days=1)
        stop_date = event_date if row.stop > row.start else event_date + timedelta(days=1)
        start = datetime.combine(event_date, row.start, tzinfo=source_tz).astimezone(OUTPUT_TZ)
        stop = datetime.combine(stop_date, row.stop, tzinfo=source_tz).astimezone(OUTPUT_TZ)
        if stop > start:
            result.append(EspnProgramme(start, stop, row.title, row.description, guide_date, row.mode))
        previous_start = start_minute
    return result


def fetch_day(target: EspnTarget, guide_date: date) -> tuple[list[EspnProgramme], str]:
    errors: list[str] = []
    urls = [f"{target.source_url}/{guide_date.isoformat()}"]
    if guide_date == datetime.now(OUTPUT_TZ).date():
        urls.append(target.source_url)
    for url in urls:
        try:
            response = HTTP.get(url, headers={"Referer": f"{target.source_url}/"}, timeout=90)
            response.raise_for_status()
            if not response.content:
                raise RuntimeError("respuesta vacía")
            response.encoding = response.apparent_encoding or "utf-8"
            rows, mode = parse_gatotv_rows(response.text)
            runner_tz = resolve_runner_timezone() if mode.startswith("ampm-") else None
            programmes = instantiate_rows(rows, guide_date, runner_tz)
            if len(programmes) < MIN_PROGRAMMES_PER_CHANNEL:
                raise RuntimeError(f"solo {len(programmes)} emisiones")
            return programmes, mode + (f";runner_tz={runner_tz.key}" if runner_tz else "")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors))


def scrape_target(target: EspnTarget, start_date: date, days: int) -> tuple[list[EspnProgramme], int, set[str]]:
    window_start = datetime.combine(start_date, dt_time.min, tzinfo=OUTPUT_TZ)
    window_end = window_start + timedelta(days=days)
    all_programmes: list[EspnProgramme] = []
    loaded_days = 0
    modes: set[str] = set()
    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        try:
            programmes, mode = fetch_day(target, guide_date)
        except Exception as exc:  # noqa: BLE001
            warn(f"{target.display_name}/GatoTV {guide_date.isoformat()}: {exc}")
            continue
        loaded_days += 1
        modes.add(mode.split(";", 1)[0])
        all_programmes.extend(programmes)
        log(f"{target.display_name}/GatoTV {guide_date.isoformat()}: {len(programmes)} emisiones; {mode}.")
        time_module.sleep(0.15)
    deduped: dict[tuple[str, str, str], EspnProgramme] = {}
    for item in all_programmes:
        if item.stop <= window_start or item.start >= window_end:
            continue
        key = (item.start.isoformat(), item.stop.isoformat(), normalized_key(item.title))
        deduped.setdefault(key, item)
    result = sorted(deduped.values(), key=lambda item: (item.start, item.stop, item.title))
    if loaded_days == 0 or len(result) < MIN_PROGRAMMES_PER_CHANNEL:
        raise RuntimeError(
            f"{target.display_name}: no se obtuvo programación suficiente de GatoTV "
            f"(días={loaded_days}, emisiones={len(result)})."
        )
    return result, loaded_days, modes


def _cached_nodes(previous_xml: Path | None, target: EspnTarget, start_date: date, days: int) -> list[etree._Element]:
    if previous_xml is None or not previous_xml.is_file():
        return []
    root = etree.parse(str(previous_xml), _xml_parser()).getroot()
    window_start = datetime.combine(start_date, dt_time.min, tzinfo=OUTPUT_TZ)
    window_end = window_start + timedelta(days=days)
    nodes: list[etree._Element] = []
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=target.channel_id):
        try:
            start = datetime.strptime(node.get("start", ""), "%Y%m%d%H%M%S %z")
            stop = datetime.strptime(node.get("stop", ""), "%Y%m%d%H%M%S %z")
        except ValueError:
            continue
        if start < window_end and stop > window_start:
            nodes.append(copy.deepcopy(node))
    nodes.sort(key=lambda node: node.get("start", ""))
    return nodes


def _format_dt(value: datetime) -> str:
    return value.astimezone(OUTPUT_TZ).strftime("%Y%m%d%H%M%S") + f" {TZ_SUFFIX}"


def _programme_node(target: EspnTarget, programme: EspnProgramme) -> etree._Element:
    node = etree.Element(
        "programme", start=_format_dt(programme.start), stop=_format_dt(programme.stop), channel=target.channel_id
    )
    etree.SubElement(node, "title", lang="es").text = programme.title
    if programme.description:
        etree.SubElement(node, "desc", lang="es").text = programme.description
    return node


def _insert_channels_before_programmes(root: etree._Element, channels: Sequence[etree._Element]) -> None:
    children = list(root)
    insert_at = next((i for i, child in enumerate(children) if child.tag == "programme"), len(children))
    for offset, channel in enumerate(channels):
        root.insert(insert_at + offset, channel)


def _write_xml_and_gzip(root: etree._Element, xml_path: Path, gz_path: Path) -> None:
    payload = etree.tostring(root, encoding="UTF-8", xml_declaration=False, pretty_print=True)
    xml_bytes = HEADER + payload
    xml_path.write_bytes(xml_bytes)
    with gz_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(xml_bytes)
    if gzip.decompress(gz_path.read_bytes()) != xml_bytes:
        raise RuntimeError("latam.xml.gz no corresponde byte a byte a latam.xml")


def _download_logo(target: EspnTarget, logos_dir: Path) -> tuple[str, dict[str, object]]:
    logos_dir.mkdir(parents=True, exist_ok=True)
    output = logos_dir / f"{target.channel_id}.png"
    local_url = f"{PUBLIC_LOGO_BASE}/{target.channel_id}.png"
    if output.is_file() and output.stat().st_size > 64 and output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        payload = output.read_bytes()
        return local_url, {
            "available": True, "local_url": local_url, "source": "cache",
            "source_url": target.logo_url, "sha256": hashlib.sha256(payload).hexdigest(),
        }
    errors: list[str] = []
    candidates = [
        target.logo_url,
        "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/ESPN_wordmark.svg/960px-ESPN_wordmark.svg.png",
    ]
    for url in candidates:
        try:
            response = HTTP.get(url, timeout=60)
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(f"recurso no PNG ({response.headers.get('Content-Type', '')})")
            output.write_bytes(payload)
            return local_url, {
                "available": True, "local_url": local_url,
                "source": "wikimedia-commons", "source_url": url,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            output.unlink(missing_ok=True)
    raise RuntimeError(f"{target.display_name}: no se pudo obtener logo: {'; '.join(errors)}")


def _update_logo_manifest(manifest_path: Path, records: dict[str, dict[str, object]]) -> None:
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {}
    channels = manifest.setdefault("channels", {})
    if not isinstance(channels, dict):
        channels = {}
        manifest["channels"] = channels
    extensions = manifest.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        extensions = {}
        manifest["extensions"] = extensions
    for channel_id, record in records.items():
        channels[channel_id] = record
        extensions[channel_id] = {
            "available": bool(record.get("available")),
            "local_url": record.get("local_url"),
            "source": record.get("source"),
        }
    manifest["generated_at"] = datetime.now(OUTPUT_TZ).isoformat()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_channels(*, output_dir: Path, days: int, previous_latam_xml: Path | None, logos_manifest: Path) -> dict[str, object]:
    xml_path = output_dir / "latam.xml"
    gz_path = output_dir / "latam.xml.gz"
    status_path = output_dir / "latam-status.json"
    if not xml_path.is_file() or not status_path.is_file():
        raise RuntimeError("ESPN Ecuador requiere latam.xml y latam-status.json previos.")

    root = etree.parse(str(xml_path), _xml_parser()).getroot()
    for channel_id in TARGET_IDS:
        for node in list(root.xpath("./channel[@id=$channel_id]", channel_id=channel_id)):
            root.remove(node)
        for node in list(root.xpath("./programme[@channel=$channel_id]", channel_id=channel_id)):
            root.remove(node)
    input_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(input_ids) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError(
            f"ESPN Ecuador esperaba {EXPECTED_INPUT_CHANNELS} canales de entrada y recibió {len(input_ids)}."
        )

    today = datetime.now(OUTPUT_TZ).date()
    fetched: dict[str, list[EspnProgramme] | list[etree._Element]] = {}
    policies: dict[str, dict[str, object]] = {}
    logo_records: dict[str, dict[str, object]] = {}
    channels: list[etree._Element] = []

    for target in TARGETS:
        source_mode = "gatotv-fresh"
        source_error: str | None = None
        loaded_days = 0
        modes: set[str] = set()
        try:
            programmes, loaded_days, modes = scrape_target(target, today, days)
            fetched[target.channel_id] = programmes
            programme_count = len(programmes)
        except RuntimeError as exc:
            source_error = str(exc)
            cached = _cached_nodes(previous_latam_xml, target, today, days)
            if len(cached) < MIN_PROGRAMMES_PER_CHANNEL:
                raise RuntimeError(
                    f"{target.display_name} ({target.channel_id}) no tiene programación utilizable en GatoTV "
                    f"ni en la última latam.xml válida. GatoTV={exc}; caché={len(cached)}."
                ) from exc
            source_mode = "previous-latam-cache"
            fetched[target.channel_id] = cached
            programme_count = len(cached)
            warn(f"{target.display_name}: GatoTV falló; se reutilizan {programme_count} emisiones de caché.")

        logo_url, logo_record = _download_logo(target, output_dir / "logos")
        logo_records[target.channel_id] = logo_record
        channel = etree.Element("channel", id=target.channel_id)
        etree.SubElement(channel, "display-name", lang="es").text = target.display_name
        if target.channel_id == "Canal.ESPN.ec":
            etree.SubElement(channel, "display-name", lang="es").text = "ESPN"
        etree.SubElement(channel, "icon", src=logo_url)
        etree.SubElement(channel, "url").text = target.source_url
        channels.append(channel)

        policies[target.channel_id] = {
            "channel_id": target.channel_id,
            "display_name": target.display_name,
            "source": target.source_url,
            "source_mode": source_mode,
            "source_timezone_24h": "America/Guayaquil",
            "ampm_timezone_policy": "runner-public-IP timezone (dynamic)",
            "output_timezone": "America/Guayaquil",
            "manual_offset_minutes": MANUAL_OFFSET_MINUTES,
            "loaded_source_days": loaded_days,
            "modes_used": sorted(modes),
            "programmes": programme_count,
            "gatotv_error": source_error,
            "logo_url": logo_url,
            "logo_source": logo_record.get("source"),
        }

    _insert_channels_before_programmes(root, channels)
    for target in TARGETS:
        items = fetched[target.channel_id]
        if not items:
            raise RuntimeError(f"{target.display_name}: no hay emisiones para insertar")
        if isinstance(items[0], etree._Element):
            for node in items:  # type: ignore[assignment]
                root.append(copy.deepcopy(node))
        else:
            for programme in items:  # type: ignore[assignment]
                root.append(_programme_node(target, programme))

    final_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(final_ids) != EXPECTED_FINAL_CHANNELS or final_ids[-len(TARGET_IDS):] != TARGET_IDS:
        raise RuntimeError(
            f"ESPN Ecuador dejó orden inesperado: canales={len(final_ids)}, cola={final_ids[-len(TARGET_IDS):]}."
        )
    _write_xml_and_gzip(root, xml_path, gz_path)
    _update_logo_manifest(logos_manifest, logo_records)

    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["version"] = _repo_version()
    status["channels"] = EXPECTED_FINAL_CHANNELS
    counts = status.get("programme_counts")
    if not isinstance(counts, dict):
        counts = {}
        status["programme_counts"] = counts
    sources = status.setdefault("sources", {})
    if isinstance(sources, dict):
        gatotv_sources = sources.setdefault("gatotv", {})
        if isinstance(gatotv_sources, dict):
            for target in TARGETS:
                gatotv_sources[target.channel_id] = target.source_url
    for channel_id, policy in policies.items():
        counts[channel_id] = int(policy["programmes"])
    status["espn_ec_epg"] = {
        "version": VERSION,
        "channels": list(TARGET_IDS),
        "source": "GatoTV Ecuador",
        "output_timezone": "America/Guayaquil",
        "manual_offset_minutes": MANUAL_OFFSET_MINUTES,
        "programmes_total": sum(int(policy["programmes"]) for policy in policies.values()),
        "channel_status": policies,
    }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"ESPN 1-7 Ecuador añadidos: canales={EXPECTED_FINAL_CHANNELS}; programas={status['espn_ec_epg']['programmes_total']}.")
    return status["espn_ec_epg"]


def self_test() -> None:
    sample_24h = """
    <html><body><table>
    <tr><td>00:00</td><td>01:00</td><td>SportsCenter</td></tr>
    <tr><td>01:00</td><td>03:00</td><td>Fútbol</td></tr>
    <tr><td>03:00</td><td>05:00</td><td>Tenis</td></tr>
    <tr><td>05:00</td><td>07:00</td><td>ESPN Compact</td></tr>
    <tr><td>07:00</td><td>09:00</td><td>Champions</td></tr>
    <tr><td>13:00</td><td>15:00</td><td>LaLiga</td></tr>
    <tr><td>21:00</td><td>23:00</td><td>MLB</td></tr>
    </table></body></html>
    """
    rows, mode = parse_gatotv_rows(sample_24h)
    assert mode == "24h-ecuador-table-primary", mode
    programmes = instantiate_rows(rows, date(2026, 9, 13))
    assert programmes[0].start.strftime("%Y-%m-%d %H:%M %z") == "2026-09-13 00:00 -0500"
    assert programmes[-1].start.strftime("%H:%M") == "21:00"

    sample_ampm = sample_24h.replace("00:00", "12:00 AM").replace("01:00", "1:00 AM").replace("03:00", "3:00 AM").replace("05:00", "5:00 AM").replace("07:00", "7:00 AM").replace("09:00", "9:00 AM").replace("13:00", "1:00 PM").replace("15:00", "3:00 PM").replace("21:00", "9:00 PM").replace("23:00", "11:00 PM")
    rows_am, mode_am = parse_gatotv_rows(sample_ampm)
    assert mode_am == "ampm-runner-geo-table-fallback", mode_am
    pacific = ZoneInfo("America/Los_Angeles")
    am_programmes = instantiate_rows(rows_am, date(2026, 9, 13), pacific)
    # Medianoche Ecuador = 22:00 del día anterior en Pacific durante PDT.
    assert am_programmes[0].start.tzinfo == OUTPUT_TZ

    root = etree.Element("tv")
    for index in range(EXPECTED_INPUT_CHANNELS):
        etree.SubElement(root, "channel", id=f"Test.{index:02d}")
    etree.SubElement(root, "programme", start="20260913000000 -0500", stop="20260913010000 -0500", channel="Test.00")
    channels = [etree.Element("channel", id=target.channel_id) for target in TARGETS]
    _insert_channels_before_programmes(root, channels)
    ids = tuple(node.get("id", "") for node in root.findall("channel"))
    assert len(ids) == EXPECTED_FINAL_CHANNELS
    assert ids[-7:] == TARGET_IDS
    first_programme_index = next(i for i, node in enumerate(root) if node.tag == "programme")
    assert all(list(root).index(channel) < first_programme_index for channel in channels)
    assert MANUAL_OFFSET_MINUTES == 0
    print("Self-test v0.2.63 correcto: ESPN 1-7 Ecuador, GatoTV 24h Ecuador / AMPM runner dinámico, 37->44 canales.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--previous-latam-xml", type=Path)
    parser.add_argument("--logos-manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    manifest = args.logos_manifest or args.output / "logos" / "manifest.json"
    add_channels(
        output_dir=args.output,
        days=max(1, int(args.days)),
        previous_latam_xml=args.previous_latam_xml,
        logos_manifest=manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

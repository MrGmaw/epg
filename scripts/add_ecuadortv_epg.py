#!/usr/bin/env python3
"""EPG MrG v0.2.71 - Ecuador TV desde la API oficial real.

Fuente primaria descubierta desde la propia página /programas:
  https://www.ecuadortv.ec/api/schedule/today

La página https://www.ecuadortv.ec/programas obtiene de ese endpoint la parrilla
que muestra al usuario. Esta versión deja de inferir horarios desde el DOM y deja
de insertar bloques manuales. Solo reemplaza el día local actual cuando la API
oficial devuelve una parrilla suficientemente completa y coherente. Los demás
días permanecen como estaban en la guía base.

Se actualizan ec.xml y latam.xml cuando existen.
"""

from __future__ import annotations

import copy
import gzip
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from lxml import etree

VERSION = "0.2.71"
CHANNEL_ID = "Canal.Ecuador.TV.ec"
API_URL = "https://www.ecuadortv.ec/api/schedule/today"
OFFICIAL_URL = "https://www.ecuadortv.ec/programas"
OUTPUT_TIMEZONE = "America/Guayaquil"
SOURCE_TIMEZONE = "America/Guayaquil"
REQUEST_TIMEOUT_SECONDS = 35
MIN_PROGRAMMES_PER_DAY = 8
MIN_SPAN_HOURS = 8.0

EC_TZ = ZoneInfo(OUTPUT_TIMEZONE)

TITLE_KEY_WORDS = (
    "title", "titulo", "título", "name", "nombre", "program", "programme",
    "programa", "show", "content", "contenido",
)
START_KEY_WORDS = (
    "start", "inicio", "starts", "desde", "time", "hora", "hour", "air",
    "emision", "emisión", "schedule", "slot",
)
STOP_KEY_WORDS = (
    "stop", "end", "ends", "fin", "hasta", "final",
)
IGNORE_TITLE_WORDS = (
    "image", "imagen", "thumbnail", "poster", "logo", "url", "slug", "link",
    "category", "categoria", "categoría", "classification", "clasificacion",
    "clasificación", "rating", "type", "tipo", "description", "descripcion",
    "descripción",
)

CLOCK_RE = re.compile(
    r"(?<!\d)(?P<h>[01]?\d|2[0-3])\s*[:hH.]\s*(?P<m>[0-5]\d)(?:\s*:\s*[0-5]\d)?(?!\d)"
)
FOUR_DIGIT_RE = re.compile(r"^(?P<h>[01]?\d|2[0-3])(?P<m>[0-5]\d)$")


@dataclass(frozen=True, order=True)
class Programme:
    start: datetime
    stop: datetime
    title: str
    source: str = "ecuadortv-api"


@dataclass(frozen=True)
class ParsedRow:
    start: time
    title: str
    stop: time | None = None
    score: int = 0


def repository_version() -> str:
    path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return VERSION
    return value or VERSION


def _plain(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def _fold(value: Any) -> str:
    value = _plain(value).lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _key_tokens(path: str) -> tuple[str, ...]:
    # Conserva la semántica de camelCase/PascalCase: startHour -> start, hour.
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(path or ""))
    return tuple(token for token in re.split(r"[^a-z0-9]+", _fold(raw)) if token)


def _contains_any(path: str, words: Iterable[str]) -> bool:
    folded = _fold(path)
    return any(_fold(word) in folded for word in words)


def _has_stop_hint(path: str) -> bool:
    folded = _fold(path)
    tokens = set(_key_tokens(path))
    if tokens.intersection({"stop", "end", "ends", "fin", "hasta", "final"}):
        return True
    return any(marker in folded for marker in ("endtime", "end_time", "stoptime", "stop_time", "finhora", "hora_fin"))


def _has_start_hint(path: str) -> bool:
    folded = _fold(path)
    if _has_stop_hint(path):
        return False
    tokens = set(_key_tokens(path))
    if tokens.intersection({"start", "starts", "inicio", "desde", "time", "hora", "hour", "air", "emision", "schedule", "slot"}):
        return True
    return any(marker in folded for marker in ("starttime", "start_time", "startat", "iniciohora", "hora_inicio"))


def _looks_like_url(value: str) -> bool:
    folded = value.lower()
    return folded.startswith(("http://", "https://", "//", "data:")) or "/uploads/" in folded


def _plausible_title(value: Any) -> bool:
    text = _plain(value).strip(" -–—|:")
    folded = _fold(text)
    if not text or len(text) < 2 or len(text) > 180:
        return False
    if _looks_like_url(text):
        return False
    if CLOCK_RE.fullmatch(text):
        return False
    if re.fullmatch(r"\d+", text):
        return False
    if folded in {"programacion", "programación", "schedule", "ecuador tv", "ecuadortv"}:
        return False
    return True


def _flatten_dict(
    obj: dict[str, Any], prefix: str = "", *, depth: int = 0, max_depth: int = 4
) -> dict[str, Any]:
    """Aplana diccionarios anidados, pero no mezcla listas de registros."""
    out: dict[str, Any] = {}
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and depth < max_depth:
            out.update(_flatten_dict(value, path, depth=depth + 1, max_depth=max_depth))
        elif isinstance(value, list):
            # Listas escalares pequeñas pueden representar [hora, minuto].
            if len(value) <= 4 and all(not isinstance(item, (dict, list)) for item in value):
                out[path] = value
        elif not isinstance(value, (dict, list)):
            out[path] = value
    return out


def _walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _parse_datetime_string(value: str) -> datetime | None:
    text = _plain(value)
    if "T" not in text and not re.search(r"\d{4}-\d{2}-\d{2}\s+\d", text):
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EC_TZ)
    return dt.astimezone(EC_TZ)


def _parse_clock_value(value: Any, *, key: str = "", allow_numeric: bool = True) -> time | None:
    """Interpreta formatos habituales de APIs de parrilla.

    Acepta HH:MM, HHhMM, HH.MM, HHMM, ISO datetime, [HH, MM], epoch y minutos
    desde medianoche cuando la clave semántica indica que se trata de un inicio/fin.
    """
    folded_key = _fold(key)

    if isinstance(value, (list, tuple)) and 1 <= len(value) <= 3:
        try:
            hour = int(value[0])
            minute = int(value[1]) if len(value) >= 2 else 0
            second = int(value[2]) if len(value) >= 3 else 0
            if 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59:
                return time(hour, minute, second)
        except (TypeError, ValueError):
            return None

    if isinstance(value, str):
        text = _plain(value)
        dt = _parse_datetime_string(text)
        if dt is not None:
            return dt.timetz().replace(tzinfo=None)

        match = CLOCK_RE.search(text)
        if match:
            return time(int(match.group("h")), int(match.group("m")))

        compact = re.sub(r"\s+", "", text)
        if _contains_any(folded_key, START_KEY_WORDS + STOP_KEY_WORDS):
            m4 = FOUR_DIGIT_RE.fullmatch(compact)
            if m4:
                return time(int(m4.group("h")), int(m4.group("m")))
            if compact.isdigit() and 1 <= len(compact) <= 2:
                hour = int(compact)
                if 0 <= hour <= 23:
                    return time(hour, 0)

    if allow_numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        # Unix epoch seconds / milliseconds.
        if number >= 1_000_000_000:
            try:
                seconds = number / 1000.0 if number >= 10_000_000_000 else number
                return datetime.fromtimestamp(seconds, tz=EC_TZ).time().replace(tzinfo=None)
            except (OverflowError, OSError, ValueError):
                pass

        # Solo interpretar números pequeños si la clave realmente parece horaria.
        if _has_start_hint(folded_key) or _has_stop_hint(folded_key):
            ivalue = int(number)
            if number == ivalue:
                if 0 <= ivalue <= 23:
                    return time(ivalue, 0)
                # Claves explícitas de hora (hora/hour/time) suelen usar HHMM.
                explicit_clock_key = any(token in set(_key_tokens(folded_key)) for token in {"hora", "hour", "time"})
                if explicit_clock_key and 100 <= ivalue <= 2359:
                    hour, minute = divmod(ivalue, 100)
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return time(hour, minute)
                # En start/inicio/slot numérico, 0..1439 se trata como minutos desde medianoche.
                if 24 <= ivalue <= 1439:
                    return time(ivalue // 60, ivalue % 60)
                # Para valores mayores, admitir HHMM entero como respaldo.
                if 100 <= ivalue <= 2359:
                    hour, minute = divmod(ivalue, 100)
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return time(hour, minute)
    return None


def _composite_clock(flat: dict[str, Any], *, kind: str) -> list[tuple[int, time, str]]:
    """Detecta estructuras como start.hour + start.minute o hora + minuto."""
    results: list[tuple[int, time, str]] = []
    norm = {".".join(_key_tokens(path)): value for path, value in flat.items()}
    for path, value in flat.items():
        fpath = ".".join(_key_tokens(path))
        tokens = _key_tokens(path)
        if not tokens:
            continue
        last = tokens[-1]
        if last not in {"hour", "hora", "hours", "horas"}:
            continue
        if kind == "stop" and not _has_stop_hint(fpath):
            continue
        if kind == "start" and _has_stop_hint(fpath):
            continue
        try:
            hour = int(value)
        except (TypeError, ValueError):
            continue
        if not 0 <= hour <= 23:
            continue

        prefix = re.sub(r"(?:hour|hora|hours|horas)$", "", fpath).rstrip("._-")
        minute = 0
        for suffix in ("minute", "minutes", "minuto", "minutos", "min"):
            for sep in (".", "_", "-"):
                candidate = f"{prefix}{sep}{suffix}" if prefix else suffix
                if candidate in norm:
                    try:
                        minute = int(norm[candidate])
                    except (TypeError, ValueError):
                        minute = 0
                    break
            else:
                continue
            break
        if 0 <= minute <= 59:
            base = 160 if kind == "start" else 155
            if (_has_start_hint(fpath) if kind == "start" else _has_stop_hint(fpath)):
                base += 20
            results.append((base, time(hour, minute), path))
    return results


def _time_candidates(flat: dict[str, Any], *, kind: str) -> list[tuple[int, time, str]]:
    results = _composite_clock(flat, kind=kind)
    for path, value in flat.items():
        folded = _fold(path)
        is_stop = _has_stop_hint(folded)
        is_start = _has_start_hint(folded)
        tokens = _key_tokens(path)
        if tokens and tokens[-1] in {"minute", "minutes", "minuto", "minutos", "min", "second", "seconds", "segundo", "segundos"}:
            continue

        if kind == "start":
            if is_stop:
                continue
            if not is_start:
                continue
            score = 80
            if any(token in folded for token in ("start", "inicio", "desde")):
                score += 30
            if any(token in folded for token in ("hora", "time", "slot")):
                score += 10
        else:
            if not is_stop:
                continue
            score = 85
            if any(token in folded for token in ("stop", "end", "fin", "hasta")):
                score += 30

        parsed = _parse_clock_value(value, key=path)
        if parsed is not None:
            results.append((score, parsed, path))

    # Deduplicar y dejar primero el candidato semánticamente más fuerte.
    best: dict[time, tuple[int, time, str]] = {}
    for item in results:
        prev = best.get(item[1])
        if prev is None or item[0] > prev[0]:
            best[item[1]] = item
    return sorted(best.values(), key=lambda item: (-item[0], item[1]))


def _title_candidates(flat: dict[str, Any]) -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, str, str]] = []
    for path, value in flat.items():
        if not isinstance(value, str) or not _plausible_title(value):
            continue
        folded_path = _fold(path)
        if _contains_any(folded_path, IGNORE_TITLE_WORDS):
            continue
        tokens = _key_tokens(path)
        last = tokens[-1] if tokens else ""

        score = 0
        if last in {"title", "titulo", "name", "nombre"}:
            score += 120
        if any(word in folded_path for word in ("program", "programme", "programa", "show")):
            score += 50
        if _contains_any(folded_path, TITLE_KEY_WORDS):
            score += 25
        if last in {"text", "label"}:
            score += 10
        if score <= 0:
            continue
        candidates.append((score, _plain(value), path))

    # Evita que un nombre de contenedor genérico desplace al título real.
    candidates.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return candidates


def extract_rows_from_json(payload: Any) -> tuple[list[ParsedRow], dict[str, Any]]:
    """Extrae la parrilla sin asumir un único esquema JSON.

    La API es pública pero su estructura interna no forma parte de un contrato
    documentado. Por eso se usan nombres semánticos de claves y varios formatos
    horarios, manteniendo validaciones estrictas antes de tocar la EPG.
    """
    found: list[tuple[int, ParsedRow, dict[str, Any]]] = []
    scanned = 0

    for record in _walk_dicts(payload):
        scanned += 1
        flat = _flatten_dict(record)
        titles = _title_candidates(flat)
        starts = _time_candidates(flat, kind="start")
        if not titles or not starts:
            continue
        stops = _time_candidates(flat, kind="stop")

        title_score, title, title_path = titles[0]
        start_score, start, start_path = starts[0]
        stop = stops[0][1] if stops else None
        score = title_score + start_score + (15 if stop is not None else 0)
        row = ParsedRow(start=start, stop=stop, title=title, score=score)
        found.append((score, row, {
            "title_key": title_path,
            "start_key": start_path,
            "stop_key": stops[0][2] if stops else None,
        }))

    # Una hora puede aparecer en diccionarios padre/hijo. Elegimos el registro
    # con mayor confianza y evitamos duplicados por hora+título.
    best_by_pair: dict[tuple[time, str], tuple[int, ParsedRow, dict[str, Any]]] = {}
    for item in found:
        key = (item[1].start, _fold(item[1].title))
        prev = best_by_pair.get(key)
        if prev is None or item[0] > prev[0]:
            best_by_pair[key] = item

    # En una parrilla lineal debe haber un único programa principal por hora de
    # inicio. Si la API incluye metadatos duplicados, gana el candidato más fuerte.
    best_by_start: dict[time, tuple[int, ParsedRow, dict[str, Any]]] = {}
    for item in best_by_pair.values():
        start = item[1].start
        prev = best_by_start.get(start)
        if prev is None or item[0] > prev[0]:
            best_by_start[start] = item

    selected = sorted(best_by_start.values(), key=lambda item: item[1].start)
    rows = [item[1] for item in selected]
    diagnostics = {
        "dicts_scanned": scanned,
        "candidate_records": len(found),
        "selected_rows": len(rows),
        "selected_keys": [item[2] for item in selected[:12]],
    }
    return rows, diagnostics


def _make_driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise RuntimeError("Fallback de Ecuador TV requiere selenium.") from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,1600")
    options.add_argument("--lang=es-EC")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    return driver


def _fetch_api_with_browser() -> Any:
    """Fallback: usa el mismo origen/navegador, pero sigue leyendo la API real."""
    driver = None
    try:
        driver = _make_driver()
        driver.get(OFFICIAL_URL)
        script = r"""
        const done = arguments[arguments.length - 1];
        fetch('/api/schedule/today', {credentials: 'same-origin', cache: 'no-store'})
          .then(async r => {
            const text = await r.text();
            done({ok: r.ok, status: r.status, text});
          })
          .catch(e => done({ok: false, status: 0, text: String(e)}));
        """
        result = driver.execute_async_script(script)
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(f"fetch navegador falló: {result!r}")
        return json.loads(str(result.get("text") or ""))
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def fetch_official_api() -> tuple[Any, dict[str, Any]]:
    errors: list[str] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": OFFICIAL_URL,
        "Origin": "https://www.ecuadortv.ec",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        response = requests.get(API_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        return payload, {
            "method": "requests",
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body_chars": len(response.text),
            "errors": errors,
        }
    except Exception as exc:
        errors.append(f"requests: {type(exc).__name__}: {exc}")

    try:
        payload = _fetch_api_with_browser()
        return payload, {
            "method": "browser-fetch",
            "http_status": 200,
            "content_type": "application/json",
            "body_chars": len(json.dumps(payload, ensure_ascii=False)),
            "errors": errors,
        }
    except Exception as exc:
        errors.append(f"browser-fetch: {type(exc).__name__}: {exc}")
        raise RuntimeError(
            "Ecuador TV: no se pudo obtener la API oficial /api/schedule/today. "
            + " | ".join(errors)
        ) from exc


def _rows_span_hours(rows: list[ParsedRow]) -> float:
    if len(rows) < 2:
        return 0.0
    first = datetime.combine(date(2000, 1, 1), rows[0].start)
    last = datetime.combine(date(2000, 1, 1), rows[-1].start)
    return round((last - first).total_seconds() / 3600.0, 2)


def _validate_rows(rows: list[ParsedRow]) -> tuple[bool, float, str]:
    rows = sorted(rows, key=lambda item: item.start)
    span = _rows_span_hours(rows)
    if len(rows) < MIN_PROGRAMMES_PER_DAY:
        return False, span, "too-few-programmes"
    if span < MIN_SPAN_HOURS:
        return False, span, "span-too-short"
    if len({row.start for row in rows}) != len(rows):
        return False, span, "duplicate-start-times"
    return True, span, "accepted"


def build_programmes(rows: list[ParsedRow], *, day: date) -> tuple[list[Programme], dict[str, Any]]:
    rows = sorted(rows, key=lambda item: item.start)
    ok, span, reason = _validate_rows(rows)
    if not ok:
        return [], {
            "official_dates": [],
            "daily": {
                day.isoformat(): {
                    "api_programmes": len(rows),
                    "span_hours": span,
                    "accepted": False,
                    "reason": reason,
                }
            },
        }

    programmes: list[Programme] = []
    for idx, row in enumerate(rows):
        start = datetime.combine(day, row.start, tzinfo=EC_TZ)
        if row.stop is not None:
            stop = datetime.combine(day, row.stop, tzinfo=EC_TZ)
            if stop <= start:
                stop += timedelta(days=1)
        elif idx + 1 < len(rows):
            stop = datetime.combine(day, rows[idx + 1].start, tzinfo=EC_TZ)
            if stop <= start:
                stop += timedelta(days=1)
        else:
            stop = datetime.combine(day + timedelta(days=1), time.min, tzinfo=EC_TZ)
        if stop <= start:
            continue
        programmes.append(Programme(start=start, stop=stop, title=row.title))

    return programmes, {
        "official_dates": [day.isoformat()],
        "daily": {
            day.isoformat(): {
                "api_programmes": len(rows),
                "span_hours": span,
                "accepted": True,
                "reason": "accepted",
            }
        },
    }


def parse_xmltv_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S %z")


def xmltv_stamp(value: datetime) -> str:
    return value.astimezone(EC_TZ).strftime("%Y%m%d%H%M%S %z")


def _programme_interval(node: etree._Element) -> tuple[datetime, datetime] | None:
    try:
        return parse_xmltv_datetime(node.get("start", "")), parse_xmltv_datetime(node.get("stop", ""))
    except ValueError:
        return None


def _make_programme(item: Programme) -> etree._Element:
    node = etree.Element(
        "programme",
        start=xmltv_stamp(item.start),
        stop=xmltv_stamp(item.stop),
        channel=CHANNEL_ID,
    )
    etree.SubElement(node, "title", lang="es").text = item.title
    return node


def _overlap(start: datetime, stop: datetime, cut_start: datetime, cut_stop: datetime) -> bool:
    return stop > cut_start and start < cut_stop


def _replace_full_day(root: etree._Element, day: date, programmes: list[Programme]) -> int:
    ds = datetime.combine(day, time.min, tzinfo=EC_TZ)
    de = ds + timedelta(days=1)
    removed = 0
    for node in list(root.xpath("./programme[@channel=$cid]", cid=CHANNEL_ID)):
        interval = _programme_interval(node)
        if interval is None:
            continue
        start, stop = (value.astimezone(EC_TZ) for value in interval)
        if not _overlap(start, stop, ds, de):
            continue
        root.remove(node)
        removed += 1
        if start < ds:
            left = copy.deepcopy(node)
            left.set("stop", xmltv_stamp(ds))
            root.append(left)
        if stop > de:
            right = copy.deepcopy(node)
            right.set("start", xmltv_stamp(de))
            root.append(right)
    for item in programmes:
        root.append(_make_programme(item))
    return removed


def _sort_programmes(root: etree._Element) -> None:
    nodes = list(root.findall("programme"))
    for node in nodes:
        root.remove(node)
    nodes.sort(key=lambda node: (node.get("start", ""), node.get("channel", ""), node.get("stop", "")))
    root.extend(nodes)


def merge_into_tree(
    root: etree._Element,
    official: list[Programme],
    *,
    official_dates: Iterable[str],
) -> dict[str, Any]:
    accepted = {date.fromisoformat(value) for value in official_dates}
    by_day: dict[date, list[Programme]] = {}
    for item in official:
        by_day.setdefault(item.start.date(), []).append(item)

    replaced = 0
    inserted = 0
    for day in sorted(accepted):
        items = sorted(by_day.get(day, []), key=lambda item: item.start)
        replaced += _replace_full_day(root, day, items)
        inserted += len(items)

    _sort_programmes(root)
    final_nodes = root.xpath("./programme[@channel=$cid]", cid=CHANNEL_ID)
    return {
        "replaced_programmes": replaced,
        "official_api_programmes": inserted,
        "final_programmes": len(final_nodes),
        "total_programmes": len(root.findall("programme")),
    }


def _write_xml(tree: etree._ElementTree, xml_path: Path, gz_path: Path) -> None:
    # validate_outputs.py exige esta cabecera exacta byte por byte.
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
    data = exact_header + payload
    xml_path.write_bytes(data)
    with gz_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(data)
    if gzip.decompress(gz_path.read_bytes()) != data:
        raise RuntimeError(f"{gz_path}: GZIP no coincide con XML.")


def _read_base_date(status: dict[str, Any]) -> date:
    value = status.get("base_date")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(EC_TZ).date()


def _update_status(
    status_path: Path,
    *,
    base_date: date,
    source_info: dict[str, Any],
    parse_info: dict[str, Any],
    build_info: dict[str, Any],
    merge_info: dict[str, Any],
) -> None:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["version"] = repository_version()
    status["programmes"] = int(merge_info["total_programmes"])
    counts = status.setdefault("programme_counts", {})
    counts[CHANNEL_ID] = int(merge_info["final_programmes"])
    status["ecuador_tv_epg"] = {
        "version": VERSION,
        "channel_id": CHANNEL_ID,
        "source": API_URL,
        "source_page": OFFICIAL_URL,
        "source_timezone": SOURCE_TIMEZONE,
        "output_timezone": OUTPUT_TIMEZONE,
        "mode": "official-api-today+existing-guide-other-days",
        "fetch_method": source_info.get("method"),
        "http_status": source_info.get("http_status"),
        "body_chars": source_info.get("body_chars"),
        "official_dates": list(build_info["official_dates"]),
        "official_api_programmes": int(merge_info["official_api_programmes"]),
        "replaced_programmes": int(merge_info["replaced_programmes"]),
        "programmes": int(merge_info["final_programmes"]),
        "daily": build_info["daily"],
        "parser": parse_info,
        "errors": list(source_info.get("errors", [])),
    }
    status.setdefault("sources", {})["ecuador_tv_official_api"] = API_URL
    status["sources"]["ecuador_tv_official_page"] = OFFICIAL_URL
    # Retirar claves del parche provisional si existen.
    status["sources"].pop("ecuador_tv_noticias_7", None)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _patch_one(
    output_dir: Path,
    xml_name: str,
    status_name: str,
    *,
    base_date: date,
    source_info: dict[str, Any],
    parse_info: dict[str, Any],
    build_info: dict[str, Any],
    official: list[Programme],
) -> dict[str, Any] | None:
    xml_path = output_dir / xml_name
    gz_path = output_dir / f"{xml_name}.gz"
    status_path = output_dir / status_name
    if not xml_path.is_file() or not status_path.is_file():
        return None

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=True)
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    channels = root.xpath("./channel[@id=$cid]", cid=CHANNEL_ID)
    if len(channels) != 1:
        raise RuntimeError(f"{xml_name}: se esperaba exactamente un canal {CHANNEL_ID}; encontrados={len(channels)}")

    merge_info = merge_into_tree(
        root,
        official,
        official_dates=build_info["official_dates"],
    )
    if merge_info["final_programmes"] < 5:
        raise RuntimeError(f"{xml_name}: Ecuador TV quedó con programación insuficiente ({merge_info['final_programmes']}).")

    _write_xml(tree, xml_path, gz_path)
    _update_status(
        status_path,
        base_date=base_date,
        source_info=source_info,
        parse_info=parse_info,
        build_info=build_info,
        merge_info=merge_info,
    )
    return merge_info


def apply(output_dir: Path, days: int) -> dict[str, Any]:
    status_candidates = [output_dir / "latam-status.json", output_dir / "status.json"]
    status = None
    for path in status_candidates:
        if path.is_file():
            status = json.loads(path.read_text(encoding="utf-8"))
            break
    if status is None:
        raise RuntimeError("Ecuador TV v0.2.71 requiere status.json o latam-status.json existente.")

    base_date = _read_base_date(status)
    payload, source_info = fetch_official_api()
    rows, parse_info = extract_rows_from_json(payload)
    official, build_info = build_programmes(rows, day=base_date)

    preview = [f"{row.start.strftime('%H:%M')} {row.title}" for row in rows]
    print("ECUADORTV_API_SOURCE " + API_URL)
    print("ECUADORTV_API_FETCH " + json.dumps(source_info, ensure_ascii=False, sort_keys=True))
    print("ECUADORTV_API_PARSER " + json.dumps(parse_info, ensure_ascii=False, sort_keys=True))
    print("ECUADORTV_API_ROWS " + json.dumps(preview, ensure_ascii=False))

    if not build_info["official_dates"]:
        day_info = build_info["daily"].get(base_date.isoformat(), {})
        raise RuntimeError(
            "Ecuador TV: la API oficial respondió, pero la parrilla no superó la validación: "
            + json.dumps(day_info, ensure_ascii=False, sort_keys=True)
        )

    results: dict[str, Any] = {}
    for xml_name, status_name in (("ec.xml", "status.json"), ("latam.xml", "latam-status.json")):
        merge = _patch_one(
            output_dir,
            xml_name,
            status_name,
            base_date=base_date,
            source_info=source_info,
            parse_info=parse_info,
            build_info=build_info,
            official=official,
        )
        if merge is not None:
            results[xml_name] = merge

    if not results:
        raise RuntimeError("No se encontró ec.xml ni latam.xml para aplicar Ecuador TV v0.2.71.")

    return {
        "base_date": base_date.isoformat(),
        "source": source_info,
        "parser": parse_info,
        "build": build_info,
        "outputs": results,
    }


def self_test() -> None:
    # Variantes de esquema deliberadamente distintas: la API puede cambiar
    # nombres de claves sin que debamos volver a leer el DOM.
    fixture = {
        "data": {
            "schedule": [
                {"program": {"title": "Ecuador en movimiento"}, "start": "05h00"},
                {"program": {"name": "Educa"}, "start_time": "06:00:00"},
                {"titulo": "Noticias 7 Matinal", "inicio": 420},
                {"nombre": "Café TV", "hora": 830},
                {"show": {"title": "Somos cultura"}, "start": {"hour": 10, "minute": 0}},
                {"programa": {"nombre": "Ecuador diverso"}, "inicio": {"hora": 11, "minuto": 0}},
                {"title": "Noticias 7 Central", "start": [12, 30]},
                {"title": "Serie nacional", "startAt": "2026-09-24T13:30:00-05:00"},
                {"title": "Cine", "start": 900},
                {"title": "Magazine", "start": 1020},
                {"title": "Esta es mi canción", "start": 1080},
                {"title": "Noticias 7 Estelar", "start": 1140, "end": 1200},
                {"title": "Ficción Latina", "start": "2000"},
                {"title": "Fanático", "start": {"hour": 21, "minute": 0}},
                {"title": "Un Café con JJ", "start": "22h00"},
                {"title": "Estas Secretarias", "start": {"hour": 22, "minute": 30}},
            ]
        }
    }
    rows, info = extract_rows_from_json(fixture)
    mapping = {row.start.strftime("%H:%M"): row.title for row in rows}
    assert mapping["19:00"] == "Noticias 7 Estelar", mapping
    assert mapping["20:00"] == "Ficción Latina", mapping
    assert mapping["21:00"] == "Fanático", mapping
    assert mapping["22:00"] == "Un Café con JJ", mapping
    assert mapping["22:30"] == "Estas Secretarias", mapping
    assert info["selected_rows"] >= 12, info

    day = date(2026, 9, 24)
    programmes, build = build_programmes(rows, day=day)
    assert build["official_dates"] == ["2026-09-24"], build
    assert any(p.title == "Noticias 7 Estelar" and p.start.hour == 19 and p.stop.hour == 20 for p in programmes)

    # Verifica que el reemplazo sea del día oficial completo, sin bloques manuales.
    root = etree.Element("tv", **{"generator-info-name": "none", "generator-info-url": "none"})
    etree.SubElement(root, "channel", id=CHANNEL_ID)
    old = etree.SubElement(
        root, "programme",
        start="20260924183000 -0500",
        stop="20260924200000 -0500",
        channel=CHANNEL_ID,
    )
    etree.SubElement(old, "title", lang="es").text = "Esta es mi canción"
    merge = merge_into_tree(root, programmes, official_dates=build["official_dates"])
    at_19 = root.xpath(
        "./programme[@channel=$cid and @start='20260924190000 -0500']",
        cid=CHANNEL_ID,
    )
    assert len(at_19) == 1
    assert at_19[0].findtext("title") == "Noticias 7 Estelar"
    assert merge["official_api_programmes"] == len(programmes)

    print(
        "Prueba Ecuador TV v0.2.71 correcta: API oficial, parser JSON flexible, "
        "19:00 Noticias 7 Estelar, 20:00 Ficción Latina, 21:00 Fanático, "
        "22:00 Un Café con JJ y 22:30 Estas Secretarias."
    )


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="public")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.days < 1:
        raise SystemExit("--days debe ser >= 1")
    result = apply(Path(args.output), args.days)
    print(
        "Ecuador TV v0.2.71: "
        f"fuente={API_URL}; fechas oficiales={result['build']['official_dates']}; "
        f"salidas={list(result['outputs'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

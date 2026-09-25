#!/usr/bin/env python3
"""EPG MrG v0.2.69 - Ecuador TV desde su parrilla oficial.

Fuente primaria:
  https://www.ecuadortv.ec/programas

Estrategia:
1. Intenta leer con Selenium/Chrome la parrilla semanal renderizada de Ecuador TV.
2. Solo sustituye un día completo cuando la lectura parece suficientemente completa
   y, en días laborables, confirma el bloque oficial Noticias 7 Estelar 19:00-20:00.
3. Si un día no puede leerse de forma fiable, conserva la parrilla previa y aplica
   únicamente los bloques de Noticias 7 cuyo horario fijo publica Ecuador TV en su
   propia ficha oficial. Esto evita que una fuente secundaria sobrescriba, por
   ejemplo, Noticias 7 Estelar con "Esta es mi canción".

Se actualizan tanto ec.xml como latam.xml cuando existen.
"""

from __future__ import annotations

import copy
import gzip
import json
import re
import time as time_module
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from lxml import etree

VERSION = "0.2.69"
CHANNEL_ID = "Canal.Ecuador.TV.ec"
TARGET_IDS = (CHANNEL_ID,)
OFFICIAL_URL = "https://www.ecuadortv.ec/programas"
NEWS_URL = "https://www.ecuadortv.ec/programas/noticias-7"
OUTPUT_TIMEZONE = "America/Guayaquil"
SOURCE_TIMEZONE = "America/Guayaquil"
MANUAL_OFFSET_MINUTES = 0
MIN_PROGRAMMES_PER_DAY = 8
MIN_SPAN_HOURS = 9.0
PAGE_TIMEOUT_SECONDS = 45
POST_LOAD_SECONDS = 3.0

EC_TZ = ZoneInfo(OUTPUT_TIMEZONE)

WEEKDAY_NAMES = (
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
)
WEEKDAY_ALIASES = {
    0: ("lunes", "lun"),
    1: ("martes", "mar"),
    2: ("miércoles", "miercoles", "mié", "mie"),
    3: ("jueves", "jue"),
    4: ("viernes", "vie"),
    5: ("sábado", "sabado", "sáb", "sab"),
    6: ("domingo", "dom"),
}

TIME_TOKEN = r"(?:[01]?\d|2[0-3])\s*[:hH]\s*[0-5]\d(?:\s*:\s*[0-5]\d)?"
TIME_RE = re.compile(rf"(?<!\d)(?P<token>{TIME_TOKEN})(?!\d)")
RANGE_RE = re.compile(
    rf"(?<!\d)(?P<start>{TIME_TOKEN})\s*(?:-|–|—|a)\s*(?P<stop>{TIME_TOKEN})(?!\d)",
    re.IGNORECASE,
)

SECTION_END_MARKERS = (
    "rendicion de cuentas",
    "politica de privacidad",
    "politicas de privacidad",
    "codigo deontologico",
    "contactanos",
    "© copyright",
)
NOISE_LINES = {
    "programación", "programacion", "programas", "en vivo", "inicio", "menu", "menú",
    "lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo",
}


@dataclass(frozen=True, order=True)
class Programme:
    start: datetime
    stop: datetime
    title: str
    source: str = "official"


@dataclass(frozen=True)
class ParsedRow:
    start: time
    title: str
    stop: time | None = None


def repository_version() -> str:
    path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return VERSION
    return value or VERSION


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def _fold(value: str) -> str:
    value = _plain(value).lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _parse_clock(value: str) -> time | None:
    text = _plain(value).lower().replace("h", ":")
    parts = [part.strip() for part in text.split(":")]
    try:
        if len(parts) < 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) >= 3 else 0
        return time(hour, minute, second)
    except (TypeError, ValueError):
        return None


def _plausible_title(value: str) -> bool:
    text = _plain(value).strip(" -–—|:")
    folded = _fold(text)
    if not text or len(text) < 2 or len(text) > 160:
        return False
    if folded in {_fold(item) for item in NOISE_LINES}:
        return False
    if re.fullmatch(r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)", folded):
        return False
    if RANGE_RE.fullmatch(text) or TIME_RE.fullmatch(text):
        return False
    if re.fullmatch(r"\d{1,2}(?:/|-|\.)\d{1,2}(?:/|-|\.)20\d{2}", text):
        return False
    return True


def _schedule_section(body_text: str) -> str:
    text = body_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines()]

    # Preferimos el último encabezado "Programación" de la página, porque el
    # menú superior puede contener la misma palabra antes de la parrilla real.
    starts = [
        idx for idx, line in enumerate(lines)
        if _fold(line) in {"programacion", "programacion de hoy", "parrilla", "programacion semanal"}
        or _fold(line).startswith("programacion del")
    ]
    if starts:
        lines = lines[starts[-1]:]

    cut = len(lines)
    for idx, line in enumerate(lines[1:], start=1):
        folded = _fold(line)
        if any(marker in folded for marker in SECTION_END_MARKERS):
            cut = idx
            break
    return "\n".join(lines[:cut])


def extract_rows_from_visible_text(body_text: str) -> list[ParsedRow]:
    section = _schedule_section(body_text)
    lines = [_plain(line) for line in section.splitlines() if _plain(line)]
    rows: list[ParsedRow] = []

    for idx, line in enumerate(lines):
        range_match = RANGE_RE.search(line)
        if range_match:
            start = _parse_clock(range_match.group("start"))
            stop = _parse_clock(range_match.group("stop"))
            span = range_match.span()
        else:
            single = TIME_RE.search(line)
            if not single:
                continue
            start = _parse_clock(single.group("token"))
            stop = None
            span = single.span()

        if start is None:
            continue

        before = line[:span[0]].strip(" -–—|:")
        after = line[span[1]:].strip(" -–—|:")
        title = ""
        if _plausible_title(after):
            title = after
        elif _plausible_title(before):
            title = before
        else:
            for jump in (1, 2, 3):
                if idx + jump < len(lines) and _plausible_title(lines[idx + jump]):
                    title = lines[idx + jump]
                    break
            if not title and idx > 0 and _plausible_title(lines[idx - 1]):
                title = lines[idx - 1]

        if title:
            rows.append(ParsedRow(start=start, stop=stop, title=_plain(title)))

    # Un inicio de hora debe representar una sola emisión en la vista del día.
    unique: dict[time, ParsedRow] = {}
    for row in rows:
        unique.setdefault(row.start, row)
    return sorted(unique.values(), key=lambda item: item.start)


def extract_rows_from_html(html: str) -> list[ParsedRow]:
    soup = BeautifulSoup(html, "html.parser")
    return extract_rows_from_visible_text(soup.get_text("\n", strip=True))


def _weekday_click_matches(text: str, weekday: int) -> bool:
    folded = _fold(text)
    tokens = re.findall(r"[a-z]+", folded)
    aliases = {_fold(value) for value in WEEKDAY_ALIASES[weekday]}
    return any(token in aliases for token in tokens)


def _make_driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise RuntimeError(
            "Ecuador TV oficial requiere selenium; instala requirements.txt."
        ) from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,2400")
    options.add_argument("--lang=es-EC")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(PAGE_TIMEOUT_SECONDS)
    return driver


def _page_body_text(driver) -> str:
    from selenium.webdriver.common.by import By
    return driver.find_element(By.TAG_NAME, "body").text


def _capture_schedule(driver) -> tuple[list[ParsedRow], str]:
    rows = extract_rows_from_visible_text(_page_body_text(driver))
    mode = "rendered-text"
    if len(rows) < MIN_PROGRAMMES_PER_DAY:
        html_rows = extract_rows_from_html(driver.page_source)
        if len(html_rows) > len(rows):
            rows = html_rows
            mode = "rendered-html"
    return rows, mode


def _click_weekday(driver, target_date: date) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    selectors = "button, a, [role='button'], [role='tab'], [onclick]"
    elements = driver.find_elements(By.CSS_SELECTOR, selectors)
    candidate = None
    for element in elements:
        try:
            if not element.is_displayed():
                continue
            label = _plain(
                element.text
                or element.get_attribute("aria-label")
                or element.get_attribute("title")
                or ""
            )
            if _weekday_click_matches(label, target_date.weekday()):
                candidate = element
                break
        except Exception:
            continue
    if candidate is None:
        return False

    before = _schedule_section(_page_body_text(driver))
    try:
        driver.execute_script("arguments[0].click();", candidate)
    except Exception:
        try:
            candidate.click()
        except Exception:
            return False

    def changed(drv) -> bool:
        try:
            return _schedule_section(_page_body_text(drv)) != before
        except Exception:
            return False

    try:
        WebDriverWait(driver, 8).until(changed)
    except Exception:
        time_module.sleep(1.2)
    return True


def scrape_official(base_date: date, days: int) -> tuple[dict[date, list[ParsedRow]], dict[str, Any]]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    collected: dict[date, list[ParsedRow]] = {}
    attempts: list[dict[str, Any]] = []
    errors: list[str] = []
    driver = None

    try:
        driver = _make_driver()
        driver.get(OFFICIAL_URL)
        WebDriverWait(driver, 25).until(
            lambda d: "program" in _fold(d.find_element(By.TAG_NAME, "body").text)
        )
        time_module.sleep(POST_LOAD_SECONDS)

        # La página abre por defecto el día vigente; base_date es la fecha local
        # usada por la generación del EPG.
        rows, mode = _capture_schedule(driver)
        collected[base_date] = rows
        attempts.append({
            "target_date": base_date.isoformat(),
            "programmes": len(rows),
            "mode": mode,
            "clicked": False,
        })

        for offset in range(days):
            target = base_date + timedelta(days=offset)
            if target == base_date:
                continue
            try:
                clicked = _click_weekday(driver, target)
                if not clicked:
                    attempts.append({
                        "target_date": target.isoformat(),
                        "programmes": 0,
                        "mode": "weekday-tab-not-found",
                        "clicked": False,
                    })
                    continue
                time_module.sleep(0.8)
                rows, mode = _capture_schedule(driver)
                collected[target] = rows
                attempts.append({
                    "target_date": target.isoformat(),
                    "programmes": len(rows),
                    "mode": mode,
                    "clicked": True,
                })
            except Exception as exc:
                errors.append(f"{target.isoformat()}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"carga oficial: {type(exc).__name__}: {exc}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    return collected, {"attempts": attempts, "errors": errors[-20:]}


def _rows_span_hours(rows: list[ParsedRow]) -> float:
    if len(rows) < 2:
        return 0.0
    first = datetime.combine(date(2000, 1, 1), rows[0].start)
    last = datetime.combine(date(2000, 1, 1), rows[-1].start)
    return round((last - first).total_seconds() / 3600.0, 2)


def _has_estelar(rows: list[ParsedRow]) -> bool:
    for row in rows:
        if row.start == time(19, 0) and "noticias 7 estelar" in _fold(row.title):
            return True
    return False


def _rows_are_complete(day: date, rows: list[ParsedRow]) -> tuple[bool, float, str]:
    rows = sorted(rows, key=lambda item: item.start)
    span = _rows_span_hours(rows)
    if len(rows) < MIN_PROGRAMMES_PER_DAY:
        return False, span, "too-few-programmes"
    if span < MIN_SPAN_HOURS:
        return False, span, "span-too-short"
    # Este ancla es la corrección que motivó v0.2.69 y también funciona como
    # comprobación de que estamos leyendo la vista correcta del día laborable.
    if day.weekday() < 5 and not _has_estelar(rows):
        return False, span, "missing-noticias-7-estelar-1900"
    return True, span, "accepted"


def build_programmes(
    scraped: dict[date, list[ParsedRow]], *, base_date: date, days: int
) -> tuple[list[Programme], dict[str, Any]]:
    accepted: dict[date, list[ParsedRow]] = {}
    daily: dict[str, dict[str, Any]] = {}

    for offset in range(days):
        day = base_date + timedelta(days=offset)
        rows = sorted(scraped.get(day, []), key=lambda item: item.start)
        ok, span, reason = _rows_are_complete(day, rows)
        daily[day.isoformat()] = {
            "scraped_programmes": len(rows),
            "span_hours": span,
            "accepted": ok,
            "reason": reason,
        }
        if ok:
            accepted[day] = rows

    programmes: list[Programme] = []
    for day, rows in sorted(accepted.items()):
        for idx, row in enumerate(rows):
            start = datetime.combine(day, row.start, tzinfo=EC_TZ)
            if row.stop is not None:
                stop = datetime.combine(day, row.stop, tzinfo=EC_TZ)
                if stop <= start:
                    stop += timedelta(days=1)
            elif idx + 1 < len(rows):
                stop = datetime.combine(day, rows[idx + 1].start, tzinfo=EC_TZ)
            else:
                stop = datetime.combine(day + timedelta(days=1), time.min, tzinfo=EC_TZ)
            if stop > start:
                programmes.append(Programme(start=start, stop=stop, title=row.title))

    return programmes, {
        "official_dates": [day.isoformat() for day in sorted(accepted)],
        "daily": daily,
    }


def fixed_news_for_day(day: date) -> list[Programme]:
    """Horarios publicados por Ecuador TV en la ficha oficial de Noticias 7."""
    slots: list[tuple[time, time, str]] = []
    if day.weekday() < 5:
        slots.extend([
            (time(7, 0), time(8, 30), "Noticias 7 Matinal"),
            (time(12, 0), time(12, 3), "Micro Informativo"),
            (time(12, 30), time(13, 30), "Noticias 7 Central"),
            (time(19, 0), time(20, 0), "Noticias 7 Estelar"),
        ])
    else:
        if day.weekday() == 6:
            slots.append((time(10, 30), time(11, 0), "Noticias 7 Internacional"))
        slots.append((time(11, 0), time(11, 15), "Noticias 7 Resumen Nacional"))

    return [
        Programme(
            start=datetime.combine(day, start, tzinfo=EC_TZ),
            stop=datetime.combine(day, stop, tzinfo=EC_TZ),
            title=title,
            source="official-fixed-news",
        )
        for start, stop, title in slots
    ]


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


def _replace_interval(root: etree._Element, item: Programme) -> int:
    removed = 0
    existing = list(root.xpath("./programme[@channel=$cid]", cid=CHANNEL_ID))
    for node in existing:
        interval = _programme_interval(node)
        if interval is None:
            continue
        start, stop = interval
        start = start.astimezone(EC_TZ)
        stop = stop.astimezone(EC_TZ)
        if not _overlap(start, stop, item.start, item.stop):
            continue

        root.remove(node)
        removed += 1
        if start < item.start:
            left = copy.deepcopy(node)
            left.set("stop", xmltv_stamp(item.start))
            root.append(left)
        if stop > item.stop:
            right = copy.deepcopy(node)
            right.set("start", xmltv_stamp(item.stop))
            root.append(right)

    root.append(_make_programme(item))
    return removed


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
    base_date: date,
    days: int,
) -> dict[str, Any]:
    accepted = {date.fromisoformat(value) for value in official_dates}
    by_day: dict[date, list[Programme]] = {}
    for item in official:
        by_day.setdefault(item.start.date(), []).append(item)

    replaced = 0
    fixed_inserted = 0
    full_inserted = 0
    fallback_dates: list[str] = []

    for offset in range(days):
        day = base_date + timedelta(days=offset)
        if day in accepted:
            items = sorted(by_day.get(day, []), key=lambda item: item.start)
            replaced += _replace_full_day(root, day, items)
            full_inserted += len(items)
        else:
            fallback_dates.append(day.isoformat())
            for item in fixed_news_for_day(day):
                replaced += _replace_interval(root, item)
                fixed_inserted += 1

    _sort_programmes(root)
    final_nodes = root.xpath("./programme[@channel=$cid]", cid=CHANNEL_ID)
    return {
        "replaced_programmes": replaced,
        "official_full_programmes": full_inserted,
        "official_fixed_programmes": fixed_inserted,
        "final_programmes": len(final_nodes),
        "fallback_dates": fallback_dates,
        "total_programmes": len(root.findall("programme")),
    }


def _write_xml(tree: etree._ElementTree, xml_path: Path, gz_path: Path) -> None:
    doctype = tree.docinfo.doctype or '<!DOCTYPE tv SYSTEM "xmltv.dtd">'
    data = etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
        doctype=doctype,
    )
    xml_path.write_bytes(data)
    with gz_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(data)


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
        "source": OFFICIAL_URL,
        "news_schedule_source": NEWS_URL,
        "source_timezone": SOURCE_TIMEZONE,
        "output_timezone": OUTPUT_TIMEZONE,
        "manual_offset_minutes": MANUAL_OFFSET_MINUTES,
        "mode": "official-rendered-primary+official-news-fixed-fallback+existing-guide",
        "renderer": "selenium-chrome-headless",
        "official_dates": list(build_info["official_dates"]),
        "fixed_fallback_dates": list(merge_info["fallback_dates"]),
        "official_full_programmes": int(merge_info["official_full_programmes"]),
        "official_fixed_programmes": int(merge_info["official_fixed_programmes"]),
        "replaced_programmes": int(merge_info["replaced_programmes"]),
        "programmes": int(merge_info["final_programmes"]),
        "daily": build_info["daily"],
        "attempts": list(source_info.get("attempts", [])),
        "errors": list(source_info.get("errors", [])),
        "verified_fixed_slots": {
            "weekdays": [
                "07:00-08:30 Noticias 7 Matinal",
                "12:00-12:03 Micro Informativo",
                "12:30-13:30 Noticias 7 Central",
                "19:00-20:00 Noticias 7 Estelar",
            ],
            "saturday": ["11:00-11:15 Noticias 7 Resumen Nacional"],
            "sunday": [
                "10:30-11:00 Noticias 7 Internacional",
                "11:00-11:15 Noticias 7 Resumen Nacional",
            ],
        },
    }
    status.setdefault("sources", {})["ecuador_tv_official"] = OFFICIAL_URL
    status["sources"]["ecuador_tv_noticias_7"] = NEWS_URL
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _patch_one(
    output_dir: Path,
    xml_name: str,
    status_name: str,
    *,
    base_date: date,
    days: int,
    source_info: dict[str, Any],
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
        base_date=base_date,
        days=days,
    )
    if merge_info["final_programmes"] < 5:
        raise RuntimeError(f"{xml_name}: Ecuador TV quedó con programación insuficiente ({merge_info['final_programmes']}).")

    _write_xml(tree, xml_path, gz_path)
    _update_status(
        status_path,
        base_date=base_date,
        source_info=source_info,
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
        raise RuntimeError("Ecuador TV v0.2.69 requiere status.json o latam-status.json existente.")

    base_date = _read_base_date(status)
    scraped, source_info = scrape_official(base_date, days)
    official, build_info = build_programmes(scraped, base_date=base_date, days=days)

    results: dict[str, Any] = {}
    for xml_name, status_name in (("ec.xml", "status.json"), ("latam.xml", "latam-status.json")):
        merge = _patch_one(
            output_dir,
            xml_name,
            status_name,
            base_date=base_date,
            days=days,
            source_info=source_info,
            build_info=build_info,
            official=official,
        )
        if merge is not None:
            results[xml_name] = merge

    if not results:
        raise RuntimeError("No se encontró ec.xml ni latam.xml para aplicar Ecuador TV v0.2.69.")

    if not build_info["official_dates"]:
        print(
            "ADVERTENCIA Ecuador TV v0.2.69: no se aceptó un día completo desde la vista renderizada; "
            "se conservaron los demás programas y se aplicaron los horarios fijos oficiales de Noticias 7."
        )

    return {
        "base_date": base_date.isoformat(),
        "source": source_info,
        "build": build_info,
        "outputs": results,
    }


def self_test() -> None:
    fixture = """
    Programación
    Lunes Martes Miércoles Jueves Viernes Sábado Domingo
    05:00 - 06:00 Ecuador en movimiento
    06:00 - 07:00 Educa
    07:00 - 08:30 Noticias 7 Matinal
    08:30 - 10:00 Café TV
    10:00 - 11:00 Somos cultura
    11:00 - 12:00 Ecuador diverso
    12:00 - 12:03 Micro Informativo
    12:03 - 12:30 Conexión
    12:30 - 13:30 Noticias 7 Central
    13:30 - 15:00 Serie nacional
    15:00 - 17:00 Cine
    17:00 - 18:00 Magazine
    18:00 - 19:00 Esta es mi canción
    19:00 - 20:00 Noticias 7 Estelar
    20:00 - 21:00 Amor Profundo
    21:00 - 22:00 Fanático
    22:00 - 23:00 Documental
    23:00 - 23:59 Cine ecuatoriano
    """
    rows = extract_rows_from_visible_text(fixture)
    assert len(rows) == 18, rows
    assert dict((r.start, r.title) for r in rows)[time(19, 0)] == "Noticias 7 Estelar"

    day = date(2026, 9, 24)  # jueves
    built, info = build_programmes({day: rows}, base_date=day, days=1)
    assert info["official_dates"] == ["2026-09-24"], info
    assert any(p.title == "Noticias 7 Estelar" and p.start.hour == 19 for p in built)

    # Prueba crítica del fallback: un bloque viejo 18:30-20:00 debe partirse en
    # 18:30-19:00 y sustituirse 19:00-20:00 por Noticias 7 Estelar.
    root = etree.Element("tv")
    etree.SubElement(root, "channel", id=CHANNEL_ID)
    old = etree.SubElement(
        root, "programme",
        start="20260924183000 -0500",
        stop="20260924200000 -0500",
        channel=CHANNEL_ID,
    )
    etree.SubElement(old, "title", lang="es").text = "Esta es mi canción"
    old2 = etree.SubElement(
        root, "programme",
        start="20260924200000 -0500",
        stop="20260924210000 -0500",
        channel=CHANNEL_ID,
    )
    etree.SubElement(old2, "title", lang="es").text = "Programa siguiente"

    merge = merge_into_tree(
        root,
        [],
        official_dates=[],
        base_date=day,
        days=1,
    )
    nodes = root.xpath("./programme[@channel=$cid]", cid=CHANNEL_ID)
    at_19 = [n for n in nodes if n.get("start") == "20260924190000 -0500"]
    assert len(at_19) == 1, [(n.get("start"), n.findtext("title")) for n in nodes]
    assert at_19[0].get("stop") == "20260924200000 -0500"
    assert at_19[0].findtext("title") == "Noticias 7 Estelar"
    assert not any(
        n.findtext("title") == "Esta es mi canción"
        and n.get("start") <= "20260924190000 -0500" < n.get("stop")
        for n in nodes
    )
    assert merge["official_fixed_programmes"] == 4, merge

    weekend = fixed_news_for_day(date(2026, 9, 27))
    assert [(p.start.strftime("%H:%M"), p.title) for p in weekend] == [
        ("10:30", "Noticias 7 Internacional"),
        ("11:00", "Noticias 7 Resumen Nacional"),
    ]

    print(
        "Prueba Ecuador TV v0.2.69 correcta: parser oficial, validación de Noticias 7 Estelar 19:00, "
        "overlay de horarios fijos y partición segura de programas previos."
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
        "Ecuador TV v0.2.69: "
        f"fechas oficiales={result['build']['official_dates']}; "
        f"salidas={list(result['outputs'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

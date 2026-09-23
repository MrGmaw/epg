#!/usr/bin/env python3
"""EPG MrG v0.2.67 - TC Televisión desde la parrilla oficial renderizada.

Fuente primaria:
  https://tctelevision.com/programacion/

La página de TC carga su parrilla mediante JavaScript. Este módulo utiliza
Chrome headless/Selenium para leer la vista oficial ya renderizada. Solo
sustituye un día de la programación existente cuando la parrilla oficial
alcanza un mínimo razonable de emisiones y extensión horaria; los demás días
conservan la guía que ya exista en latam.xml.

La reproducción de TC no forma parte de este módulo.
"""

from __future__ import annotations

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

VERSION = "0.2.67"
CHANNEL_ID = "Canal.TC.Televisión.ec"
TARGET_IDS = (CHANNEL_ID,)
OFFICIAL_URL = "https://tctelevision.com/programacion/"
OUTPUT_TIMEZONE = "America/Guayaquil"
SOURCE_TIMEZONE = "America/Guayaquil"
MANUAL_OFFSET_MINUTES = 0
MIN_PROGRAMMES_PER_DAY = 8
MIN_SPAN_HOURS = 10.0
PAGE_TIMEOUT_SECONDS = 45
POST_LOAD_SECONDS = 3.0

EC_TZ = ZoneInfo(OUTPUT_TIMEZONE)

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
WEEKDAY_NAMES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
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

TIME_RE = re.compile(
    r"(?<!\d)(?P<hour>[01]?\d|2[0-3])\s*(?P<sep>[:hH])\s*(?P<minute>[0-5]\d)"
    r"(?:\s*(?P<ampm>[AaPp]\.?[Mm]\.?))?(?!\d)"
)
DATE_RE = re.compile(
    r"(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s*,?\s*)?"
    r"(?P<day>\d{1,2})\s+(?:de\s+)?"
    r"(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)"
    r"(?:\s+(?:de\s+)?)?(?P<year>20\d{2})",
    re.IGNORECASE,
)

SECTION_END_MARKERS = (
    "rendicion de cuentas",
    "politicas de privacidad",
    "codigo deontologico",
    "buzon:",
    "© copyright",
)

NOISE_LINES = {
    "programación del",
    "programacion del",
    "en vivo",
    "cerrar",
    "inicio",
    "menu",
    "menú",
}


@dataclass(frozen=True, order=True)
class TCProgramme:
    start: datetime
    stop: datetime
    title: str


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


def parse_spanish_date(text: str) -> date | None:
    match = DATE_RE.search(_plain(text))
    if not match:
        return None
    month_name = _fold(match.group("month"))
    month = SPANISH_MONTHS.get(month_name)
    if month is None:
        return None
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def parse_time_token(text: str) -> tuple[time, tuple[int, int]] | None:
    match = TIME_RE.search(_plain(text))
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = (match.group("ampm") or "").lower().replace(".", "")
    if ampm:
        if hour > 12:
            return None
        if ampm == "am":
            hour = 0 if hour == 12 else hour
        elif ampm == "pm":
            hour = 12 if hour == 12 else hour + 12
    return time(hour, minute), match.span()


def _schedule_section(body_text: str) -> str:
    text = body_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if "programacion del" in _fold(line):
            lines = lines[idx:]
            break
    cut = len(lines)
    for idx, line in enumerate(lines[1:], start=1):
        folded_line = _fold(line)
        if any(marker in folded_line for marker in SECTION_END_MARKERS):
            cut = idx
            break
    return "\n".join(lines[:cut])


def _plausible_title(value: str) -> bool:
    text = _plain(value).strip(" -–—|:")
    folded = _fold(text)
    if not text or len(text) < 2 or len(text) > 140:
        return False
    if folded in {_fold(item) for item in NOISE_LINES}:
        return False
    if parse_spanish_date(text) is not None:
        return False
    parsed = parse_time_token(text)
    if parsed is not None:
        _, span = parsed
        if not text[:span[0]].strip() and not text[span[1]:].strip(" -–—|:"):
            return False
    if folded in {_fold(name) for name in WEEKDAY_NAMES}:
        return False
    return True


def extract_rows_from_visible_text(
    body_text: str,
    *,
    expected_date: date,
) -> tuple[date, list[tuple[time, str]]]:
    section = _schedule_section(body_text)
    section_date = parse_spanish_date(section) or expected_date
    lines = [_plain(line) for line in section.splitlines()]
    lines = [line for line in lines if line]

    rows: list[tuple[time, str]] = []
    for idx, line in enumerate(lines):
        parsed = parse_time_token(line)
        if parsed is None:
            continue
        start_time, span = parsed
        before = line[:span[0]].strip(" -–—|:")
        after = line[span[1]:].strip(" -–—|:")

        title = ""
        if _plausible_title(after):
            title = after
        elif _plausible_title(before):
            title = before
        else:
            for jump in (1, 2):
                if idx + jump < len(lines) and _plausible_title(lines[idx + jump]):
                    title = lines[idx + jump]
                    break
            if not title and idx > 0 and _plausible_title(lines[idx - 1]):
                title = lines[idx - 1]

        if title:
            rows.append((start_time, _plain(title)))

    unique: dict[time, str] = {}
    for start_time, title in rows:
        unique.setdefault(start_time, title)
    return section_date, sorted(unique.items(), key=lambda item: item[0])


def extract_rows_from_html(
    html: str,
    *,
    expected_date: date,
) -> tuple[date, list[tuple[time, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text("\n", strip=True)
    section_date, visible_rows = extract_rows_from_visible_text(
        body_text, expected_date=expected_date
    )
    if len(visible_rows) >= MIN_PROGRAMMES_PER_DAY:
        return section_date, visible_rows

    rows: list[tuple[time, str]] = []
    for string in soup.find_all(string=TIME_RE):
        text = _plain(string)
        parsed = parse_time_token(text)
        if parsed is None:
            continue
        start_time, _ = parsed
        node = getattr(string, "parent", None)
        if node is None:
            continue

        candidates: list[str] = []
        cursor = node
        for _ in range(4):
            if cursor is None:
                break
            values = [_plain(item) for item in cursor.stripped_strings]
            values = [item for item in values if item]
            if 2 <= len(values) <= 8:
                candidates = values
                break
            cursor = getattr(cursor, "parent", None)

        for candidate in candidates:
            parsed_candidate = parse_time_token(candidate)
            if parsed_candidate is not None:
                _, span = parsed_candidate
                remainder = candidate[span[1]:].strip(" -–—|:")
                if _plausible_title(remainder):
                    rows.append((start_time, remainder))
                    break
                if candidate[:span[0]].strip() == "" and remainder == "":
                    continue
            if candidate != text and _plausible_title(candidate):
                rows.append((start_time, candidate))
                break

    unique: dict[time, str] = {}
    for start_time, title in rows:
        unique.setdefault(start_time, _plain(title))
    if len(unique) > len(visible_rows):
        return section_date, sorted(unique.items(), key=lambda item: item[0])
    return section_date, visible_rows


def _weekday_click_matches(text: str, weekday: int) -> bool:
    folded = _fold(text)
    if not folded:
        return False
    tokens = re.findall(r"[a-z]+", folded)
    aliases = {_fold(value) for value in WEEKDAY_ALIASES[weekday]}
    return any(token in aliases for token in tokens)


def _make_driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise RuntimeError(
            "TC oficial requiere selenium; instala requirements.txt de v0.2.67."
        ) from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,2200")
    options.add_argument("--lang=es-EC")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(PAGE_TIMEOUT_SECONDS)
    return driver


def _page_body_text(driver) -> str:
    from selenium.webdriver.common.by import By
    return driver.find_element(By.TAG_NAME, "body").text


def _capture_schedule(
    driver,
    *,
    expected_date: date,
) -> tuple[date, list[tuple[time, str]], str]:
    body = _page_body_text(driver)
    parsed_date, rows = extract_rows_from_visible_text(
        body, expected_date=expected_date
    )
    mode = "rendered-text"
    if len(rows) < MIN_PROGRAMMES_PER_DAY:
        parsed_date, rows = extract_rows_from_html(
            driver.page_source, expected_date=expected_date
        )
        mode = "rendered-html"
    return parsed_date, rows, mode


def _click_weekday(driver, target_date: date) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    elements = driver.find_elements(
        By.CSS_SELECTOR,
        "button, a, [role='button'], [role='tab'], [onclick]",
    )
    candidate = None
    for element in elements:
        try:
            if not element.is_displayed():
                continue
            label = _plain(
                element.text or element.get_attribute("aria-label") or ""
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
        time_module.sleep(1.5)
    return _schedule_section(_page_body_text(driver)) != before


def scrape_official(
    base_date: date,
    days: int,
) -> tuple[dict[date, list[tuple[time, str]]], dict[str, Any]]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver = None
    collected: dict[date, list[tuple[time, str]]] = {}
    errors: list[str] = []
    attempts: list[dict[str, Any]] = []

    try:
        driver = _make_driver()
        driver.get(OFFICIAL_URL)
        WebDriverWait(driver, 25).until(
            lambda d: "programacion" in _fold(
                d.find_element(By.TAG_NAME, "body").text
            )
        )
        time_module.sleep(POST_LOAD_SECONDS)

        parsed_date, rows, mode = _capture_schedule(
            driver, expected_date=base_date
        )
        window_end = base_date + timedelta(days=days)
        if base_date <= parsed_date < window_end:
            collected[parsed_date] = rows
        attempts.append(
            {
                "target_date": base_date.isoformat(),
                "parsed_date": parsed_date.isoformat(),
                "programmes": len(rows),
                "mode": mode,
                "clicked": False,
            }
        )

        for offset in range(days):
            target = base_date + timedelta(days=offset)
            if target in collected and len(collected[target]) >= MIN_PROGRAMMES_PER_DAY:
                continue
            try:
                clicked = _click_weekday(driver, target)
                if not clicked:
                    attempts.append(
                        {
                            "target_date": target.isoformat(),
                            "programmes": 0,
                            "mode": "weekday-tab-not-found",
                            "clicked": False,
                        }
                    )
                    continue

                time_module.sleep(0.8)
                parsed_date, rows, mode = _capture_schedule(
                    driver, expected_date=target
                )
                effective_date = parsed_date
                if not (base_date <= effective_date < window_end):
                    effective_date = target
                collected[effective_date] = rows
                attempts.append(
                    {
                        "target_date": target.isoformat(),
                        "parsed_date": effective_date.isoformat(),
                        "programmes": len(rows),
                        "mode": mode,
                        "clicked": True,
                    }
                )
            except Exception as exc:
                errors.append(
                    f"{target.isoformat()}: {type(exc).__name__}: {exc}"
                )

    except Exception as exc:
        errors.append(f"carga oficial: {type(exc).__name__}: {exc}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    return collected, {"attempts": attempts, "errors": errors[-20:]}


def _rows_are_complete(
    rows: list[tuple[time, str]],
) -> tuple[bool, float]:
    if len(rows) < MIN_PROGRAMMES_PER_DAY:
        return False, 0.0
    ordered = sorted(rows, key=lambda item: item[0])
    first = datetime.combine(date(2000, 1, 1), ordered[0][0])
    last = datetime.combine(date(2000, 1, 1), ordered[-1][0])
    span = (last - first).total_seconds() / 3600.0
    return span >= MIN_SPAN_HOURS, round(span, 2)


def build_programmes(
    scraped: dict[date, list[tuple[time, str]]],
    *,
    base_date: date,
    days: int,
) -> tuple[list[TCProgramme], dict[str, Any]]:
    accepted: dict[date, list[tuple[time, str]]] = {}
    daily: dict[str, dict[str, Any]] = {}

    for offset in range(days):
        day = base_date + timedelta(days=offset)
        rows = sorted(scraped.get(day, []), key=lambda item: item[0])
        complete, span_hours = _rows_are_complete(rows)
        daily[day.isoformat()] = {
            "scraped_programmes": len(rows),
            "span_hours": span_hours,
            "accepted": complete,
        }
        if complete:
            accepted[day] = rows

    flat_starts: list[tuple[datetime, str]] = []
    for day, rows in sorted(accepted.items()):
        for start_time, title in rows:
            flat_starts.append(
                (datetime.combine(day, start_time, tzinfo=EC_TZ), title)
            )
    flat_starts.sort(key=lambda item: item[0])

    programmes: list[TCProgramme] = []
    for idx, (start, title) in enumerate(flat_starts):
        day_end = datetime.combine(
            start.date() + timedelta(days=1), time.min, tzinfo=EC_TZ
        )
        if idx + 1 < len(flat_starts):
            next_start = flat_starts[idx + 1][0]
            stop = next_start if next_start.date() == start.date() else day_end
        else:
            stop = day_end
        if stop > start:
            programmes.append(
                TCProgramme(start=start, stop=stop, title=title)
            )

    return programmes, {
        "official_dates": [day.isoformat() for day in sorted(accepted)],
        "daily": daily,
    }


def parse_xmltv_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S %z")


def xmltv_stamp(value: datetime) -> str:
    return value.astimezone(EC_TZ).strftime("%Y%m%d%H%M%S %z")


def _programme_interval(
    node: etree._Element,
) -> tuple[datetime, datetime] | None:
    try:
        return (
            parse_xmltv_datetime(node.get("start", "")),
            parse_xmltv_datetime(node.get("stop", "")),
        )
    except ValueError:
        return None


def _overlaps_date(
    start: datetime,
    stop: datetime,
    day: date,
) -> bool:
    ds = datetime.combine(day, time.min, tzinfo=EC_TZ)
    de = ds + timedelta(days=1)
    local_start = start.astimezone(EC_TZ)
    local_stop = stop.astimezone(EC_TZ)
    return local_stop > ds and local_start < de


def _make_programme(item: TCProgramme) -> etree._Element:
    node = etree.Element(
        "programme",
        start=xmltv_stamp(item.start),
        stop=xmltv_stamp(item.stop),
        channel=CHANNEL_ID,
    )
    etree.SubElement(node, "title", lang="es").text = item.title
    return node


def merge_into_tree(
    root: etree._Element,
    official: list[TCProgramme],
    *,
    official_dates: Iterable[str],
) -> dict[str, Any]:
    accepted_dates = {
        date.fromisoformat(value) for value in official_dates
    }
    existing = list(
        root.xpath(
            "./programme[@channel=$channel_id]",
            channel_id=CHANNEL_ID,
        )
    )

    removed = 0
    for node in existing:
        interval = _programme_interval(node)
        if interval is None:
            continue
        if any(
            _overlaps_date(interval[0], interval[1], day)
            for day in accepted_dates
        ):
            root.remove(node)
            removed += 1

    for item in official:
        root.append(_make_programme(item))

    programmes = list(root.findall("programme"))
    for node in programmes:
        root.remove(node)
    programmes.sort(
        key=lambda node: (
            node.get("start", ""),
            node.get("channel", ""),
            node.get("stop", ""),
        )
    )
    root.extend(programmes)

    final_nodes = root.xpath(
        "./programme[@channel=$channel_id]",
        channel_id=CHANNEL_ID,
    )
    return {
        "replaced_programmes": removed,
        "official_programmes": len(official),
        "final_programmes": len(final_nodes),
        "fallback_programmes_kept": len(final_nodes) - len(official),
        "total_programmes": len(root.findall("programme")),
    }


def _read_base_date(status: dict[str, Any]) -> date:
    value = status.get("base_date")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(EC_TZ).date()


def _write_xml(
    tree: etree._ElementTree,
    xml_path: Path,
    gz_path: Path,
) -> None:
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
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            compresslevel=9,
            mtime=0,
        ) as gz:
            gz.write(data)


def update_status(
    status_path: Path,
    *,
    base_date: date,
    days: int,
    source_info: dict[str, Any],
    build_info: dict[str, Any],
    merge_info: dict[str, Any],
) -> None:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["version"] = repository_version()
    status["programmes"] = int(merge_info["total_programmes"])

    counts = status.setdefault("programme_counts", {})
    counts[CHANNEL_ID] = int(merge_info["final_programmes"])

    official_dates = list(build_info["official_dates"])
    window_dates = [
        (base_date + timedelta(days=offset)).isoformat()
        for offset in range(days)
    ]
    fallback_dates = [
        value for value in window_dates
        if value not in official_dates
    ]

    status["tc_television_epg"] = {
        "version": VERSION,
        "channel_id": CHANNEL_ID,
        "source": OFFICIAL_URL,
        "source_timezone": SOURCE_TIMEZONE,
        "output_timezone": OUTPUT_TIMEZONE,
        "manual_offset_minutes": MANUAL_OFFSET_MINUTES,
        "mode": "official-rendered-primary+existing-latam-fallback",
        "renderer": "selenium-chrome-headless",
        "official_dates": official_dates,
        "fallback_dates": fallback_dates,
        "official_programmes": int(
            merge_info["official_programmes"]
        ),
        "fallback_programmes_kept": int(
            merge_info["fallback_programmes_kept"]
        ),
        "replaced_programmes": int(
            merge_info["replaced_programmes"]
        ),
        "programmes": int(merge_info["final_programmes"]),
        "daily": build_info["daily"],
        "attempts": list(source_info.get("attempts", [])),
        "errors": list(source_info.get("errors", [])),
    }

    sources = status.setdefault("sources", {})
    sources["tc_television_official"] = OFFICIAL_URL

    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def apply(output_dir: Path, days: int) -> dict[str, Any]:
    xml_path = output_dir / "latam.xml"
    gz_path = output_dir / "latam.xml.gz"
    status_path = output_dir / "latam-status.json"

    if not xml_path.is_file() or not status_path.is_file():
        raise RuntimeError(
            "TC v0.2.67 requiere latam.xml y latam-status.json existentes."
        )

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()

    channels = root.xpath(
        "./channel[@id=$channel_id]",
        channel_id=CHANNEL_ID,
    )
    if len(channels) != 1:
        raise RuntimeError(
            f"Se esperaba exactamente un canal {CHANNEL_ID}; "
            f"encontrados={len(channels)}"
        )

    status = json.loads(
        status_path.read_text(encoding="utf-8")
    )
    base_date = _read_base_date(status)

    scraped, source_info = scrape_official(base_date, days)
    official, build_info = build_programmes(
        scraped,
        base_date=base_date,
        days=days,
    )

    merge_info = merge_into_tree(
        root,
        official,
        official_dates=build_info["official_dates"],
    )

    if merge_info["final_programmes"] < MIN_PROGRAMMES_PER_DAY:
        raise RuntimeError(
            "TC: ni la parrilla oficial ni la guía previa contienen "
            f"suficientes emisiones "
            f"({merge_info['final_programmes']})."
        )

    _write_xml(tree, xml_path, gz_path)
    update_status(
        status_path,
        base_date=base_date,
        days=days,
        source_info=source_info,
        build_info=build_info,
        merge_info=merge_info,
    )

    if not build_info["official_dates"]:
        print(
            "ADVERTENCIA TC v0.2.67: no se aceptó ningún día oficial; "
            "se conserva íntegramente el fallback ya presente."
        )

    return {
        "base_date": base_date.isoformat(),
        "source": source_info,
        "build": build_info,
        "merge": merge_info,
    }


def self_test() -> None:
    fixture = """
    martes, 22 septiembre 2026
    Programación del
    martes, 22 septiembre 2026
    00:00 Encuentro con la verdad
    01:00 Cuatro cuartos
    03:30 Educa
    04:30 Hechizada
    05:15 Mi Bella Genio
    05:40 DespierTC
    07:00 El Noticiero I
    08:30 Entre ellas
    10:00 De casa en casa
    11:30 Caminos de amor
    12:00 El Noticiero II
    14:00 Después de El Noticiero
    15:00 Hilos de vida
    16:15 Soy el mejor
    19:00 El Noticiero III
    20:30 Novela estelar
    22:00 Programa nocturno
    Rendición de cuentas 2025
    """

    expected = date(2026, 9, 22)
    parsed_date, rows = extract_rows_from_visible_text(
        fixture,
        expected_date=expected,
    )
    assert parsed_date == expected, parsed_date
    assert len(rows) == 17, rows
    assert rows[6][1] == "El Noticiero I", rows[6]

    built, info = build_programmes(
        {expected: rows},
        base_date=expected,
        days=1,
    )
    assert info["official_dates"] == ["2026-09-22"], info
    assert len(built) == 17, built
    assert built[0].start.strftime("%H:%M") == "00:00"
    assert (
        built[-1].stop.strftime("%Y-%m-%d %H:%M")
        == "2026-09-23 00:00"
    )

    root = etree.Element("tv")
    etree.SubElement(root, "channel", id=CHANNEL_ID)
    old = etree.SubElement(
        root,
        "programme",
        start="20260922070000 -0500",
        stop="20260922080000 -0500",
        channel=CHANNEL_ID,
    )
    etree.SubElement(
        old,
        "title",
        lang="es",
    ).text = "Fallback viejo"

    merged = merge_into_tree(
        root,
        built,
        official_dates=info["official_dates"],
    )
    titles = [
        node.findtext("title")
        for node in root.xpath(
            "./programme[@channel=$channel_id]",
            channel_id=CHANNEL_ID,
        )
    ]
    assert "Fallback viejo" not in titles
    assert "El Noticiero I" in titles
    assert merged["official_programmes"] == 17
    assert merged["final_programmes"] == 17

    print(
        "Prueba TC v0.2.67 correcta: parser de parrilla oficial "
        "renderizada, America/Guayaquil, overlay por día y "
        "fallback preservado."
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
    merge = result["merge"]
    build = result["build"]
    print(
        "TC v0.2.67: "
        f"oficiales={merge['official_programmes']}; "
        f"reemplazadas={merge['replaced_programmes']}; "
        f"finales={merge['final_programmes']}; "
        f"fechas oficiales={build['official_dates']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

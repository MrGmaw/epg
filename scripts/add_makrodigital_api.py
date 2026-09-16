#!/usr/bin/env python3
"""EPG MrG v0.2.66 - MakroDigital desde su API dinámica oficial.

Fuente primaria:
  POST https://makrodigitaltelevision.com/admin/api/getData-test.php
  {"channel":"14","timeZone":"America/Guayaquil","nowUtc":"...Z"}

La API entrega start_dt/end_dt explícitamente en UTC. Este módulo consulta varios
puntos por día, deduplica current/next/future, convierte UTC -> America/Guayaquil
y reemplaza la programación semanal únicamente donde existe cobertura dinámica.
Si la API falla o no cubre una fecha, se conserva la parrilla ya presente en
latam.xml (fuente semanal New York del generador LATAM) como fallback.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from lxml import etree

VERSION = "0.2.66"
CHANNEL_ID = "MakroDigitalTV.ec"
TARGET_IDS = (CHANNEL_ID,)
API_CHANNEL = 14
API_URL = "https://makrodigitaltelevision.com/admin/api/getData-test.php"
WIDGET_URL = "https://makrodigitaltelevision.com/admin/api/widget.html?channel=14"
WEEKLY_URL = "https://makrodigitaltelevision.com/programacion/"
OUTPUT_TIMEZONE = "America/Guayaquil"
SOURCE_TIMEZONE = "UTC"
MANUAL_OFFSET_MINUTES = 0
QUERY_LOCAL_HOURS = (0, 4, 8, 12, 16, 20)
MIN_DYNAMIC_PROGRAMMES_PER_DAY = 5
FULL_DAY_COVERAGE_HOURS = 18.0
REQUEST_TIMEOUT = 25
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
EC_TZ = ZoneInfo(OUTPUT_TIMEZONE)
UTC = timezone.utc


@dataclass(frozen=True, order=True)
class ApiProgramme:
    start_utc: datetime
    end_utc: datetime
    title: str
    image_url: str | None = None

    @property
    def start_local(self) -> datetime:
        return self.start_utc.astimezone(EC_TZ)

    @property
    def end_local(self) -> datetime:
        return self.end_utc.astimezone(EC_TZ)


def repository_version() -> str:
    path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return VERSION
    return value or VERSION


def parse_api_datetime(value: str) -> datetime:
    value = str(value or "").strip()
    if not value:
        raise ValueError("fecha UTC vacía")
    # La API devuelve actualmente YYYY-MM-DD HH:MM:SS con timezone=UTC.
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=UTC)


def parse_api_item(item: Any) -> ApiProgramme | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get("programm_name") or "").strip()
    if not title:
        return None
    try:
        start = parse_api_datetime(str(item.get("start_dt") or ""))
        end = parse_api_datetime(str(item.get("end_dt") or ""))
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    tz_name = str(item.get("timezone") or "UTC").strip().upper()
    if tz_name not in {"UTC", "GMT"}:
        # No reinterpretar silenciosamente un dato cuyo contrato haya cambiado.
        return None
    image = str(item.get("image_url") or "").strip() or None
    return ApiProgramme(start, end, title, image)


def parse_api_payload(payload: Any) -> list[ApiProgramme]:
    if not isinstance(payload, dict):
        raise RuntimeError("MakroDigital API no devolvió un objeto JSON.")
    raw_items: list[Any] = [payload.get("current_program"), payload.get("next_program")]
    future = payload.get("future_programs")
    if isinstance(future, list):
        raw_items.extend(future)
    parsed = [p for p in (parse_api_item(item) for item in raw_items) if p is not None]
    # Deduplicación estable por intervalo+título.
    unique: dict[tuple[datetime, datetime, str], ApiProgramme] = {}
    for item in parsed:
        unique[(item.start_utc, item.end_utc, item.title)] = item
    return sorted(unique.values())


def _request_payload(query_local: datetime) -> dict[str, str]:
    query_utc = query_local.astimezone(UTC)
    return {
        "channel": str(API_CHANNEL),
        "timeZone": OUTPUT_TIMEZONE,
        "nowUtc": query_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def fetch_api_at(session: requests.Session, query_local: datetime) -> list[ApiProgramme]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://makrodigitaltelevision.com",
        "Referer": WIDGET_URL,
        "User-Agent": UA,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    response = session.post(
        API_URL,
        json=_request_payload(query_local),
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("MakroDigital API devolvió una respuesta no JSON.") from exc
    return parse_api_payload(payload)


def _guide_window(base_date: date, days: int) -> tuple[datetime, datetime]:
    start = datetime.combine(base_date, time.min, tzinfo=EC_TZ)
    return start, start + timedelta(days=days)


def scrape_dynamic(base_date: date, days: int, *, pause_seconds: float = 0.15) -> tuple[list[ApiProgramme], dict[str, Any]]:
    start_local, end_local = _guide_window(base_date, days)
    session = requests.Session()
    collected: dict[tuple[datetime, datetime, str], ApiProgramme] = {}
    errors: list[str] = []
    queries = 0
    successful_queries = 0

    for offset in range(days):
        local_day = base_date + timedelta(days=offset)
        for hour in QUERY_LOCAL_HOURS:
            query_local = datetime.combine(local_day, time(hour, 5), tzinfo=EC_TZ)
            queries += 1
            try:
                programmes = fetch_api_at(session, query_local)
            except (requests.RequestException, RuntimeError) as exc:
                errors.append(f"{query_local.isoformat()}: {exc}")
                continue
            successful_queries += 1
            for item in programmes:
                # Conservamos también programas que crucen la frontera del día/ventana.
                if item.end_local <= start_local or item.start_local >= end_local:
                    continue
                collected[(item.start_utc, item.end_utc, item.title)] = item
            if pause_seconds:
                time_module.sleep(pause_seconds)

    programmes = sorted(collected.values())
    info = {
        "queries": queries,
        "successful_queries": successful_queries,
        "errors": errors[-20:],
    }
    return programmes, info


def _overlap_seconds(start: datetime, end: datetime, day_start: datetime, day_end: datetime) -> float:
    left = max(start, day_start)
    right = min(end, day_end)
    return max(0.0, (right - left).total_seconds())


def daily_dynamic_stats(programmes: Iterable[ApiProgramme], base_date: date, days: int) -> dict[str, dict[str, Any]]:
    programmes = list(programmes)
    stats: dict[str, dict[str, Any]] = {}
    for offset in range(days):
        d = base_date + timedelta(days=offset)
        day_start = datetime.combine(d, time.min, tzinfo=EC_TZ)
        day_end = day_start + timedelta(days=1)
        day_items = [p for p in programmes if p.end_local > day_start and p.start_local < day_end]
        # Unión de intervalos para no contar solapes dos veces.
        intervals = sorted((max(p.start_local, day_start), min(p.end_local, day_end)) for p in day_items)
        merged: list[list[datetime]] = []
        for s, e in intervals:
            if e <= s:
                continue
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            elif e > merged[-1][1]:
                merged[-1][1] = e
        seconds = sum((e - s).total_seconds() for s, e in merged)
        stats[d.isoformat()] = {
            "programmes": len(day_items),
            "coverage_hours": round(seconds / 3600.0, 2),
            "full_day": len(day_items) >= MIN_DYNAMIC_PROGRAMMES_PER_DAY and seconds >= FULL_DAY_COVERAGE_HOURS * 3600,
        }
    return stats


def parse_xmltv_datetime(value: str) -> datetime:
    # Formato del proyecto: YYYYMMDDHHMMSS -0500.
    return datetime.strptime(value, "%Y%m%d%H%M%S %z")


def programme_interval(node: etree._Element) -> tuple[datetime, datetime] | None:
    try:
        return parse_xmltv_datetime(node.get("start", "")), parse_xmltv_datetime(node.get("stop", ""))
    except ValueError:
        return None


def xmltv_stamp(dt: datetime) -> str:
    local = dt.astimezone(EC_TZ)
    return local.strftime("%Y%m%d%H%M%S %z")


def _make_programme(item: ApiProgramme) -> etree._Element:
    node = etree.Element(
        "programme",
        start=xmltv_stamp(item.start_utc),
        stop=xmltv_stamp(item.end_utc),
        channel=CHANNEL_ID,
    )
    title = etree.SubElement(node, "title", lang="es")
    title.text = item.title
    if item.image_url:
        etree.SubElement(node, "icon", src=item.image_url)
    return node


def merge_dynamic_into_tree(root: etree._Element, dynamic: list[ApiProgramme], base_date: date, days: int) -> dict[str, Any]:
    stats = daily_dynamic_stats(dynamic, base_date, days)
    existing = list(root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID))
    removed = 0

    full_days = {date.fromisoformat(k) for k, value in stats.items() if value["full_day"]}
    dynamic_intervals = [(p.start_local, p.end_local) for p in dynamic]

    for node in existing:
        interval = programme_interval(node)
        if interval is None:
            continue
        start, end = interval
        start = start.astimezone(EC_TZ)
        end = end.astimezone(EC_TZ)
        remove = False
        # Si la API cubre prácticamente el día completo, la fuente dinámica reemplaza
        # toda la parrilla semanal de ese día.
        for d in full_days:
            ds = datetime.combine(d, time.min, tzinfo=EC_TZ)
            de = ds + timedelta(days=1)
            if end > ds and start < de:
                remove = True
                break
        # Para días con cobertura parcial, solo se sustituyen los intervalos exactos
        # conocidos por la API, dejando la tabla semanal como relleno.
        if not remove:
            for ds, de in dynamic_intervals:
                if end > ds and start < de:
                    remove = True
                    break
        if remove:
            root.remove(node)
            removed += 1

    # Insertar programas en orden XMLTV después de todos los canales. Como el árbol
    # ya contiene programas, se ordenará la sección completa por hora/canal al final.
    for item in dynamic:
        root.append(_make_programme(item))

    programmes = list(root.findall("programme"))
    for node in programmes:
        root.remove(node)
    programmes.sort(key=lambda n: (n.get("start", ""), n.get("channel", ""), n.get("stop", "")))
    root.extend(programmes)

    final_nodes = root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID)
    return {
        "removed_weekly_programmes": removed,
        "inserted_dynamic_programmes": len(dynamic),
        "final_programmes": len(final_nodes),
        "daily": stats,
        "full_dynamic_dates": sorted(d.isoformat() for d in full_days),
    }


def _read_base_date(status: dict[str, Any]) -> date:
    value = status.get("base_date")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(EC_TZ).date()


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
    with gzip.open(gz_path, "wb") as fh:
        fh.write(data)


def update_status(status_path: Path, *, source_info: dict[str, Any], merge_info: dict[str, Any]) -> None:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["version"] = repository_version()
    counts = status.setdefault("programme_counts", {})
    counts[CHANNEL_ID] = int(merge_info["final_programmes"])
    status["makrodigital"] = {
        "channel_id": CHANNEL_ID,
        "api_channel": API_CHANNEL,
        "source": API_URL,
        "widget": WIDGET_URL,
        "weekly_fallback": WEEKLY_URL,
        "source_timezone": SOURCE_TIMEZONE,
        "target_timezone": OUTPUT_TIMEZONE,
        "query_timezone": OUTPUT_TIMEZONE,
        "manual_offset_minutes": MANUAL_OFFSET_MINUTES,
        "mode": "official-dynamic-api-primary+weekly-fallback",
        "query_hours_local": list(QUERY_LOCAL_HOURS),
        "queries": int(source_info.get("queries", 0)),
        "successful_queries": int(source_info.get("successful_queries", 0)),
        "api_errors": list(source_info.get("errors", [])),
        "dynamic_programmes": int(merge_info["inserted_dynamic_programmes"]),
        "weekly_programmes_replaced": int(merge_info["removed_weekly_programmes"]),
        "programmes": int(merge_info["final_programmes"]),
        "daily": merge_info["daily"],
        "full_dynamic_dates": merge_info["full_dynamic_dates"],
    }
    sources = status.setdefault("sources", {})
    sources["makrodigital_dynamic_api"] = API_URL
    sources["makrodigital_weekly_fallback"] = WEEKLY_URL
    # Mantener la clave histórica, pero apuntándola a la fuente primaria efectiva.
    sources["makrodigital_official"] = API_URL
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply(output_dir: Path, days: int) -> dict[str, Any]:
    xml_path = output_dir / "latam.xml"
    gz_path = output_dir / "latam.xml.gz"
    status_path = output_dir / "latam-status.json"
    if not xml_path.is_file() or not status_path.is_file():
        raise RuntimeError("MakroDigital v0.2.66 requiere latam.xml y latam-status.json existentes.")

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=True)
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    channels = root.xpath("./channel[@id=$channel_id]", channel_id=CHANNEL_ID)
    if len(channels) != 1:
        raise RuntimeError(f"Se esperaba exactamente un canal {CHANNEL_ID}; encontrados={len(channels)}")

    status = json.loads(status_path.read_text(encoding="utf-8"))
    base_date = _read_base_date(status)
    dynamic, source_info = scrape_dynamic(base_date, days)

    if dynamic:
        merge_info = merge_dynamic_into_tree(root, dynamic, base_date, days)
    else:
        # No abortar: la parrilla semanal ya presente sigue siendo fallback oficial.
        final_nodes = root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID)
        if len(final_nodes) < MIN_DYNAMIC_PROGRAMMES_PER_DAY:
            raise RuntimeError(
                "MakroDigital: la API dinámica falló y la parrilla semanal existente "
                f"solo contiene {len(final_nodes)} emisiones."
            )
        merge_info = {
            "removed_weekly_programmes": 0,
            "inserted_dynamic_programmes": 0,
            "final_programmes": len(final_nodes),
            "daily": daily_dynamic_stats([], base_date, days),
            "full_dynamic_dates": [],
        }

    _write_xml(tree, xml_path, gz_path)
    update_status(status_path, source_info=source_info, merge_info=merge_info)
    return {"source": source_info, "merge": merge_info, "base_date": base_date.isoformat()}


def self_test() -> None:
    fixture = {
        "current_program": {
            "programm_name": "Vis a Vis con Janet Hinostroza",
            "image_url": "https://makrodigitaltelevision.com/admin/img/test.jpg",
            "channel_id": 14,
            "timezone": "UTC",
            "start_dt": "2026-09-16 14:00:00",
            "end_dt": "2026-09-16 15:45:00",
        },
        "next_program": {
            "programm_name": "Videoteka Musical",
            "channel_id": 14,
            "timezone": "UTC",
            "start_dt": "2026-09-16 15:45:00",
            "end_dt": "2026-09-16 16:30:00",
        },
        "future_programs": [
            {
                "programm_name": "El Súper Libro",
                "channel_id": 14,
                "timezone": "UTC",
                "start_dt": "2026-09-16 16:30:00",
                "end_dt": "2026-09-16 17:00:00",
            },
            {
                "programm_name": "MakroNoticias",
                "channel_id": 14,
                "timezone": "UTC",
                "start_dt": "2026-09-16 18:00:00",
                "end_dt": "2026-09-16 18:30:00",
            },
        ],
    }
    parsed = parse_api_payload(fixture)
    assert len(parsed) == 4, parsed
    vis = parsed[0]
    assert vis.title == "Vis a Vis con Janet Hinostroza"
    assert vis.start_local.strftime("%Y-%m-%d %H:%M") == "2026-09-16 09:00", vis.start_local
    assert vis.end_local.strftime("%Y-%m-%d %H:%M") == "2026-09-16 10:45", vis.end_local
    makro = next(item for item in parsed if item.title == "MakroNoticias")
    assert makro.start_local.strftime("%H:%M") == "13:00", makro.start_local
    payload = _request_payload(datetime(2026, 9, 16, 10, 32, 37, tzinfo=EC_TZ))
    assert payload["channel"] == "14"
    assert payload["timeZone"] == "America/Guayaquil"
    assert payload["nowUtc"].startswith("2026-09-16T15:32:37"), payload

    root = etree.Element("tv")
    etree.SubElement(root, "channel", id=CHANNEL_ID)
    # Parrilla semanal falsa que se solapa con el dato dinámico.
    old = etree.SubElement(
        root, "programme",
        start="20260916080000 -0500", stop="20260916100000 -0500", channel=CHANNEL_ID,
    )
    etree.SubElement(old, "title", lang="es").text = "Vis a Vis viejo"
    merge = merge_dynamic_into_tree(root, parsed, date(2026, 9, 16), 1)
    titles = [n.findtext("title") for n in root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID)]
    assert "Vis a Vis viejo" not in titles, titles
    assert "Vis a Vis con Janet Hinostroza" in titles, titles
    assert merge["inserted_dynamic_programmes"] == 4, merge
    print(
        "Prueba v0.2.66 correcta: API dinámica MakroDigital canal 14; "
        "start_dt/end_dt UTC -> America/Guayaquil; overlay sobre parrilla semanal; offset manual=0."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="public")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.days < 1:
        raise SystemExit("--days debe ser >= 1")
    result = apply(Path(args.output), args.days)
    merge = result["merge"]
    print(
        f"MakroDigital v0.2.66: API dinámica={merge['inserted_dynamic_programmes']} emisiones; "
        f"semanales reemplazadas={merge['removed_weekly_programmes']}; "
        f"finales={merge['final_programmes']}; fechas completas={merge['full_dynamic_dates']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

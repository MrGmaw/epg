#!/usr/bin/env python3
"""Añade NBC 6 Miami (WTVJ) y ABC Miami 18 (WSVN-DT2) a latam.xml.

Fuente primaria: EPGShare US_LOCALS1. El XMLTV de origen conserva instantes con
su offset; se convierten explícitamente a ``America/Guayaquil``. Si una marca de
tiempo viniera sin offset, se interpreta como ``America/New_York`` para respetar
el horario legal de Miami (EST/EDT) sin aplicar offsets manuales.

La integración ocurre *después* de construir la guía LATAM base. De esta forma
los 30 canales base existentes y sus scrapers permanecen intactos.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Iterable
from zoneinfo import ZoneInfo

import requests
from lxml import etree

SOURCE_URL = "https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS1.xml.gz"
SOURCE_NAME = "EPGShare US_LOCALS1"
SOURCE_FALLBACK_TIMEZONE = ZoneInfo("America/New_York")
OUTPUT_TIMEZONE = ZoneInfo("America/Guayaquil")
EXPECTED_BASE_CHANNELS = 30
EXPECTED_FINAL_CHANNELS = 32
MIN_PROGRAMMES_PER_CHANNEL = 5


@dataclass(frozen=True)
class MiamiChannel:
    source_id: str
    target_id: str
    display_name: str
    station: str
    network: str
    website: str


MIAMI_CHANNELS: tuple[MiamiChannel, ...] = (
    MiamiChannel(
        source_id="WTVJ-DT.us_locals1",
        target_id="NBC6-Miami.us",
        display_name="NBC 6 Miami",
        station="WTVJ",
        network="NBC",
        website="https://www.nbcmiami.com/tv-schedule/",
    ),
    MiamiChannel(
        source_id="WSVN-DT2.us_locals1",
        target_id="ABC-Miami.us",
        display_name="ABC Miami 18",
        station="WSVN-DT2",
        network="ABC",
        website="https://wsvn.com/abc-miami-18/",
    ),
)
TARGET_IDS: tuple[str, ...] = tuple(item.target_id for item in MIAMI_CHANNELS)
SOURCE_IDS: tuple[str, ...] = tuple(item.source_id for item in MIAMI_CHANNELS)
SOURCE_TO_CONFIG = {item.source_id: item for item in MIAMI_CHANNELS}
TARGET_TO_CONFIG = {item.target_id: item for item in MIAMI_CHANNELS}

_XMLTV_TS = re.compile(
    r"^\s*(?P<digits>\d{8}(?:\d{4}(?:\d{2})?)?)(?:\s+(?P<offset>[+-]\d{4}|Z))?\s*$"
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--previous-latam-xml", type=Path)
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def _parse_xmltv_timestamp(value: str, *, fallback_tz: ZoneInfo = SOURCE_FALLBACK_TIMEZONE) -> datetime:
    match = _XMLTV_TS.match(value or "")
    if not match:
        raise ValueError(f"Marca XMLTV no soportada: {value!r}")

    digits = match.group("digits")
    fmt = {8: "%Y%m%d", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}.get(len(digits))
    if fmt is None:
        raise ValueError(f"Precisión XMLTV no soportada: {value!r}")

    naive = datetime.strptime(digits, fmt)
    offset = match.group("offset")
    if offset == "Z":
        aware = naive.replace(tzinfo=ZoneInfo("UTC"))
    elif offset:
        aware = datetime.strptime(f"{digits} {offset}", f"{fmt} %z")
    else:
        # Solo respaldo: EPGShare normalmente incluye offset. Nunca se suma/resta
        # una hora fija; ZoneInfo decide EST/EDT según la fecha concreta.
        aware = naive.replace(tzinfo=fallback_tz)
    return aware


def _format_guayaquil(value: str) -> str:
    dt = _parse_xmltv_timestamp(value).astimezone(OUTPUT_TIMEZONE)
    return dt.strftime("%Y%m%d%H%M%S %z")


def _copy_text_children(source: etree._Element, target: etree._Element, tag: str) -> None:
    allowed_attrs = {
        "title": {"lang"},
        "sub-title": {"lang"},
        "desc": {"lang"},
        "category": {"lang"},
        "episode-num": {"system"},
    }.get(tag, set())
    for child in source.findall(tag):
        if child.text is None or not child.text.strip():
            continue
        cloned = etree.SubElement(target, tag)
        for name in allowed_attrs:
            value = child.get(name)
            if value:
                cloned.set(name, value)
        cloned.text = child.text


def _normalise_programme(node: etree._Element, config: MiamiChannel) -> etree._Element:
    """Reconstruye un programme XMLTV mínimo y DTD-seguro.

    EPGShare suele entregar XMLTV estándar, pero reconstruir los campos útiles
    evita que un elemento no estándar o fuera de orden del proveedor rompa la
    validación estricta del repositorio.
    """
    start_raw = node.get("start", "")
    stop_raw = node.get("stop", "")
    if not start_raw or not stop_raw:
        raise ValueError(f"Programa sin start/stop completo para {config.source_id}.")

    result = etree.Element(
        "programme",
        start=_format_guayaquil(start_raw),
        stop=_format_guayaquil(stop_raw),
        channel=config.target_id,
    )
    for attr in ("pdc-start", "vps-start"):
        raw = node.get(attr)
        if raw:
            try:
                result.set(attr, _format_guayaquil(raw))
            except ValueError:
                # Son atributos opcionales; una marca no estándar del proveedor
                # no debe invalidar una emisión cuyo start/stop sí son correctos.
                pass

    # Orden según xmltv.dtd: title, sub-title, desc, ... category, ... icon,
    # ... episode-num, ... rating. Conservamos solo metadatos útiles y simples.
    _copy_text_children(node, result, "title")
    if not result.findall("title"):
        etree.SubElement(result, "title", lang="en").text = "Programming unavailable"
    _copy_text_children(node, result, "sub-title")
    _copy_text_children(node, result, "desc")
    _copy_text_children(node, result, "category")

    for child in node.findall("icon"):
        src = (child.get("src") or "").strip()
        if not src:
            continue
        icon = etree.SubElement(result, "icon", src=src)
        for attr in ("width", "height"):
            value = child.get(attr)
            if value:
                icon.set(attr, value)

    _copy_text_children(node, result, "episode-num")

    for child in node.findall("rating"):
        value_node = child.find("value")
        if value_node is None or value_node.text is None or not value_node.text.strip():
            continue
        rating = etree.SubElement(result, "rating")
        if child.get("system"):
            rating.set("system", child.get("system"))
        etree.SubElement(rating, "value").text = value_node.text

    return result


def _make_channel(source_node: etree._Element | None, config: MiamiChannel) -> etree._Element:
    channel = etree.Element("channel", id=config.target_id)
    etree.SubElement(channel, "display-name", lang="es").text = config.display_name
    etree.SubElement(channel, "display-name", lang="es").text = config.station
    etree.SubElement(channel, "display-name", lang="es").text = f"{config.network} Miami"

    if source_node is not None:
        # Conservamos iconos válidos del origen. El DTD exige icon antes de url.
        for child in source_node.findall("icon"):
            src = (child.get("src") or "").strip()
            if not src:
                continue
            icon = etree.SubElement(channel, "icon", src=src)
            for attr in ("width", "height"):
                value = child.get(attr)
                if value:
                    icon.set(attr, value)

    etree.SubElement(channel, "url").text = config.website
    return channel


def _extract_from_stream(
    stream: BinaryIO,
    *,
    start_date: date,
    days: int,
) -> tuple[dict[str, etree._Element], dict[str, list[etree._Element]]]:
    if days < 1:
        raise ValueError("--days debe ser >= 1")
    end_date = start_date + timedelta(days=days)
    window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=OUTPUT_TIMEZONE)
    window_end = datetime.combine(end_date, datetime.min.time(), tzinfo=OUTPUT_TIMEZONE)
    channels: dict[str, etree._Element] = {}
    programmes: dict[str, list[etree._Element]] = {source_id: [] for source_id in SOURCE_IDS}

    context = etree.iterparse(
        stream,
        events=("end",),
        tag=("channel", "programme"),
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    for _, elem in context:
        if elem.tag == "channel":
            source_id = elem.get("id", "")
            if source_id in SOURCE_TO_CONFIG:
                channels[source_id] = copy.deepcopy(elem)
        else:
            source_id = elem.get("channel", "")
            if source_id in SOURCE_TO_CONFIG:
                start_raw = elem.get("start", "")
                stop_raw = elem.get("stop", "")
                if start_raw and stop_raw:
                    try:
                        local_start = _parse_xmltv_timestamp(start_raw).astimezone(OUTPUT_TIMEZONE)
                        local_stop = _parse_xmltv_timestamp(stop_raw).astimezone(OUTPUT_TIMEZONE)
                    except ValueError:
                        local_start = local_stop = None
                    if (
                        local_start is not None
                        and local_stop is not None
                        and local_start < window_end
                        and local_stop > window_start
                        and local_stop > local_start
                    ):
                        programmes[source_id].append(
                            _normalise_programme(elem, SOURCE_TO_CONFIG[source_id])
                        )

        elem.clear()
        parent = elem.getparent()
        if parent is not None:
            while elem.getprevious() is not None:
                del parent[0]

    missing_channels = [source_id for source_id in SOURCE_IDS if source_id not in channels]
    if missing_channels:
        raise RuntimeError(
            "EPGShare no contiene los canales esperados: " + ", ".join(missing_channels)
        )
    for source_id, items in programmes.items():
        if len(items) < MIN_PROGRAMMES_PER_CHANNEL:
            raise RuntimeError(
                f"EPGShare devolvió programación insuficiente para {source_id}: "
                f"{len(items)} emisiones en la ventana {start_date}..{end_date - timedelta(days=1)}."
            )
    return channels, programmes


def _download_extract(
    url: str,
    *,
    start_date: date,
    days: int,
    attempts: int = 3,
) -> tuple[dict[str, etree._Element], dict[str, list[etree._Element]]]:
    headers = {
        "User-Agent": "EPG-MrG/0.2.38 (+GitHub Actions; XMLTV)",
        "Accept": "application/gzip, application/octet-stream, */*",
    }
    errors: list[str] = []

    for attempt in range(1, attempts + 1):
        response: requests.Response | None = None
        try:
            response = requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=(20, 180),
            )
            response.raise_for_status()
            response.raw.decode_content = False
            with gzip.GzipFile(fileobj=response.raw, mode="rb") as xml_stream:
                result = _extract_from_stream(xml_stream, start_date=start_date, days=days)
            print(
                f"EPGShare Miami: descarga/extracción correcta en intento {attempt}; "
                f"fuente={url}",
                flush=True,
            )
            return result
        except (OSError, ValueError, RuntimeError, requests.RequestException, etree.XMLSyntaxError) as exc:
            errors.append(f"intento {attempt}: {exc}")
            if attempt < attempts:
                print(
                    f"ADVERTENCIA: EPGShare Miami falló ({exc}); reintento {attempt + 1}/{attempts}.",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(min(5 * attempt, 15))
        finally:
            if response is not None:
                response.close()

    raise RuntimeError("No se pudo obtener EPGShare US_LOCALS1: " + " | ".join(errors))


def _extract_previous(
    previous_xml: Path,
    *,
    start_date: date,
    days: int,
) -> tuple[dict[str, etree._Element], dict[str, list[etree._Element]]]:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    root = etree.parse(str(previous_xml), parser).getroot()
    end_date = start_date + timedelta(days=days)
    window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=OUTPUT_TIMEZONE)
    window_end = datetime.combine(end_date, datetime.min.time(), tzinfo=OUTPUT_TIMEZONE)
    channels: dict[str, etree._Element] = {}
    programmes_by_target: dict[str, list[etree._Element]] = {target_id: [] for target_id in TARGET_IDS}

    for config in MIAMI_CHANNELS:
        nodes = root.xpath("./channel[@id=$cid]", cid=config.target_id)
        if nodes:
            channels[config.source_id] = copy.deepcopy(nodes[0])
        for programme in root.xpath("./programme[@channel=$cid]", cid=config.target_id):
            start_raw = programme.get("start", "")
            stop_raw = programme.get("stop", "")
            if not start_raw or not stop_raw:
                continue
            try:
                local_start = _parse_xmltv_timestamp(start_raw).astimezone(OUTPUT_TIMEZONE)
                local_stop = _parse_xmltv_timestamp(stop_raw).astimezone(OUTPUT_TIMEZONE)
            except ValueError:
                continue
            if not (local_start < window_end and local_stop > window_start and local_stop > local_start):
                continue
            item = _normalise_programme(programme, config)
            programmes_by_target[config.target_id].append(item)

    missing = [config.target_id for config in MIAMI_CHANNELS if config.source_id not in channels]
    if missing:
        raise RuntimeError("La guía previa no contiene: " + ", ".join(missing))

    result: dict[str, list[etree._Element]] = {}
    for config in MIAMI_CHANNELS:
        items = programmes_by_target[config.target_id]
        if len(items) < MIN_PROGRAMMES_PER_CHANNEL:
            raise RuntimeError(
                f"La guía previa no tiene programación vigente suficiente para {config.target_id}: "
                f"{len(items)} emisiones."
            )
        # El contrato interno usa las claves source_id aunque los nodos ya tengan target_id.
        result[config.source_id] = items
    return channels, result


def _remove_existing(root: etree._Element) -> None:
    for target_id in TARGET_IDS:
        for node in root.xpath("./channel[@id=$cid]", cid=target_id):
            root.remove(node)
        for node in root.xpath("./programme[@channel=$cid]", cid=target_id):
            root.remove(node)


EXPECTED_HEADER = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n'
)


def _write_xml_and_gzip(tree: etree._ElementTree, xml_path: Path, gz_path: Path) -> None:
    # validate_outputs.py exige exactamente esta cabecera (incluida la línea
    # vacía después del DOCTYPE), así que no delegamos esa parte a lxml.
    body = etree.tostring(
        tree.getroot(),
        encoding="UTF-8",
        xml_declaration=False,
        pretty_print=True,
    )
    data = EXPECTED_HEADER + body
    xml_path.write_bytes(data)
    with gz_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(data)


def _update_index_html(output_dir: Path) -> None:
    path = output_dir / "index.html"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    updated = re.sub(r"\b(?:28|30)\s+canales\b", "32 canales", text, flags=re.IGNORECASE)
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline="\n")


def _update_status(
    status_path: Path,
    *,
    programmes: dict[str, list[etree._Element]],
    source_url: str,
    source_mode: str,
    start_date: date,
    days: int,
    primary_error: str | None,
) -> None:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if not isinstance(status, dict):
        raise RuntimeError("latam-status.json debe contener un objeto JSON en la raíz.")

    # Compatibilidad con distintas revisiones del generador base. Algunas
    # versiones heredadas serializan metadatos auxiliares como texto en vez de
    # objetos. No intentamos modificar esos strings: normalizamos únicamente
    # los contenedores que esta capa necesita ampliar.
    counts = status.get("programme_counts")
    if not isinstance(counts, dict):
        counts = {}
        status["programme_counts"] = counts

    sources = status.get("sources")
    if not isinstance(sources, dict):
        # Conservamos el valor heredado para diagnóstico sin romper el esquema
        # nuevo que necesita un diccionario de proveedores.
        if sources not in (None, ""):
            status["legacy_sources"] = sources
        sources = {}
        status["sources"] = sources

    # `sources.epgshare` pertenece al generador base y es históricamente una
    # URL de texto. Se conserva intacto. Los canales Miami usan una clave
    # separada para evitar colisiones de esquema.
    epgshare_sources = sources.get("epgshare_miami")
    if not isinstance(epgshare_sources, dict):
        if epgshare_sources not in (None, ""):
            sources["epgshare_miami_legacy"] = epgshare_sources
        epgshare_sources = {}
        sources["epgshare_miami"] = epgshare_sources

    details: dict[str, object] = {}
    for config in MIAMI_CHANNELS:
        items = programmes[config.source_id]
        counts[config.target_id] = len(items)
        epgshare_sources[config.target_id] = source_url
        details[config.target_id] = {
            "display_name": config.display_name,
            "station": config.station,
            "network": config.network,
            "website": config.website,
            "source_channel_id": config.source_id,
            "source": source_url,
            "source_mode": source_mode,
            "source_timezone_policy": "XMLTV offset; America/New_York fallback",
            "output_timezone": "America/Guayaquil",
            "manual_offset_minutes": 0,
            "programmes": len(items),
            "window_start": start_date.isoformat(),
            "window_days": days,
        }

    status["channels"] = EXPECTED_FINAL_CHANNELS
    status["miami_epg"] = {
        "provider": SOURCE_NAME,
        "source": source_url,
        "source_mode": source_mode,
        "output_timezone": "America/Guayaquil",
        "manual_offset_minutes": 0,
        "primary_error": primary_error,
        "channels": details,
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _assert_final(output_dir: Path) -> None:
    xml_path = output_dir / "latam.xml"
    status_path = output_dir / "latam-status.json"
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    root = etree.parse(str(xml_path), parser).getroot()
    ids = [node.get("id", "") for node in root.findall("channel")]
    if len(ids) != EXPECTED_FINAL_CHANNELS or len(set(ids)) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError(
            f"latam.xml debe quedar con {EXPECTED_FINAL_CHANNELS} canales únicos; "
            f"obtenidos={len(ids)}."
        )
    if tuple(ids[-len(TARGET_IDS):]) != TARGET_IDS:
        raise RuntimeError(f"Los canales Miami no quedaron al final en orden {TARGET_IDS!r}.")

    for target_id in TARGET_IDS:
        programmes = root.xpath("./programme[@channel=$cid]", cid=target_id)
        if len(programmes) < MIN_PROGRAMMES_PER_CHANNEL:
            raise RuntimeError(f"Programación insuficiente para {target_id}: {len(programmes)}.")
        for node in programmes:
            if not node.get("start", "").endswith(" -0500"):
                raise RuntimeError(f"start fuera de America/Guayaquil en {target_id}: {node.get('start')}")
            if not node.get("stop", "").endswith(" -0500"):
                raise RuntimeError(f"stop fuera de America/Guayaquil en {target_id}: {node.get('stop')}")

    status = json.loads(status_path.read_text(encoding="utf-8"))
    if int(status.get("channels", 0)) != EXPECTED_FINAL_CHANNELS:
        raise RuntimeError("latam-status.json no informa 32 canales.")
    policy = status.get("miami_epg", {})
    if policy.get("output_timezone") != "America/Guayaquil":
        raise RuntimeError(f"Política Miami inválida: {policy!r}")
    if int(policy.get("manual_offset_minutes", -999)) != 0:
        raise RuntimeError(f"Miami no debe usar offset manual: {policy!r}")

    with gzip.open(output_dir / "latam.xml.gz", "rb") as fh:
        if fh.read() != xml_path.read_bytes():
            raise RuntimeError("latam.xml.gz no corresponde byte a byte a latam.xml.")


def integrate(
    *,
    output_dir: Path,
    days: int,
    source_url: str,
    previous_latam_xml: Path | None,
    start_date: date,
) -> None:
    xml_path = output_dir / "latam.xml"
    gz_path = output_dir / "latam.xml.gz"
    status_path = output_dir / "latam-status.json"
    for required in (xml_path, status_path):
        if not required.is_file() or required.stat().st_size == 0:
            raise FileNotFoundError(required)

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    base_ids = [node.get("id", "") for node in root.findall("channel") if node.get("id") not in TARGET_IDS]
    if len(base_ids) != EXPECTED_BASE_CHANNELS or len(set(base_ids)) != EXPECTED_BASE_CHANNELS:
        raise RuntimeError(
            f"Se esperaban {EXPECTED_BASE_CHANNELS} canales base antes de Miami; "
            f"obtenidos={len(base_ids)}."
        )

    primary_error: str | None = None
    try:
        source_channels, programmes = _download_extract(
            source_url,
            start_date=start_date,
            days=days,
        )
        source_mode = "epgshare-live"
        effective_source = source_url
    except RuntimeError as exc:
        primary_error = str(exc)
        if previous_latam_xml is None or not previous_latam_xml.is_file():
            raise
        print(
            "ADVERTENCIA: EPGShare Miami no quedó utilizable; se probará la guía previa "
            f"{previous_latam_xml}.",
            file=sys.stderr,
            flush=True,
        )
        source_channels, programmes = _extract_previous(
            previous_latam_xml,
            start_date=start_date,
            days=days,
        )
        source_mode = "previous-latam-fallback"
        effective_source = str(previous_latam_xml)

    _remove_existing(root)
    # Todos los canales deben preceder a todos los programme según XMLTV DTD.
    first_programme = root.find("programme")
    insert_at = len(root) if first_programme is None else root.index(first_programme)
    for config in MIAMI_CHANNELS:
        source_node = source_channels.get(config.source_id)
        # En fallback la fuente ya puede ser nuestro nodo final; aun así recreamos
        # nombres canónicos y conservamos icon/url.
        channel = _make_channel(source_node, config)
        root.insert(insert_at, channel)
        insert_at += 1

    for config in MIAMI_CHANNELS:
        items = programmes[config.source_id]
        items.sort(key=lambda node: node.get("start", ""))
        for item in items:
            # Fallback previo ya tiene target_id; origen vivo se normalizó antes.
            item.set("channel", config.target_id)
            root.append(item)
        print(
            f"Miami: {config.display_name} ({config.target_id}) = {len(items)} emisiones; "
            f"modo={source_mode}.",
            flush=True,
        )

    _write_xml_and_gzip(tree, xml_path, gz_path)
    _update_status(
        status_path,
        programmes=programmes,
        source_url=effective_source,
        source_mode=source_mode,
        start_date=start_date,
        days=days,
        primary_error=primary_error,
    )
    _update_index_html(output_dir)
    _assert_final(output_dir)


def self_test() -> None:
    # Verifica DST sin offsets manuales.
    assert _format_guayaquil("20260827200000 -0400") == "20260827190000 -0500"
    assert _format_guayaquil("20261201200000 -0500") == "20261201200000 -0500"
    assert _format_guayaquil("20260827200000") == "20260827190000 -0500"
    assert _format_guayaquil("20261201200000") == "20261201200000 -0500"

    start = date(2026, 8, 27)
    source_root = etree.Element("tv")
    for config in MIAMI_CHANNELS:
        channel = etree.SubElement(source_root, "channel", id=config.source_id)
        etree.SubElement(channel, "display-name").text = config.station
        etree.SubElement(channel, "icon", src=f"https://example.invalid/{config.station}.png")
        for hour in range(6):
            programme = etree.SubElement(
                source_root,
                "programme",
                channel=config.source_id,
                start=f"20260827{12 + hour:02d}0000 -0400",
                stop=f"20260827{13 + hour:02d}0000 -0400",
            )
            etree.SubElement(programme, "title", lang="en").text = f"Programa {hour + 1}"

    source_bytes = etree.tostring(source_root, xml_declaration=True, encoding="UTF-8")
    channels, programmes = _extract_from_stream(
        io.BytesIO(source_bytes), start_date=start, days=7
    )
    assert set(channels) == set(SOURCE_IDS)
    assert all(len(programmes[source_id]) == 6 for source_id in SOURCE_IDS)
    assert programmes[SOURCE_IDS[0]][0].get("start") == "20260827110000 -0500"
    assert programmes[SOURCE_IDS[1]][0].get("channel") == "ABC-Miami.us"

    # Prueba de mezcla final, status y gzip sin red.
    with tempfile.TemporaryDirectory() as temp_name:
        out = Path(temp_name)
        base_root = etree.Element("tv")
        for idx in range(EXPECTED_BASE_CHANNELS):
            etree.SubElement(base_root, "channel", id=f"base-{idx:02d}")
        base_tree = etree.ElementTree(base_root)
        _write_xml_and_gzip(base_tree, out / "latam.xml", out / "latam.xml.gz")
        (out / "latam-status.json").write_text(
            json.dumps({"channels": EXPECTED_BASE_CHANNELS, "programme_counts": {}, "sources": {}}),
            encoding="utf-8",
        )

        tree = etree.parse(str(out / "latam.xml"), etree.XMLParser(load_dtd=False, no_network=True))
        root = tree.getroot()
        for config in MIAMI_CHANNELS:
            root.append(_make_channel(channels[config.source_id], config))
        for config in MIAMI_CHANNELS:
            for item in programmes[config.source_id]:
                root.append(copy.deepcopy(item))
        _write_xml_and_gzip(tree, out / "latam.xml", out / "latam.xml.gz")
        _update_status(
            out / "latam-status.json",
            programmes=programmes,
            source_url=SOURCE_URL,
            source_mode="self-test",
            start_date=start,
            days=7,
            primary_error=None,
        )
        _assert_final(out)

    # Regresión heredada de v0.2.37: tolera estados donde campos auxiliares
    # llegan como strings (causa del TypeError de v0.2.36).
    legacy_shapes = (
        {"channels": EXPECTED_BASE_CHANNELS, "programme_counts": "legacy", "sources": {}},
        {"channels": EXPECTED_BASE_CHANNELS, "programme_counts": {}, "sources": "legacy"},
        {
            "channels": EXPECTED_BASE_CHANNELS,
            "programme_counts": {},
            "sources": {"epgshare": "legacy"},
        },
    )
    for legacy_status in legacy_shapes:
        with tempfile.TemporaryDirectory() as temp_name:
            status_path = Path(temp_name) / "latam-status.json"
            status_path.write_text(json.dumps(legacy_status), encoding="utf-8")
            _update_status(
                status_path,
                programmes=programmes,
                source_url=SOURCE_URL,
                source_mode="self-test-legacy",
                start_date=start,
                days=7,
                primary_error=None,
            )
            repaired = json.loads(status_path.read_text(encoding="utf-8"))
            assert isinstance(repaired["programme_counts"], dict)
            assert isinstance(repaired["sources"], dict)
            assert isinstance(repaired["sources"]["epgshare_miami"], dict)
            if isinstance(legacy_status.get("sources"), dict) and "epgshare" in legacy_status["sources"]:
                assert repaired["sources"]["epgshare"] == legacy_status["sources"]["epgshare"]
            assert repaired["programme_counts"]["NBC6-Miami.us"] == 6
            assert repaired["programme_counts"]["ABC-Miami.us"] == 6

    print(
        "Prueba v0.2.38 Miami correcta: base 30 + WTVJ/NBC 6 + WSVN-DT2/ABC Miami; "
        "DST America/New_York -> America/Guayaquil; offset manual=0.",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.self_test:
        self_test()
        return 0
    start_date = args.start_date or datetime.now(OUTPUT_TIMEZONE).date()
    integrate(
        output_dir=args.output,
        days=args.days,
        source_url=args.source_url,
        previous_latam_xml=args.previous_latam_xml,
        start_date=start_date,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        requests.RequestException,
        etree.XMLSyntaxError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

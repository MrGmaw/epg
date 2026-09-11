#!/usr/bin/env python3
"""EPG MrG v0.2.59: añade El Gourmet Sur desde mi.tv Argentina.

Fuente de programación:
    https://mi.tv/ar/canales/el-gourmet

Canal XMLTV:
    Canal.Elgourmet.ar

La parrilla se obtiene mediante el scraper compartido ``mitv_utc`` del proyecto,
que interpreta el endpoint asíncrono de mi.tv como UTC y lo convierte a
``America/Guayaquil``. No se aplican offsets manuales.

El logo se obtiene con el sistema persistente de logos mi.tv. Si el portal no
entrega un recurso nuevo, se reutiliza como último recurso el logo local de
El Gourmet Ecuador, que corresponde a la misma marca gráfica.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

from lxml import etree

import build_epg_base as epg
import mitv_logos
import mitv_utc

VERSION = "0.2.59"
CHANNEL_ID = "Canal.Elgourmet.ar"
TARGET_IDS = (CHANNEL_ID,)
DISPLAY_NAMES = ("El Gourmet Sur", "El Gourmet")
COUNTRY = "ar"
SLUG = "el-gourmet"
SOURCE_URL = "https://mi.tv/ar/canales/el-gourmet"
SOURCE_TIMEZONE = "UTC"
OUTPUT_TIMEZONE = "America/Guayaquil"
MANUAL_OFFSET_MINUTES = 0
EXPECTED_INPUT_CHANNELS = 36
EXPECTED_FINAL_CHANNELS = 37
MIN_PROGRAMMES = 5
LOCAL_DAYS = 2
LOGO_FALLBACK_CHANNEL_ID = "Canal.Elgourmet.ec"
HEADER = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n'
)


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"ADVERTENCIA: {message}", file=sys.stderr, flush=True)


def _repo_version() -> str:
    path = Path("VERSION")
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return VERSION


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )


def _write_xml_and_gzip(root: etree._Element, xml_path: Path, gz_path: Path) -> None:
    payload = etree.tostring(root, encoding="UTF-8", xml_declaration=False, pretty_print=True)
    xml_bytes = HEADER + payload
    xml_path.write_bytes(xml_bytes)
    with gz_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(xml_bytes)
    if gzip.decompress(gz_path.read_bytes()) != xml_bytes:
        raise RuntimeError(f"{gz_path} no corresponde byte a byte a {xml_path}.")


def _insert_channel_before_programmes(root: etree._Element, channel: etree._Element) -> None:
    children = list(root)
    insert_at = len(children)
    for index, child in enumerate(children):
        if child.tag == "programme":
            insert_at = index
            break
    root.insert(insert_at, channel)


def _programme_node(programme: object) -> etree._Element:
    node = etree.Element(
        "programme",
        start=epg.format_xmltv_datetime(programme.start),
        stop=epg.format_xmltv_datetime(programme.stop),
        channel=CHANNEL_ID,
    )
    title = etree.SubElement(node, "title", lang="es")
    title.text = str(programme.title)
    description = getattr(programme, "description", None)
    if description:
        desc = etree.SubElement(node, "desc", lang="es")
        desc.text = str(description)
    return node


def _refresh_logo(output_dir: Path, manifest_path: Path) -> tuple[str, dict[str, object]]:
    logos_dir = output_dir / "logos"
    logos_dir.mkdir(parents=True, exist_ok=True)
    target = mitv_logos.LogoTarget(
        COUNTRY,
        SLUG,
        CHANNEL_ID,
        ("ar_el-gourmet", "ar_el_gourmet"),
    )
    record = mitv_logos.refresh_target(target, logos_dir)
    output_path = logos_dir / f"{CHANNEL_ID}.png"

    # Respaldo gráfico: misma marca El Gourmet ya cacheada para la señal EC.
    if not record.get("available"):
        fallback = logos_dir / f"{LOGO_FALLBACK_CHANNEL_ID}.png"
        if fallback.is_file() and fallback.stat().st_size > 0:
            shutil.copyfile(fallback, output_path)
            validated = mitv_logos.validate_cached_png(output_path)
            if validated is not None:
                width, height = validated
                payload = output_path.read_bytes()
                record = {
                    "page_url": SOURCE_URL,
                    "local_url": mitv_logos.local_logo_url(CHANNEL_ID),
                    "available": True,
                    "source": f"fallback-local-{LOGO_FALLBACK_CHANNEL_ID}",
                    "source_url": mitv_logos.local_logo_url(LOGO_FALLBACK_CHANNEL_ID),
                    "width": width,
                    "height": height,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                warn(
                    "El Gourmet Sur: mi.tv no entregó logo nuevo; se reutiliza el logo "
                    f"local de {LOGO_FALLBACK_CHANNEL_ID}."
                )

    if not record.get("available") or not output_path.is_file():
        raise RuntimeError(
            "El Gourmet Sur: no se pudo obtener ni reutilizar un logo local válido."
        )

    manifest: dict[str, object]
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {}
    channels = manifest.setdefault("channels", {})
    if not isinstance(channels, dict):
        channels = {}
        manifest["channels"] = channels
    channels[CHANNEL_ID] = record
    available = [cid for cid, item in channels.items() if isinstance(item, dict) and item.get("available")]
    missing = [cid for cid, item in channels.items() if not (isinstance(item, dict) and item.get("available"))]
    manifest["generated_at"] = datetime.now(epg.TZ).isoformat()
    manifest["public_base_url"] = mitv_logos.PUBLIC_LOGO_BASE
    manifest["targets"] = len(channels)
    manifest["available"] = len(available)
    manifest["missing"] = missing
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(record["local_url"]), record


def _cached_programmes(previous_xml: Path | None, start_date, days: int) -> list[etree._Element]:
    if previous_xml is None or not previous_xml.is_file():
        return []
    root = etree.parse(str(previous_xml), _xml_parser()).getroot()
    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=days)
    result: list[etree._Element] = []
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID):
        raw_start = node.get("start", "")
        raw_stop = node.get("stop", "")
        try:
            dt_start = datetime.strptime(raw_start, "%Y%m%d%H%M%S %z")
            dt_stop = datetime.strptime(raw_stop, "%Y%m%d%H%M%S %z")
        except ValueError:
            continue
        if dt_start < window_end and dt_stop > window_start:
            result.append(copy.deepcopy(node))
    result.sort(key=lambda item: item.get("start", ""))
    return result


def _load_fresh_programmes(start_date, days: int):
    local_days = min(max(int(days), 1), LOCAL_DAYS)
    return mitv_utc.scrape_mitv_channel(
        country=COUNTRY,
        slug=SLUG,
        channel_id=CHANNEL_ID,
        start_date=start_date,
        local_days=local_days,
        pause_seconds=0.5,
    )


def add_channel(
    *,
    output_dir: Path,
    days: int,
    previous_latam_xml: Path | None,
    logos_manifest: Path,
) -> dict[str, object]:
    xml_path = output_dir / "latam.xml"
    gz_path = output_dir / "latam.xml.gz"
    status_path = output_dir / "latam-status.json"
    if not xml_path.is_file() or not status_path.is_file():
        raise RuntimeError("El Gourmet Sur requiere latam.xml y latam-status.json previos.")

    root = etree.parse(str(xml_path), _xml_parser()).getroot()
    # Idempotencia si se reejecuta el paso.
    for node in list(root.xpath("./channel[@id=$channel_id]", channel_id=CHANNEL_ID)):
        root.remove(node)
    for node in list(root.xpath("./programme[@channel=$channel_id]", channel_id=CHANNEL_ID)):
        root.remove(node)

    input_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(input_ids) != EXPECTED_INPUT_CHANNELS:
        raise RuntimeError(
            f"El Gourmet Sur esperaba {EXPECTED_INPUT_CHANNELS} canales de entrada y recibió {len(input_ids)}."
        )

    today = datetime.now(epg.TZ).date()
    source_mode = "mi-tv-fresh"
    source_error: str | None = None
    loaded_source_days = 0
    programmes = []
    cached_nodes: list[etree._Element] = []
    try:
        programmes, loaded_source_days = _load_fresh_programmes(today, days)
    except RuntimeError as exc:
        source_error = str(exc)
        cached_nodes = _cached_programmes(previous_latam_xml, today, min(max(days, 1), LOCAL_DAYS))
        if len(cached_nodes) < MIN_PROGRAMMES:
            raise RuntimeError(
                "El Gourmet Sur no tiene programación utilizable en mi.tv ni en la última "
                f"latam.xml válida de epg-data. mi.tv={exc}; caché={len(cached_nodes)} emisiones."
            ) from exc
        source_mode = "previous-latam-cache"
        warn(
            f"El Gourmet Sur: mi.tv falló ({exc}); se reutilizan {len(cached_nodes)} "
            "emisiones vigentes de la última latam.xml válida."
        )

    logo_url, logo_record = _refresh_logo(output_dir, logos_manifest)

    channel = etree.Element("channel", id=CHANNEL_ID)
    for name in DISPLAY_NAMES:
        display = etree.SubElement(channel, "display-name", lang="es")
        display.text = name
    etree.SubElement(channel, "icon", src=logo_url)
    url = etree.SubElement(channel, "url")
    url.text = SOURCE_URL
    _insert_channel_before_programmes(root, channel)

    if source_mode == "mi-tv-fresh":
        if len(programmes) < MIN_PROGRAMMES:
            raise RuntimeError(
                f"El Gourmet Sur: mi.tv devolvió solo {len(programmes)} emisiones."
            )
        for programme in sorted(programmes, key=lambda item: (item.start, item.title)):
            root.append(_programme_node(programme))
        programme_count = len(programmes)
    else:
        for node in cached_nodes:
            root.append(node)
        programme_count = len(cached_nodes)

    final_ids = tuple(node.get("id", "") for node in root.findall("channel"))
    if len(final_ids) != EXPECTED_FINAL_CHANNELS or final_ids[-1:] != TARGET_IDS:
        raise RuntimeError(
            f"El Gourmet Sur dejó un orden de canales inesperado: {len(final_ids)} / último={final_ids[-1:]}."
        )

    _write_xml_and_gzip(root, xml_path, gz_path)

    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["version"] = _repo_version()
    status["channels"] = EXPECTED_FINAL_CHANNELS
    sources = status.setdefault("sources", {})
    if isinstance(sources, dict):
        mi_tv = sources.setdefault("mi_tv", {})
        if isinstance(mi_tv, dict):
            mi_tv[CHANNEL_ID] = SOURCE_URL
    source_days = status.setdefault("mitv_source_days", {})
    if isinstance(source_days, dict):
        source_days[CHANNEL_ID] = int(loaded_source_days)
    status["elgourmet_sur_epg"] = {
        "version": VERSION,
        "channel_id": CHANNEL_ID,
        "display_name": DISPLAY_NAMES[0],
        "source": SOURCE_URL,
        "source_mode": source_mode,
        "source_timezone": SOURCE_TIMEZONE,
        "output_timezone": OUTPUT_TIMEZONE,
        "manual_offset_minutes": MANUAL_OFFSET_MINUTES,
        "loaded_source_days": int(loaded_source_days),
        "programmes": programme_count,
        "mi_tv_error": source_error,
        "logo_url": logo_url,
        "logo_source": logo_record.get("source"),
        "logo_source_url": logo_record.get("source_url"),
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    log(
        f"El Gourmet Sur añadido: {programme_count} emisiones; modo={source_mode}; "
        f"{SOURCE_TIMEZONE}->{OUTPUT_TIMEZONE}; logo={logo_url}; canales={EXPECTED_FINAL_CHANNELS}."
    )
    return status["elgourmet_sur_epg"]


def self_test() -> None:
    # Prueba de inserción estructural, serialización y orden XMLTV sin Internet.
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        root = etree.Element("tv")
        for index in range(EXPECTED_INPUT_CHANNELS):
            etree.SubElement(root, "channel", id=f"Test.{index:02d}")
        etree.SubElement(
            root,
            "programme",
            start="20260911000000 -0500",
            stop="20260911010000 -0500",
            channel="Test.00",
        )
        channel = etree.Element("channel", id=CHANNEL_ID)
        etree.SubElement(channel, "display-name", lang="es").text = DISPLAY_NAMES[0]
        etree.SubElement(channel, "icon", src=mitv_logos.local_logo_url(CHANNEL_ID))
        _insert_channel_before_programmes(root, channel)
        ids = tuple(node.get("id", "") for node in root.findall("channel"))
        assert len(ids) == EXPECTED_FINAL_CHANNELS
        assert ids[-1] == CHANNEL_ID
        first_programme_index = next(i for i, node in enumerate(root) if node.tag == "programme")
        channel_index = list(root).index(channel)
        assert channel_index < first_programme_index
        xml_path = base / "latam.xml"
        gz_path = base / "latam.xml.gz"
        _write_xml_and_gzip(root, xml_path, gz_path)
        assert gzip.decompress(gz_path.read_bytes()) == xml_path.read_bytes()

    assert COUNTRY == "ar"
    assert SLUG == "el-gourmet"
    assert SOURCE_TIMEZONE == "UTC"
    assert OUTPUT_TIMEZONE == "America/Guayaquil"
    assert MANUAL_OFFSET_MINUTES == 0
    print(
        "Prueba v0.2.59 correcta: Canal.Elgourmet.ar se inserta como canal 37, "
        "mi.tv Argentina UTC->America/Guayaquil, logo local y offset manual 0."
    )


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
    manifest = args.logos_manifest or (args.output / "logos" / "manifest.json")
    add_channel(
        output_dir=args.output,
        days=args.days,
        previous_latam_xml=args.previous_latam_xml,
        logos_manifest=manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

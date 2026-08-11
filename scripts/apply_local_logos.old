#!/usr/bin/env python3
"""Aplica a un XMLTV los logos locales disponibles y regenera su XML.GZ."""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path

from lxml import etree

from mitv_logos import load_logo_urls

HEADER = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n'
)


def set_icon(channel: etree._Element, icon_url: str) -> None:
    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    icon = etree.Element("icon", src=icon_url)
    children = list(channel)
    insert_at = len(children)
    for index, child in enumerate(children):
        if child.tag == "url":
            insert_at = index
            break
    channel.insert(insert_at, icon)


def apply(xml_path: Path, gz_path: Path, manifest_path: Path) -> int:
    logo_urls = load_logo_urls(manifest_path)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=True)
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    changed = 0
    for channel in root.findall("channel"):
        channel_id = channel.get("id", "")
        icon_url = logo_urls.get(channel_id)
        if icon_url:
            set_icon(channel, icon_url)
            changed += 1

    payload = etree.tostring(root, encoding="UTF-8", xml_declaration=False, pretty_print=True)
    xml_bytes = HEADER + payload
    xml_path.write_bytes(xml_bytes)
    with gz_path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, compresslevel=9, mtime=0) as gz_handle:
            gz_handle.write(xml_bytes)
    if gzip.decompress(gz_path.read_bytes()) != xml_bytes:
        raise RuntimeError(f"{gz_path} no coincide con {xml_path}.")
    print(f"Logos locales aplicados en {xml_path.name}: {changed}.")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--gz", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    apply(args.xml, args.gz, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

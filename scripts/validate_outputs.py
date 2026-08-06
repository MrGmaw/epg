#!/usr/bin/env python3
"""Validaciones finales de los archivos XML/XML.GZ publicados."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from lxml import etree

EC_REQUIRED = {
    "TeleamazonasQuito.ec",
    "TeleamazonasGuayaquil.ec",
    "Ecuavisa.ec",
    "EcuavisaInternacional.ec",
    "TVC.ec",
    "Canal.CNN.en.Español.ec",
    "NTN24.co",
}
LATAM_REQUIRED = (
    "Canal.TC.Televisión.ec",
    "Canal.Gamavisión.ec",
    "Canal.RTS.ec",
    "Canal.TVE.Internacional.(Televisión.Española).ec",
    "TeleamazonasQuito.ec",
    "TeleamazonasGuayaquil.ec",
    "Ecuavisa.ec",
    "EcuavisaInternacional.ec",
    "TVC.ec",
    "Canal.CNN.en.Español.ec",
    "NTN24.co",
    "CanalRCN.co",
    "CaracolTV.co",
    "Canal.Elgourmet.ec",
    "Canal.History.co",
    "Canal.History.2.co",
    "TV.Publica.canal.7.ar",
    "Telefe.ar",
    "Deutsche.Welle.cl",
    "Canal.Ecuador.TV.ec",
)
EXPECTED_HEADER = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n'
)


def validate_pair(
    xml_path: Path,
    gz_path: Path,
    dtd_path: Path,
    required: set[str],
    exact_order: tuple[str, ...] | None = None,
) -> dict[str, int]:
    xml_bytes = xml_path.read_bytes()
    if not xml_bytes.startswith(EXPECTED_HEADER):
        raise RuntimeError(f"Cabecera XML inesperada en {xml_path}.")
    if gzip.decompress(gz_path.read_bytes()) != xml_bytes:
        raise RuntimeError(f"{gz_path} no coincide con {xml_path}.")

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    channel_ids = [channel.get("id", "") for channel in root.findall("channel")]
    if len(channel_ids) != len(set(channel_ids)):
        raise RuntimeError(f"IDs duplicados en {xml_path}.")
    missing = required.difference(channel_ids)
    if missing:
        raise RuntimeError(f"Faltan IDs en {xml_path}: {sorted(missing)}")
    if exact_order is not None and channel_ids != list(exact_order):
        raise RuntimeError(f"{xml_path} no contiene exactamente los 20 IDs acordados.")

    counts = {channel_id: 0 for channel_id in required}
    for programme in root.findall("programme"):
        channel_id = programme.get("channel", "")
        if channel_id in counts:
            counts[channel_id] += 1
    empty = [channel_id for channel_id, count in counts.items() if count <= 0]
    if empty:
        raise RuntimeError(f"Canales sin programación en {xml_path}: {empty}")

    with dtd_path.open("rb") as handle:
        dtd = etree.DTD(handle)
    if not dtd.validate(tree):
        errors = "\n".join(str(item) for item in dtd.error_log[:20])
        raise RuntimeError(f"DTD inválido en {xml_path}:\n{errors}")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", type=Path, default=Path("public"))
    args = parser.parse_args()
    public = args.public

    ec_counts = validate_pair(
        public / "ec.xml",
        public / "ec.xml.gz",
        public / "xmltv.dtd",
        EC_REQUIRED,
    )
    latam_counts = validate_pair(
        public / "latam.xml",
        public / "latam.xml.gz",
        public / "xmltv.dtd",
        set(LATAM_REQUIRED),
        LATAM_REQUIRED,
    )

    status = json.loads((public / "status.json").read_text(encoding="utf-8"))
    latam_status = json.loads(
        (public / "latam-status.json").read_text(encoding="utf-8")
    )
    if int(latam_status.get("channels", 0)) != 20:
        raise RuntimeError("latam-status.json no informa 20 canales.")
    for channel_id in LATAM_REQUIRED:
        if int(latam_status.get("programme_counts", {}).get(channel_id, 0)) <= 0:
            raise RuntimeError(
                f"latam-status.json no registra programación para {channel_id}."
            )
    if not status.get("generated_at") or not latam_status.get("generated_at"):
        raise RuntimeError("Falta generated_at en los archivos de estado.")

    print("Validación final correcta.")
    print(f"ec.xml: {sum(ec_counts.values())} emisiones obligatorias.")
    print(f"latam.xml: {sum(latam_counts.values())} emisiones, 20 canales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

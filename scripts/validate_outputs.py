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
    "hgtv.ar",
    "France24Espanol.fr",
    "Canal24Horas.es",
    "La1.es",
    "TVEStarHD.es",
    "Clan.es",
    "MakroDigitalTV.ec",
    "Canal.Ecuador.TV.ec",
)
VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
EXPECTED_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
LOCAL_LOGO_BASE = "https://mrgmaw.github.io/epg/logos/"
MITV_LOGO_IDS = {
    "Canal.CNN.en.Español.ec",
    "Canal.TVE.Internacional.(Televisión.Española).ec",
    "NTN24.co",
    "CanalRCN.co",
    "CaracolTV.co",
    "Canal.Elgourmet.ec",
    "Canal.History.co",
    "Canal.History.2.co",
    "TV.Publica.canal.7.ar",
    "Telefe.ar",
    "Deutsche.Welle.cl",
    "hgtv.ar",
    "France24Espanol.fr",
}
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
        raise RuntimeError(
            f"{xml_path} no contiene exactamente los {len(exact_order)} IDs acordados."
        )

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



def channel_icon_map(tree: etree._ElementTree) -> dict[str, str]:
    result: dict[str, str] = {}
    for channel in tree.getroot().findall("channel"):
        icon = channel.find("icon")
        if icon is not None and icon.get("src"):
            result[channel.get("id", "")] = icon.get("src", "")
    return result


def validate_logo_manifest(public: Path) -> dict[str, object]:
    manifest_path = public / "logos" / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Falta logos/manifest.json.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    channels = manifest.get("channels")
    if not isinstance(channels, dict):
        raise RuntimeError("logos/manifest.json no contiene channels válido.")
    if int(manifest.get("targets", 0)) != len(MITV_LOGO_IDS):
        raise RuntimeError(
            f"El manifiesto de logos no contiene los {len(MITV_LOGO_IDS)} canales mi.tv esperados."
        )

    available: set[str] = set()
    for channel_id in MITV_LOGO_IDS:
        item = channels.get(channel_id)
        if not isinstance(item, dict):
            raise RuntimeError(f"Falta {channel_id} en el manifiesto de logos.")
        if item.get("available"):
            path = public / "logos" / f"{channel_id}.png"
            if not path.is_file() or not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(f"Logo local inválido o ausente para {channel_id}.")
            expected_url = f"{LOCAL_LOGO_BASE}{channel_id}.png"
            if item.get("local_url") != expected_url:
                raise RuntimeError(f"URL local inesperada para {channel_id}.")
            available.add(channel_id)
    return {"manifest": manifest, "available": available}

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

    logo_info = validate_logo_manifest(public)
    logo_available = logo_info["available"]
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=True)
    ec_tree = etree.parse(str(public / "ec.xml"), parser)
    latam_tree = etree.parse(str(public / "latam.xml"), parser)
    ec_icons = channel_icon_map(ec_tree)
    latam_icons = channel_icon_map(latam_tree)
    for channel_id in logo_available:
        expected_url = f"{LOCAL_LOGO_BASE}{channel_id}.png"
        if latam_icons.get(channel_id) != expected_url:
            raise RuntimeError(f"latam.xml no usa el logo local de {channel_id}.")
        if channel_id in {"Canal.CNN.en.Español.ec", "NTN24.co"} and ec_icons.get(channel_id) != expected_url:
            raise RuntimeError(f"ec.xml no usa el logo local de {channel_id}.")

    status = json.loads((public / "status.json").read_text(encoding="utf-8"))
    latam_status = json.loads(
        (public / "latam-status.json").read_text(encoding="utf-8")
    )
    if latam_status.get("version") != EXPECTED_VERSION:
        raise RuntimeError(
            f"latam-status.json no informa la versión {EXPECTED_VERSION}."
        )
    expected_latam_channels = len(LATAM_REQUIRED)
    if int(latam_status.get("channels", 0)) != expected_latam_channels:
        raise RuntimeError(
            f"latam-status.json no informa {expected_latam_channels} canales."
        )
    for channel_id in LATAM_REQUIRED:
        if int(latam_status.get("programme_counts", {}).get(channel_id, 0)) <= 0:
            raise RuntimeError(
                f"latam-status.json no registra programación para {channel_id}."
            )
    if not status.get("generated_at") or not latam_status.get("generated_at"):
        raise RuntimeError("Falta generated_at en los archivos de estado.")

    print("Validación final correcta.")
    print(f"ec.xml: {sum(ec_counts.values())} emisiones obligatorias.")
    print(f"latam.xml: {sum(latam_counts.values())} emisiones, {len(LATAM_REQUIRED)} canales.")
    print(f"logos mi.tv: {len(logo_available)}/{len(MITV_LOGO_IDS)} disponibles localmente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

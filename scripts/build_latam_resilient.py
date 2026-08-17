#!/usr/bin/env python3
"""Construye LATAM excluyendo STAR TVE de forma definitiva.

El nombre de este archivo se conserva únicamente por compatibilidad con el
workflow incremental de las versiones v0.2.26-v0.2.28. Desde v0.2.29 ya no
existe ninguna lógica de recuperación, caché ni scraping especial para STAR TVE.

Antes de ejecutar ``build_latam_epg.main()`` se elimina ``TVEStarHD.es`` tanto
de ``GATOTV_CHANNELS`` como de ``LATAM_CHANNEL_IDS``. Por ello STAR TVE no se
consulta en GatoTV, no se publica como <channel>, no genera <programme> y no
puede bloquear la generación de los otros 26 canales.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lxml import etree

import build_latam_epg as latam

STAR_ID = "TVEStarHD.es"
EXPECTED_CHANNELS = 26


def _arg_path(argv: list[str], name: str, default: Path) -> Path:
    prefix = name + "="
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return Path(argv[index + 1])
        if value.startswith(prefix):
            return Path(value.split("=", 1)[1])
    return default


def _output_dir(argv: list[str]) -> Path:
    return _arg_path(argv, "--output", Path("public"))


def configure_without_star() -> None:
    """Retira STAR TVE de las colecciones usadas por el constructor LATAM."""
    latam.GATOTV_CHANNELS = tuple(
        config for config in latam.GATOTV_CHANNELS if config.channel_id != STAR_ID
    )
    latam.LATAM_CHANNEL_IDS = tuple(
        channel_id for channel_id in latam.LATAM_CHANNEL_IDS if channel_id != STAR_ID
    )

    if any(config.channel_id == STAR_ID for config in latam.GATOTV_CHANNELS):
        raise RuntimeError("STAR TVE sigue presente en GATOTV_CHANNELS.")
    if STAR_ID in latam.LATAM_CHANNEL_IDS:
        raise RuntimeError("STAR TVE sigue presente en LATAM_CHANNEL_IDS.")
    if len(latam.LATAM_CHANNEL_IDS) != EXPECTED_CHANNELS:
        raise RuntimeError(
            "La guía sin STAR TVE debe contener exactamente "
            f"{EXPECTED_CHANNELS} canales; obtenidos={len(latam.LATAM_CHANNEL_IDS)}."
        )
    if len(set(latam.LATAM_CHANNEL_IDS)) != EXPECTED_CHANNELS:
        raise RuntimeError("La guía LATAM sin STAR TVE contiene IDs duplicados.")


def _clean_status(output_dir: Path) -> None:
    """Elimina del estado cualquier metadato heredado específico de STAR TVE."""
    status_path = output_dir / "latam-status.json"
    if not status_path.is_file():
        return

    status = json.loads(status_path.read_text(encoding="utf-8"))
    for key in list(status):
        if key.startswith("star_tve_"):
            status.pop(key, None)

    for key in (
        "programme_counts",
        "gatotv_source_days",
        "gatotv_daily_counts",
        "gatotv_source_timezones",
        "gatotv_ampm_local_preferred",
    ):
        value = status.get(key)
        if isinstance(value, dict):
            value.pop(STAR_ID, None)

    sources = status.get("sources")
    if isinstance(sources, dict):
        gato_tv = sources.get("gato_tv")
        if isinstance(gato_tv, dict):
            gato_tv.pop(STAR_ID, None)

    status["channels"] = EXPECTED_CHANNELS
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _assert_output_without_star(output_dir: Path) -> None:
    """Guardia final: STAR no puede aparecer en XML ni en latam-status.json."""
    xml_path = output_dir / "latam.xml"
    if not xml_path.is_file():
        raise RuntimeError("No se generó latam.xml.")

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    if root.xpath("./channel[@id=$channel_id]", channel_id=STAR_ID):
        raise RuntimeError("latam.xml todavía contiene el canal STAR TVE.")
    if root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_ID):
        raise RuntimeError("latam.xml todavía contiene emisiones de STAR TVE.")

    channel_ids = [node.get("id", "") for node in root.findall("channel")]
    if len(channel_ids) != EXPECTED_CHANNELS:
        raise RuntimeError(
            f"latam.xml debe contener {EXPECTED_CHANNELS} canales sin STAR TVE; "
            f"obtenidos={len(channel_ids)}."
        )

    status_path = output_dir / "latam-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if int(status.get("channels", 0)) != EXPECTED_CHANNELS:
        raise RuntimeError("latam-status.json no informa 26 canales.")
    if STAR_ID in status.get("programme_counts", {}):
        raise RuntimeError("latam-status.json todavía registra STAR TVE.")


def self_test() -> None:
    configure_without_star()
    assert len(latam.LATAM_CHANNEL_IDS) == EXPECTED_CHANNELS
    assert STAR_ID not in latam.LATAM_CHANNEL_IDS
    assert STAR_ID not in {config.channel_id for config in latam.GATOTV_CHANNELS}
    assert "Canal24Horas.es" in latam.LATAM_CHANNEL_IDS
    assert "La1.es" in latam.LATAM_CHANNEL_IDS
    assert "Clan.es" in latam.LATAM_CHANNEL_IDS
    print(
        "Prueba LATAM sin STAR TVE correcta: 26 canales; STAR excluido de "
        "GatoTV y del conjunto publicado."
    )


def main() -> int:
    configure_without_star()
    result = latam.main()
    if result == 0:
        output_dir = _output_dir(sys.argv[1:])
        _clean_status(output_dir)
        _assert_output_without_star(output_dir)
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (etree.XMLSyntaxError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

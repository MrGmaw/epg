#!/usr/bin/env python3
"""Construye LATAM sin STAR TVE y añade Antena 3 / Star Channel desde mi.tv.

Compatibilidad con v0.2.29:
- ``TVEStarHD.es`` continúa excluido completamente.
- Se añaden ``Antena3-America.co`` y ``Star-Channel.co`` desde mi.tv Colombia.

Regla horaria corregida desde v0.2.32:
las páginas visibles de mi.tv Colombia corresponden al reloj local de
Colombia/Ecuador, pero el endpoint HTML asíncrono usado por el scraper entrega
sus horas en UTC. Por ello Antena 3 y Star Channel usan el mismo parser
``scripts/mitv_utc.py`` que el resto de canales mi.tv: UTC ->
``America/Guayaquil``. No existe offset manual.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from lxml import etree

import build_latam_epg as latam
import mitv_utc

STAR_TVE_ID = "TVEStarHD.es"
ANTENA3_ID = "Antena3-America.co"
STAR_CHANNEL_ID = "Star-Channel.co"
ADDED_MITV_IDS = frozenset({ANTENA3_ID, STAR_CHANNEL_ID})
EXPECTED_CHANNELS = 28
EXPECTED_LATAM_IDS: tuple[str, ...] = (
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
    ANTENA3_ID,
    STAR_CHANNEL_ID,
    "Canal24Horas.es",
    "La1.es",
    "Clan.es",
    "MakroDigitalTV.ec",
    "Canal.Ecuador.TV.ec",
)
ADDED_MITV_CHANNELS: tuple[latam.MitvChannel, ...] = (
    latam.MitvChannel(
        "co",
        "antena3",
        ANTENA3_ID,
        ("Antena 3", "Antena3"),
        "https://mi.tv/co/canales/antena3",
    ),
    latam.MitvChannel(
        "co",
        "fox",
        STAR_CHANNEL_ID,
        ("Star Channel", "STAR Channel"),
        "https://mi.tv/co/canales/fox",
    ),
)


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


def configure_channels() -> None:
    """Retira STAR TVE y añade los dos canales mi.tv con IDs estables."""
    latam.GATOTV_CHANNELS = tuple(
        config for config in latam.GATOTV_CHANNELS if config.channel_id != STAR_TVE_ID
    )

    # Idempotencia: si se invoca más de una vez, no duplica canales.
    latam.MITV_CHANNELS = tuple(
        config for config in latam.MITV_CHANNELS if config.channel_id not in ADDED_MITV_IDS
    ) + ADDED_MITV_CHANNELS

    latam.LATAM_CHANNEL_IDS = (
        *latam.BASE_CHANNEL_IDS,
        *(config.channel_id for config in latam.MITV_CHANNELS),
        *(config.channel_id for config in latam.GATOTV_CHANNELS),
        latam.MAKRODIGITAL_ID,
        latam.ECUADOR_TV_ID,
    )

    if STAR_TVE_ID in latam.LATAM_CHANNEL_IDS:
        raise RuntimeError("STAR TVE reapareció en LATAM_CHANNEL_IDS.")
    if any(config.channel_id == STAR_TVE_ID for config in latam.GATOTV_CHANNELS):
        raise RuntimeError("STAR TVE reapareció en GATOTV_CHANNELS.")
    if len(latam.LATAM_CHANNEL_IDS) != EXPECTED_CHANNELS:
        raise RuntimeError(
            f"La guía debe contener {EXPECTED_CHANNELS} canales; "
            f"obtenidos={len(latam.LATAM_CHANNEL_IDS)}."
        )
    if len(set(latam.LATAM_CHANNEL_IDS)) != EXPECTED_CHANNELS:
        raise RuntimeError("La guía LATAM contiene IDs duplicados.")
    if tuple(latam.LATAM_CHANNEL_IDS) != EXPECTED_LATAM_IDS:
        raise RuntimeError(
            "El orden/identidad de LATAM_CHANNEL_IDS no coincide con los 28 IDs "
            "canónicos de v0.2.32."
        )
    for channel_id in ADDED_MITV_IDS:
        if channel_id not in latam.LATAM_CHANNEL_IDS:
            raise RuntimeError(f"Falta el nuevo canal {channel_id}.")


def _clean_and_annotate_status(output_dir: Path) -> None:
    """Limpia metadatos STAR TVE y registra la política mi.tv corregida."""
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
            value.pop(STAR_TVE_ID, None)

    sources = status.get("sources")
    if isinstance(sources, dict):
        gato_tv = sources.get("gato_tv")
        if isinstance(gato_tv, dict):
            gato_tv.pop(STAR_TVE_ID, None)

    status["channels"] = EXPECTED_CHANNELS
    status.pop("mitv_local_time_channels", None)
    status["mitv_endpoint_time_channels"] = {
        ANTENA3_ID: {
            "source": "https://mi.tv/co/canales/antena3",
            "endpoint_timezone": "UTC",
            "output_timezone": "America/Guayaquil",
            "conversion": "UTC->America/Guayaquil",
        },
        STAR_CHANNEL_ID: {
            "source": "https://mi.tv/co/canales/fox",
            "endpoint_timezone": "UTC",
            "output_timezone": "America/Guayaquil",
            "conversion": "UTC->America/Guayaquil",
        },
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _assert_output(output_dir: Path) -> None:
    """Guardia final: 28 canales, nuevos IDs presentes y STAR TVE ausente."""
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
    root = etree.parse(str(xml_path), parser).getroot()

    if root.xpath("./channel[@id=$channel_id]", channel_id=STAR_TVE_ID):
        raise RuntimeError("latam.xml todavía contiene STAR TVE.")
    if root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_TVE_ID):
        raise RuntimeError("latam.xml todavía contiene emisiones STAR TVE.")

    channel_ids = [node.get("id", "") for node in root.findall("channel")]
    if len(channel_ids) != EXPECTED_CHANNELS or len(set(channel_ids)) != EXPECTED_CHANNELS:
        raise RuntimeError(
            f"latam.xml debe contener {EXPECTED_CHANNELS} canales únicos; "
            f"obtenidos={len(channel_ids)}."
        )
    if tuple(channel_ids) != EXPECTED_LATAM_IDS:
        raise RuntimeError(
            "latam.xml contiene 28 canales, pero su orden/identidad no coincide "
            "con la secuencia canónica de v0.2.32."
        )

    for channel_id in (ANTENA3_ID, STAR_CHANNEL_ID):
        if channel_id not in channel_ids:
            raise RuntimeError(f"latam.xml no contiene {channel_id}.")
        programmes = root.xpath("./programme[@channel=$channel_id]", channel_id=channel_id)
        if len(programmes) < 5:
            raise RuntimeError(
                f"latam.xml contiene programación insuficiente para {channel_id}: "
                f"{len(programmes)} emisiones."
            )
        for programme in programmes:
            if not programme.get("start", "").endswith(" -0500"):
                raise RuntimeError(f"Hora no Guayaquil en {channel_id}: {programme.get('start')}")
            if not programme.get("stop", "").endswith(" -0500"):
                raise RuntimeError(f"Hora no Guayaquil en {channel_id}: {programme.get('stop')}")

    status_path = output_dir / "latam-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if int(status.get("channels", 0)) != EXPECTED_CHANNELS:
        raise RuntimeError("latam-status.json no informa 28 canales.")
    counts = status.get("programme_counts", {})
    for channel_id in (ANTENA3_ID, STAR_CHANNEL_ID):
        if int(counts.get(channel_id, 0)) < 5:
            raise RuntimeError(f"latam-status.json no registra programación de {channel_id}.")

    endpoint_modes = status.get("mitv_endpoint_time_channels", {})
    expected_sources = {
        ANTENA3_ID: "https://mi.tv/co/canales/antena3",
        STAR_CHANNEL_ID: "https://mi.tv/co/canales/fox",
    }
    for channel_id, source_url in expected_sources.items():
        mode = endpoint_modes.get(channel_id, {})
        if mode.get("source") != source_url:
            raise RuntimeError(f"Fuente mi.tv inesperada para {channel_id}.")
        if (
            mode.get("endpoint_timezone") != "UTC"
            or mode.get("output_timezone") != "America/Guayaquil"
            or mode.get("conversion") != "UTC->America/Guayaquil"
        ):
            raise RuntimeError(f"Política horaria inesperada para {channel_id}: {mode!r}")


def _sample_page(times_and_titles: list[tuple[str, str]]) -> str:
    items = "\n".join(
        """
        <li><a><div class="content">
          <span class="time">{clock}</span>
          <h2>{title}</h2>
          <p class="synopsis">Prueba endpoint UTC de mi.tv</p>
        </div></a></li>
        """.format(clock=clock, title=title)
        for clock, title in times_and_titles
    )
    return f'<div id="listings"><ul>{items}</ul></div>'


def self_test() -> None:
    configure_channels()
    assert len(latam.LATAM_CHANNEL_IDS) == EXPECTED_CHANNELS
    assert tuple(latam.LATAM_CHANNEL_IDS) == EXPECTED_LATAM_IDS
    assert STAR_TVE_ID not in latam.LATAM_CHANNEL_IDS
    assert ANTENA3_ID in latam.LATAM_CHANNEL_IDS
    assert STAR_CHANNEL_ID in latam.LATAM_CHANNEL_IDS

    sample = _sample_page(
        [
            ("3:00pm", "Programa 1"),
            ("4:00pm", "Programa 2"),
            ("5:00pm", "Programa 3"),
            ("6:00pm", "Programa 4"),
            ("7:00pm", "Programa 5"),
            ("8:00pm", "Programa 6"),
        ]
    )
    programmes = mitv_utc.parse_mitv_page_utc(
        sample, date(2026, 8, 21), ANTENA3_ID
    )
    # El endpoint devuelve 15:00 UTC; la página visible en Colombia/Ecuador
    # corresponde a 10:00 (-05:00). Este era el desfase de v0.2.30/v0.2.31.
    assert programmes[0].start.isoformat() == "2026-08-21T10:00:00-05:00"
    assert programmes[0].stop.isoformat() == "2026-08-21T11:00:00-05:00"
    assert programmes[0].channel_id == ANTENA3_ID

    programmes_star = mitv_utc.parse_mitv_page_utc(
        sample, date(2026, 8, 21), STAR_CHANNEL_ID
    )
    assert programmes_star[0].start.isoformat() == "2026-08-21T10:00:00-05:00"

    # Asegura que el constructor no vuelve a sustituir el scraper estándar.
    assert latam.scrape_mitv_channel is mitv_utc.scrape_mitv_channel

    print(
        "Prueba v0.2.32 correcta: 28 canales; STAR TVE excluido; "
        "Antena 3 y Star Channel usan endpoint UTC -> America/Guayaquil."
    )


def main() -> int:
    configure_channels()
    result = latam.main()
    if result == 0:
        output_dir = _output_dir(sys.argv[1:])
        _clean_and_annotate_status(output_dir)
        _assert_output(output_dir)
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

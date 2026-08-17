#!/usr/bin/env python3
"""Ejecuta build_latam_epg con respaldo exacto para STAR TVE.

La fuente primaria de STAR TVE sigue siendo GatoTV y conserva íntegra la lógica
horaria de build_latam_epg (AM/PM localizado en America/Guayaquil y 24 h
Atlantic/Canary como respaldo, sin offsets manuales).

Si GatoTV no entrega ninguna parrilla utilizable para STAR TVE en una ejecución,
se reutilizan exclusivamente emisiones de TVEStarHD.es del último latam.xml
publicado que se solapen con las mismas fechas de la ventana actual. No se
proyectan días de semana, no se desplazan horas y no se inventan emisiones.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

from lxml import etree

import build_latam_epg as latam

STAR_ID = "TVEStarHD.es"
LAST_SOURCE_MODE: str | None = None
LAST_LIVE_ERROR: str | None = None
LAST_CACHE_PROGRAMMES = 0


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


def _previous_latam(argv: list[str]) -> Path:
    return _arg_path(argv, "--previous-latam-xml", Path(".cache/previous-latam.xml"))


def _text(node: etree._Element, tag: str) -> str | None:
    values = [latam.epg.normalize_text(value) for value in node.xpath(f"./{tag}/text()")]
    values = [value for value in values if value]
    return " — ".join(values) or None


def star_from_previous_latam(
    xml_path: Path,
    start_date: date,
    days: int,
) -> tuple[list[latam.epg.Programme], int, dict[str, int]]:
    """Extrae STAR TVE del cache usando fechas absolutas, sin reproyección."""
    if not xml_path.is_file() or xml_path.stat().st_size == 0:
        raise RuntimeError(f"STAR TVE: no existe caché LATAM utilizable en {xml_path}.")

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    window_start = datetime.combine(start_date, time.min, tzinfo=latam.epg.TZ)
    window_end = window_start + timedelta(days=days)

    programmes: list[latam.epg.Programme] = []
    for node in root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_ID):
        try:
            start = latam.parse_xmltv_datetime(node.get("start", ""))
            stop = latam.parse_xmltv_datetime(node.get("stop", ""))
        except ValueError:
            continue
        if not (start < window_end and stop > window_start):
            continue
        title = _text(node, "title")
        if not title:
            continue
        programmes.append(
            latam.epg.Programme(
                channel_id=STAR_ID,
                start=start,
                stop=stop,
                title=title,
                description=_text(node, "desc"),
            )
        )

    deduplicated: dict[tuple[str, str, str], latam.epg.Programme] = {}
    for programme in programmes:
        key = (
            programme.start.isoformat(),
            programme.stop.isoformat(),
            latam.normalized(programme.title),
        )
        deduplicated.setdefault(key, programme)
    result = sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.stop, item.title),
    )
    if len(result) < 5:
        raise RuntimeError(
            "STAR TVE: la última latam.xml no contiene al menos 5 emisiones "
            "exactas dentro de la ventana vigente."
        )

    daily_counts: dict[str, int] = {}
    for programme in result:
        day_key = programme.start.astimezone(latam.epg.TZ).date().isoformat()
        daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
    loaded_days = len(daily_counts)
    return result, loaded_days, daily_counts


def make_resilient_scraper(
    original: Callable,
    previous_latam_xml: Path,
) -> Callable:
    def resilient(config, start_date: date, days: int):
        global LAST_SOURCE_MODE, LAST_LIVE_ERROR, LAST_CACHE_PROGRAMMES
        if config.channel_id != STAR_ID:
            return original(config, start_date, days)
        try:
            result = original(config, start_date, days)
            LAST_SOURCE_MODE = "gatotv-live"
            LAST_LIVE_ERROR = None
            LAST_CACHE_PROGRAMMES = 0
            return result
        except RuntimeError as exc:
            LAST_LIVE_ERROR = str(exc)
            latam.epg.warn(
                "STAR TVE: GatoTV no entregó una parrilla utilizable; "
                "se probará la última latam.xml publicada sin mover fechas ni horas. "
                f"Detalle: {exc}"
            )
            try:
                programmes, loaded_days, daily_counts = star_from_previous_latam(
                    previous_latam_xml,
                    start_date,
                    days,
                )
            except (OSError, etree.XMLSyntaxError, RuntimeError, ValueError) as cache_exc:
                raise RuntimeError(
                    "STAR TVE: falló GatoTV y tampoco existe una copia exacta suficiente "
                    f"en epg-data. GatoTV: {exc}; caché: {cache_exc}"
                ) from cache_exc
            LAST_SOURCE_MODE = "epg-data-exact-cache"
            LAST_CACHE_PROGRAMMES = len(programmes)
            latam.epg.log(
                "STAR TVE: respaldo exacto desde epg-data activado: "
                f"{len(programmes)} emisiones en {loaded_days} día(s); "
                "reproyección=NO; ajuste_manual=0min."
            )
            return programmes, loaded_days, daily_counts

    return resilient


def _record_status(output_dir: Path) -> None:
    status_path = output_dir / "latam-status.json"
    if not status_path.is_file() or LAST_SOURCE_MODE is None:
        return
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    status["star_tve_source_mode"] = LAST_SOURCE_MODE
    status["star_tve_cache_policy"] = "exact-dates-only-no-reprojection"
    if LAST_SOURCE_MODE == "epg-data-exact-cache":
        status["star_tve_fallback"] = "epg-data/latam.xml"
        status["star_tve_cache_programmes"] = LAST_CACHE_PROGRAMMES
        status["star_tve_gatotv_error"] = LAST_LIVE_ERROR
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def self_test() -> None:
    root = etree.Element("tv")
    base = datetime(2026, 8, 17, 0, 0, tzinfo=latam.epg.TZ)
    for index in range(6):
        start = base + timedelta(hours=index * 3)
        stop = start + timedelta(hours=1)
        node = etree.SubElement(
            root,
            "programme",
            channel=STAR_ID,
            start=start.strftime("%Y%m%d%H%M%S %z"),
            stop=stop.strftime("%Y%m%d%H%M%S %z"),
        )
        etree.SubElement(node, "title", lang="es").text = f"STAR cache {index}"
    # Emisión fuera de la ventana: debe ignorarse y jamás trasladarse.
    outside = etree.SubElement(
        root,
        "programme",
        channel=STAR_ID,
        start="20260825000000 -0500",
        stop="20260825010000 -0500",
    )
    etree.SubElement(outside, "title", lang="es").text = "NO trasladar"

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "previous-latam.xml"
        etree.ElementTree(root).write(str(path), encoding="UTF-8", xml_declaration=True)
        programmes, loaded_days, daily_counts = star_from_previous_latam(
            path,
            date(2026, 8, 17),
            7,
        )
        assert len(programmes) == 6
        assert loaded_days == 1
        assert daily_counts == {"2026-08-17": 6}
        assert programmes[0].start.isoformat() == "2026-08-17T00:00:00-05:00"
        assert all(item.title != "NO trasladar" for item in programmes)

        calls = 0
        def failing_original(config, start_date, days):
            nonlocal calls
            calls += 1
            raise RuntimeError("fallo GatoTV simulado")

        fake_config = type("Config", (), {"channel_id": STAR_ID})()
        resilient = make_resilient_scraper(failing_original, path)
        fallback, fallback_days, fallback_counts = resilient(
            fake_config,
            date(2026, 8, 17),
            7,
        )
        assert calls == 1
        assert len(fallback) == 6
        assert fallback_days == 1
        assert fallback_counts == {"2026-08-17": 6}
        assert LAST_SOURCE_MODE == "epg-data-exact-cache"

    print(
        "Prueba STAR resiliente correcta: GatoTV primario; cache epg-data exacta, "
        "sin reproyección de fechas ni offsets manuales."
    )


def main() -> int:
    previous = _previous_latam(sys.argv[1:])
    latam.scrape_gatotv_channel = make_resilient_scraper(
        latam.scrape_gatotv_channel,
        previous,
    )
    result = latam.main()
    if result == 0:
        _record_status(_output_dir(sys.argv[1:]))
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (etree.XMLSyntaxError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

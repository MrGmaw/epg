#!/usr/bin/env python3
"""Ejecuta el generador estable de ``ec.xml`` con capas de compatibilidad.

El workflow descarga ``build_epg_base.py`` desde un commit inmutable. Esta
capa conserva ese generador y aplica solamente:

- corrección UTC -> America/Guayaquil para mi.tv;
- respaldo resiliente de TVC desde la última ``ec.xml`` válida de ``epg-data``
  cuando la web oficial cambia o deja de publicar una parrilla parseable;
- respaldo resiliente de TC Televisión: EPGShare -> GatoTV -> última
  ``epg-data/ec.xml`` válida, sin offsets manuales.
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import build_epg_base as epg
import tc_resilient
import tvc_resilient
from mitv_utc import parse_mitv_page_utc, self_test as mitv_self_test


def _output_dir(argv: list[str]) -> Path:
    for index, value in enumerate(argv):
        if value == "--output" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if value.startswith("--output="):
            return Path(value.split("=", 1)[1])
    return Path("public")


def _guide_days(argv: list[str]) -> int:
    for index, value in enumerate(argv):
        if value == "--days" and index + 1 < len(argv):
            try:
                return max(1, int(argv[index + 1]))
            except ValueError:
                break
        if value.startswith("--days="):
            try:
                return max(1, int(value.split("=", 1)[1]))
            except ValueError:
                break
    try:
        return max(1, int(os.environ.get("GUIDE_DAYS", "7")))
    except ValueError:
        return 7


def _record_sources(output_dir: Path) -> None:
    status_path = output_dir / "status.json"
    if not status_path.is_file():
        return
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if tvc_resilient.LAST_SOURCE is not None:
        status["tvc_source_mode"] = tvc_resilient.LAST_SOURCE
        if tvc_resilient.LAST_SOURCE == "epg-data-cache":
            status["tvc_fallback"] = "epg-data/ec.xml"

    if tc_resilient.LAST_SOURCE is not None:
        status["tc_source_mode"] = tc_resilient.LAST_SOURCE
        status["tc_programmes"] = tc_resilient.LAST_PROGRAMMES
        if tc_resilient.LAST_SOURCE == "gatotv":
            status["tc_fallback"] = tc_resilient.GATOTV_TC_BASE
            status["tc_gatotv_days"] = tc_resilient.LAST_GATOTV_DAYS
        elif tc_resilient.LAST_SOURCE == "epg-data-cache":
            status["tc_fallback"] = "epg-data/ec.xml"

    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    # scrape_mitv_range() del generador base consulta esta función global.
    epg.parse_mitv_page = parse_mitv_page_utc

    cache_xml = Path(os.environ.get("TVC_CACHE_XML", ".cache/previous-ec.xml"))

    # TC se corrige dentro de ec.xml antes de que build_latam_epg.py lo consuma.
    # Si EPGShare ya contiene programación vigente, la guía se conserva intacta.
    epg.parse_epgshare = tc_resilient.make_resilient_epgshare_parser(
        epg,
        epg.parse_epgshare,
        cache_xml,
        _guide_days(sys.argv[1:]),
    )

    epg.scrape_tvc = tvc_resilient.make_resilient_tvc_scraper(
        epg,
        epg.scrape_tvc,
        cache_xml,
    )
    result = epg.main()
    if result == 0:
        _record_sources(_output_dir(sys.argv[1:]))
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        mitv_self_test()
        tvc_resilient.self_test(epg)
        tc_resilient.self_test(epg)
        raise SystemExit(0)
    raise SystemExit(main())

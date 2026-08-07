#!/usr/bin/env python3
"""Ejecuta el generador estable de ``ec.xml`` corrigiendo mi.tv a UTC.

El workflow descarga ``build_epg_base.py`` desde un commit inmutable. Esta
capa sustituye únicamente el parser de mi.tv y conserva sin cambios las
integraciones ya validadas de la guía principal.
"""

from __future__ import annotations

import sys

import build_epg_base as epg
from mitv_utc import parse_mitv_page_utc, self_test


def main() -> int:
    # scrape_mitv_range() del generador base consulta esta función global.
    epg.parse_mitv_page = parse_mitv_page_utc
    return epg.main()


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    raise SystemExit(main())

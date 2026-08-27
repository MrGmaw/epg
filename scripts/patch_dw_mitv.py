#!/usr/bin/env python3
"""Hotfix idempotente para la nueva ruta de DW (Español) en mi.tv Chile."""

from __future__ import annotations

import re
import sys
from pathlib import Path

OLD_SLUG = "deutsche-welle"
NEW_SLUG = "deutsche-welle-espanol"
PATTERN = re.compile(r"deutsche-welle(?!-espanol)")
TARGETS = (
    Path("scripts/build_latam_epg.py"),
    Path("scripts/mitv_logos.py"),
)


def patch_file(path: Path) -> int:
    if not path.is_file():
        print(f"ADVERTENCIA: no existe {path}; se omite.", file=sys.stderr)
        return 0
    text = path.read_text(encoding="utf-8")
    matches = len(PATTERN.findall(text))
    if matches:
        text = PATTERN.sub(NEW_SLUG, text)
        path.write_text(text, encoding="utf-8", newline="\n")
    if PATTERN.search(text):
        raise RuntimeError(f"Persistió el slug antiguo de DW en {path}.")
    print(f"DW mi.tv: {path}: reemplazos={matches}; slug={NEW_SLUG}")
    return matches


def main() -> int:
    total = sum(patch_file(path) for path in TARGETS)
    base = TARGETS[0]
    if base.is_file():
        text = base.read_text(encoding="utf-8")
        if "Deutsche.Welle.cl" in text and NEW_SLUG not in text:
            raise RuntimeError(
                "build_latam_epg.py contiene Deutsche.Welle.cl pero no el slug corregido."
            )
    print(f"Hotfix DW listo; reemplazos totales={total}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
'''Normaliza DW y activa la capa TC oficial de EPG MrG v0.2.68.

Mantiene el parche seguro del slug primario de DW. Además instala, de forma
idempotente y durante el workflow, un pequeño hook en add_makrodigital_api.py
para ejecutar add_tc_epg.py inmediatamente después de MakroDigital. Esto evita
alterar la estructura estable del workflow v0.2.66 y mantiene TC como una capa
posterior sobre latam.xml.
'''

from __future__ import annotations

import re
import sys
from pathlib import Path

NEW_SLUG = "deutsche-welle-espanol"

PATTERN = re.compile(r"(?<![\w-])deutsche-welle(?!-[\w-])")

TARGETS = (
    Path("scripts/build_latam_epg.py"),
    Path("scripts/mitv_logos.py"),
)

TC_HOOK_TARGET = Path("scripts/add_makrodigital_api.py")
TC_HOOK_MARKER = "# EPG-MRG-TC-OFFICIAL-v0.2.68"
TC_MAIN_MARKER = 'if __name__ == "__main__":\n    raise SystemExit(main())'

TC_HOOK = r'''
# EPG-MRG-TC-OFFICIAL-v0.2.68
# Capa posterior: MakroDigital termina primero y luego TC sustituye únicamente
# los días que pudo leer completos desde https://tctelevision.com/programacion/.
_TC_ORIGINAL_MAIN = main


def main() -> int:
    args = build_parser().parse_args()
    result = _TC_ORIGINAL_MAIN()

    import add_tc_epg as _tc_epg

    if args.self_test:
        _tc_epg.self_test()
        return 0 if result is None else result

    if result not in (None, 0):
        return result

    tc_result = _tc_epg.apply(Path(args.output), args.days)
    tc_merge = tc_result["merge"]
    tc_build = tc_result["build"]
    print(
        "TC v0.2.68: "
        f"oficiales={tc_merge['official_programmes']}; "
        f"reemplazadas={tc_merge['replaced_programmes']}; "
        f"finales={tc_merge['final_programmes']}; "
        f"fechas oficiales={tc_build['official_dates']}"
    )
    return 0


'''


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
        raise RuntimeError(
            f"Persistió el slug antiguo aislado de DW en {path}."
        )

    print(
        f"DW mi.tv: {path}: reemplazos={matches}; "
        f"primario={NEW_SLUG}"
    )
    return matches


def patch_tc_hook(path: Path = TC_HOOK_TARGET) -> bool:
    if not path.is_file():
        raise RuntimeError(
            f"No existe el generador requerido para TC: {path}"
        )

    text = path.read_text(encoding="utf-8")
    if TC_HOOK_MARKER in text:
        print("TC v0.2.68: hook ya presente; no se duplica.")
        return False

    if TC_MAIN_MARKER not in text:
        raise RuntimeError(
            "No se encontró el bloque main esperado en "
            "add_makrodigital_api.py; se evita modificar un "
            "archivo de estructura desconocida."
        )

    text = text.replace(
        TC_MAIN_MARKER,
        TC_HOOK + TC_MAIN_MARKER,
        1,
    )
    path.write_text(text, encoding="utf-8", newline="\n")

    check = path.read_text(encoding="utf-8")
    if TC_HOOK_MARKER not in check:
        raise RuntimeError(
            "No fue posible instalar el hook TC v0.2.68."
        )

    print(
        "TC v0.2.68: hook oficial instalado en "
        "add_makrodigital_api.py (después de MakroDigital)."
    )
    return True


def main() -> int:
    total = sum(patch_file(path) for path in TARGETS)

    base = TARGETS[0]
    if base.is_file():
        text = base.read_text(encoding="utf-8")
        if "Deutsche.Welle.cl" in text and NEW_SLUG not in text:
            raise RuntimeError(
                "build_latam_epg.py contiene Deutsche.Welle.cl "
                "pero no el slug primario esperado."
            )

    tc_changed = patch_tc_hook()
    print(
        "Normalización DW lista; "
        f"reemplazos totales={total}; "
        f"TC hook={'instalado' if tc_changed else 'existente'}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

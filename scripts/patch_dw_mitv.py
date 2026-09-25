#!/usr/bin/env python3
'''Normaliza DW y activa las capas oficiales TC + Ecuador TV de EPG MrG v0.2.69.

Mantiene el parche del slug primario de DW. Instala de forma idempotente un hook
en add_makrodigital_api.py para ejecutar, después de MakroDigital:
  1) TC Televisión oficial (componente v0.2.68)
  2) Ecuador TV oficial/fallback Noticias 7 (componente v0.2.69)

Así se conserva la estructura estable del workflow sin editarlo manualmente.
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

HOOK_TARGET = Path("scripts/add_makrodigital_api.py")
HOOK_MARKER = "# EPG-MRG-OFFICIAL-LAYERS-v0.2.69"
MAIN_MARKER = 'if __name__ == "__main__":\n    raise SystemExit(main())'

HOOK = r'''
# EPG-MRG-OFFICIAL-LAYERS-v0.2.69
# Capas posteriores: primero TC (v0.2.68) y luego Ecuador TV (v0.2.69).
_EPG_MRG_ORIGINAL_MAIN = main


def main() -> int:
    args = build_parser().parse_args()
    result = _EPG_MRG_ORIGINAL_MAIN()

    import add_tc_epg as _tc_epg
    import add_ecuadortv_epg as _ecuador_tv_epg

    if args.self_test:
        _tc_epg.self_test()
        _ecuador_tv_epg.self_test()
        return 0 if result is None else result

    if result not in (None, 0):
        return result

    from pathlib import Path as _EpgPath

    tc_result = _tc_epg.apply(_EpgPath(args.output), args.days)
    tc_merge = tc_result["merge"]
    tc_build = tc_result["build"]
    print(
        "TC v0.2.68: "
        f"oficiales={tc_merge['official_programmes']}; "
        f"reemplazadas={tc_merge['replaced_programmes']}; "
        f"finales={tc_merge['final_programmes']}; "
        f"fechas oficiales={tc_build['official_dates']}"
    )

    etv_result = _ecuador_tv_epg.apply(_EpgPath(args.output), args.days)
    print(
        "Ecuador TV v0.2.69: "
        f"fechas oficiales={etv_result['build']['official_dates']}; "
        f"salidas={list(etv_result['outputs'])}"
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
        raise RuntimeError(f"Persistió el slug antiguo aislado de DW en {path}.")
    print(f"DW mi.tv: {path}: reemplazos={matches}; primario={NEW_SLUG}")
    return matches


def patch_official_layers(path: Path = HOOK_TARGET) -> bool:
    if not path.is_file():
        raise RuntimeError(f"No existe el generador requerido para las capas oficiales: {path}")

    text = path.read_text(encoding="utf-8")
    if HOOK_MARKER in text:
        print("Capas oficiales v0.2.69: hook ya presente; no se duplica.")
        return False

    # En una copia de trabajo que hubiera sido parcheada previamente durante la
    # misma ejecución, evitamos apilar wrappers incompatibles.
    if "# EPG-MRG-TC-OFFICIAL-v0.2.68" in text:
        raise RuntimeError(
            "add_makrodigital_api.py ya contiene el hook temporal TC v0.2.68. "
            "Ejecuta v0.2.69 sobre un checkout limpio (GitHub Actions lo hace automáticamente)."
        )

    if MAIN_MARKER not in text:
        raise RuntimeError(
            "No se encontró el bloque main esperado en add_makrodigital_api.py; "
            "se evita modificar un archivo de estructura desconocida."
        )

    text = text.replace(MAIN_MARKER, HOOK + MAIN_MARKER, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    if HOOK_MARKER not in path.read_text(encoding="utf-8"):
        raise RuntimeError("No fue posible instalar el hook de capas oficiales v0.2.69.")

    print("Capas oficiales v0.2.69: hook TC + Ecuador TV instalado después de MakroDigital.")
    return True


def main() -> int:
    total = sum(patch_file(path) for path in TARGETS)
    base = TARGETS[0]
    if base.is_file():
        text = base.read_text(encoding="utf-8")
        if "Deutsche.Welle.cl" in text and NEW_SLUG not in text:
            raise RuntimeError(
                "build_latam_epg.py contiene Deutsche.Welle.cl pero no el slug primario esperado."
            )
    changed = patch_official_layers()
    print(
        "Normalización DW lista; "
        f"reemplazos totales={total}; "
        f"capas oficiales={'instaladas' if changed else 'existentes'}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

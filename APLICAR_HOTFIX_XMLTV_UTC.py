#!/usr/bin/env python3
"""Aplica el hotfix vUTC a scripts/build_epg.py manteniendo las demás capas."""
from __future__ import annotations
import ast
from pathlib import Path
import sys

raiz = Path(__file__).resolve().parent
fichero = raiz / "scripts" / "build_epg.py"
modulo = raiz / "scripts" / "xmltv_validation_utc.py"
if not modulo.is_file():
    sys.exit("ERROR: falta scripts/xmltv_validation_utc.py. Extrae el ZIP completo.")
if not fichero.is_file():
    sys.exit("ERROR: ejecuta este archivo desde la raíz del repositorio epg.")
texto = fichero.read_text(encoding="utf-8")
if "xmltv_validation_utc.instalar(epg)" in texto:
    print("HOTFIX XMLTV UTC: ya estaba aplicado, sin cambios.")
    sys.exit(0)

original_import = "import build_epg_base as epg\n"
original_call = "    result = epg.main()\n"
if texto.count(original_import) != 1 or texto.count(original_call) != 1:
    sys.exit(
        "ERROR: la estructura de scripts/build_epg.py no coincide con la "
        "esperada. No se modificó ningún archivo."
    )
texto = texto.replace(
    original_import,
    original_import + "import xmltv_validation_utc\n",
    1,
)
texto = texto.replace(
    original_call,
    "    xmltv_validation_utc.instalar(epg)\n" + original_call,
    1,
)
ast.parse(texto, filename=str(fichero))
fichero.write_text(texto, encoding="utf-8", newline="\n")
print(f"HOTFIX XMLTV UTC aplicado a {fichero.relative_to(raiz)}.")
print("Ejecuta: python scripts/xmltv_validation_utc.py --self-test")

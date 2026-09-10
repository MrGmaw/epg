#!/usr/bin/env python3
"""Aplica los cambios de workflow necesarios para EPG MrG v0.2.55.

Ejecutar una sola vez desde la raíz del repositorio después de copiar los
archivos del overlay v0.2.55. Es idempotente: si el workflow ya contiene la
integración de Asamblea Nacional, no vuelve a modificarlo.
"""
from __future__ import annotations

from pathlib import Path
import sys

WORKFLOW = Path('.github/workflows/actualizar-epg.yml')
MARKER = 'Añadir TVL Asamblea Nacional v0.2.55'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: se esperaba 1 coincidencia y se encontraron {count}.')
    return text.replace(old, new, 1)


def main() -> int:
    if not WORKFLOW.is_file():
        raise RuntimeError(f'No existe {WORKFLOW}; ejecute este instalador desde la raíz del repositorio.')
    text = WORKFLOW.read_text(encoding='utf-8')
    if MARKER in text:
        print('Workflow v0.2.55 ya aplicado; no se requieren cambios.')
        return 0

    text = replace_once(
        text,
        '            scripts/add_star_tve.py \\\n            scripts/patch_dw_mitv.py',
        '            scripts/add_star_tve.py \\\n            scripts/add_asamblea_epg.py \\\n            scripts/patch_dw_mitv.py',
        'huella de scripts',
    )

    text = replace_once(
        text,
        '          import add_star_tve  # noqa: F401\n          print("Importación real de generadores, Miami, v0.2.39 y STAR TVE v0.2.44 correcta.")',
        '          import add_star_tve  # noqa: F401\n          import add_asamblea_epg  # noqa: F401\n          print("Importación real de generadores, Miami, v0.2.39, STAR TVE y Asamblea Nacional correcta.")',
        'importación de módulos',
    )

    text = replace_once(
        text,
        '          python scripts/add_star_tve.py --self-test\n          python scripts/mitv_logos.py --self-test',
        '          python scripts/add_star_tve.py --self-test\n          python scripts/add_asamblea_epg.py --self-test\n          python scripts/mitv_logos.py --self-test',
        'self-test Asamblea',
    )

    star_step = '''      - name: Añadir STAR TVE v0.2.44
        shell: bash
        env:
          TZ: America/Guayaquil
        run: |
          set -euo pipefail
          python scripts/add_star_tve.py \\
            --output public \\
            --days "${GUIDE_DAYS}" \\
            --previous-latam-xml .cache/previous-latam.xml
'''
    assembly_step = star_step + '''      - name: Añadir TVL Asamblea Nacional v0.2.55
        shell: bash
        env:
          TZ: America/Guayaquil
        run: |
          set -euo pipefail
          python scripts/add_asamblea_epg.py \\
            --output public \\
            --days "${GUIDE_DAYS}" \\
            --previous-latam-xml .cache/previous-latam.xml
'''
    text = replace_once(text, star_step, assembly_step, 'paso de construcción Asamblea')

    text = replace_once(
        text,
        '          import add_star_tve as star\n          STAR_ID = star.STAR_ID',
        '          import add_star_tve as star\n          import add_asamblea_epg as asamblea\n          STAR_ID = star.STAR_ID\n          ASAMBLEA_ID = asamblea.CHANNEL_ID',
        'importación del validador Asamblea',
    )

    text = replace_once(
        text,
        '          REQUIRED = (\n              "Deutsche.Welle.cl",\n              "Antena3-America.co",\n              "Star-Channel.co",\n              "Warner-channel.co",\n              "HBO-Family.co",\n              *miami.TARGET_IDS,\n              *v039.TARGET_IDS,\n              *star.TARGET_IDS,\n          )',
        '          REQUIRED = (\n              "Deutsche.Welle.cl",\n              "Antena3-America.co",\n              "Star-Channel.co",\n              "Warner-channel.co",\n              "HBO-Family.co",\n              *miami.TARGET_IDS,\n              *v039.TARGET_IDS,\n              *star.TARGET_IDS,\n              *asamblea.TARGET_IDS,\n          )',
        'REQUIRED Asamblea',
    )

    text = replace_once(
        text,
        '          validate.LATAM_REQUIRED = (\n              *resilient.EXPECTED_LATAM_IDS,\n              *miami.TARGET_IDS,\n              *v039.TARGET_IDS,\n              *star.TARGET_IDS,\n          )\n          assert len(validate.LATAM_REQUIRED) == 35, validate.LATAM_REQUIRED',
        '          validate.LATAM_REQUIRED = (\n              *resilient.EXPECTED_LATAM_IDS,\n              *miami.TARGET_IDS,\n              *v039.TARGET_IDS,\n              *star.TARGET_IDS,\n              *asamblea.TARGET_IDS,\n          )\n          assert len(validate.LATAM_REQUIRED) == 36, validate.LATAM_REQUIRED',
        'LATAM_REQUIRED 36',
    )

    text = replace_once(
        text,
        '          assert STAR_ID in validate.LATAM_REQUIRED\n          assert all(channel_id in validate.LATAM_REQUIRED for channel_id in REQUIRED)',
        '          assert STAR_ID in validate.LATAM_REQUIRED\n          assert ASAMBLEA_ID in validate.LATAM_REQUIRED\n          assert all(channel_id in validate.LATAM_REQUIRED for channel_id in REQUIRED)',
        'assert Asamblea requerida',
    )

    text = replace_once(
        text,
        '          assert tuple(node.get("id", "") for node in root.findall("channel"))[-3:-1] == v039.TARGET_IDS\n          assert tuple(node.get("id", "") for node in root.findall("channel"))[-1:] == star.TARGET_IDS',
        '          assert tuple(node.get("id", "") for node in root.findall("channel"))[-4:-2] == v039.TARGET_IDS\n          assert tuple(node.get("id", "") for node in root.findall("channel"))[-2:-1] == star.TARGET_IDS\n          assert tuple(node.get("id", "") for node in root.findall("channel"))[-1:] == asamblea.TARGET_IDS',
        'orden final de canales',
    )

    text = replace_once(
        text,
        '          assert int(status.get("channels", 0)) == 35, status.get("channels")',
        '          assert int(status.get("channels", 0)) == 36, status.get("channels")',
        'status channels=36',
    )

    anchor = '          assert "previous-latam-cache" not in set(star_policy.get("modes_used", [])), star_policy\n'
    assembly_validation = anchor + '''          asamblea_policy = status.get("asamblea_nacional_epg", {})
          assert asamblea_policy.get("channel_id") == ASAMBLEA_ID, asamblea_policy
          assert asamblea_policy.get("source_timezone") == "America/Guayaquil", asamblea_policy
          assert asamblea_policy.get("output_timezone") == "America/Guayaquil", asamblea_policy
          assert int(asamblea_policy.get("manual_offset_minutes", -1)) == 0, asamblea_policy
          assert int(asamblea_policy.get("programmes", 0)) >= 5, asamblea_policy
'''
    text = replace_once(text, anchor, assembly_validation, 'validación de política Asamblea')

    text = replace_once(
        text,
        '              "Validación v0.2.44 correcta: 35 canales; STAR TVE presente; "',
        '              "Validación v0.2.55 correcta: 36 canales; STAR TVE y Asamblea Nacional presentes; "',
        'mensaje de validación',
    )

    text = replace_once(
        text,
        '          Guía seleccionada de 35 canales:',
        '          Guía seleccionada de 36 canales:',
        'README epg-data',
    )

    WORKFLOW.write_text(text, encoding='utf-8', newline='\n')
    # Limpieza preventiva de bytecode local: no debe subirse al repositorio.
    for path in Path('scripts').rglob('__pycache__'):
        if path.is_dir():
            for child in path.iterdir():
                if child.is_file():
                    child.unlink()
            try:
                path.rmdir()
            except OSError:
                pass
    print('Workflow actualizado para v0.2.55: 36 canales + AsambleaNacional.ec.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise

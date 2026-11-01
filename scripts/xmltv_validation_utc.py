#!/usr/bin/env python3
"""Validación XMLTV compatible con cambios de offset, sin reescribir la EPG.

Se instala sobre el generador base descargado en GitHub Actions. Corrige SOLO
falsos positivos del validador histórico que compara start[:14] y stop[:14].
Todas las demás validaciones originales se conservan.
"""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from typing import Any

_FORMATOS = (
    "%Y%m%d%H%M%S %z",
    "%Y%m%d%H%M %z",
    "%Y%m%d%H %z",
)


def _instante(fecha: str) -> datetime | None:
    """Obtiene un instante consciente de su offset si está especificado."""
    for formato in _FORMATOS:
        try:
            valor = datetime.strptime(fecha.strip(), formato)
            if valor.tzinfo is not None:
                return valor.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            continue
    return None


def _comparacion_historica(inicio: str, fin: str) -> bool:
    return (
        inicio[:14].isdigit()
        and fin[:14].isdigit()
        and inicio[:14] >= fin[:14]
    )


def _identificacion(programa: Any) -> str:
    nombre = programa.findtext("title") or "(sin título)"
    return (
        f"canal={programa.get('channel', '(sin canal)')!r}; "
        f"título={nombre!r}; start={programa.get('start', '')!r}; "
        f"stop={programa.get('stop', '')!r}"
    )


def instalar(base: Any) -> None:
    """Instala una única vez el corrector sin modificar el XML original."""
    original = base.validate_tree
    if getattr(original, "_xmltv_validacion_utc_instalada", False):
        return

    def validar(tree: Any, requeridos: Any, dtd: Any) -> Any:
        programas = tree.getroot().findall("programme")
        falsos_positivos: list[int] = []
        verdaderamente_invalidos: list[str] = []

        for indice, programa in enumerate(programas):
            inicio = programa.get("start", "")
            fin = programa.get("stop", "")
            antes = _instante(inicio)
            despues = _instante(fin)
            error_historico = _comparacion_historica(inicio, fin)

            if antes is not None and despues is not None:
                if despues <= antes:
                    verdaderamente_invalidos.append(_identificacion(programa))
                elif error_historico:
                    falsos_positivos.append(indice)
            # Cuando la fuente no incluye offset, mantenemos el criterio de
            # validación original (no inventamos zona horaria).
            elif error_historico:
                verdaderamente_invalidos.append(_identificacion(programa))

        if verdaderamente_invalidos:
            for detalle in verdaderamente_invalidos[:25]:
                print(f"ERROR XMLTV rango real inválido: {detalle}", file=sys.stderr)
            raise RuntimeError(
                f"Se encontraron {len(verdaderamente_invalidos)} programas "
                "con stop <= start en tiempo real o sin offset verificable. "
                "Revisar el listado anterior (no se corrigen horas arbitrariamente)."
            )

        if not falsos_positivos:
            return original(tree, requeridos, dtd)

        # La copia es EXCLUSIVAMENTE para alimentar al validador histórico,
        # que compara fechas lexicográficamente sin ajustar los offsets.
        # El árbol original permanece intacto y es el que se publica.
        copia = copy.deepcopy(tree)
        programas_copia = copia.getroot().findall("programme")
        for indice in falsos_positivos:
            programa = programas_copia[indice]
            inicio = _instante(programa.get("start", ""))
            fin = _instante(programa.get("stop", ""))
            assert inicio is not None and fin is not None and fin > inicio
            programa.set("start", inicio.strftime("%Y%m%d%H%M%S +0000"))
            programa.set("stop", fin.strftime("%Y%m%d%H%M%S +0000"))

        resultado = original(copia, requeridos, dtd)
        print(
            "XMLTV: "
            f"{len(falsos_positivos)} intervalos aceptados tras comparar "
            "instantes UTC; se mantienen sin cambios los horarios y offsets "
            "originales en el XML publicado.",
            flush=True,
        )
        for indice in falsos_positivos[:20]:
            print(f"XMLTV ajuste de validación: {_identificacion(programas[indice])}")
        return resultado

    validar._xmltv_validacion_utc_instalada = True  # type: ignore[attr-defined]
    base.validate_tree = validar


def _pruebas() -> None:
    from lxml import etree

    class BasePrueba:
        def __init__(self) -> None:
            self.llamadas = 0

        def validate_tree(self, tree: Any, requeridos: Any, dtd: Any) -> dict[str, int]:
            self.llamadas += 1
            lista = tree.getroot().findall("programme")
            assert all(
                not _comparacion_historica(p.get("start", ""), p.get("stop", ""))
                for p in lista
            ), "El validador histórico sigue viendo un intervalo invertido"
            return {"programmes": len(lista)}

    def arbol(inicio: str, fin: str) -> Any:
        raiz = etree.Element("tv")
        programa = etree.SubElement(
            raiz, "programme", channel="Ejemplo.us", start=inicio, stop=fin
        )
        etree.SubElement(programa, "title").text = "Programa de prueba"
        return etree.ElementTree(raiz)

    base = BasePrueba()
    instalar(base)
    instalar(base)
    ejemplo = arbol("20261101013000 -0400", "20261101011500 -0500")
    atributos = dict(ejemplo.getroot()[0].attrib)
    assert base.validate_tree(ejemplo, set(), None) == {"programmes": 1}
    assert ejemplo.getroot()[0].attrib == atributos, "Se modificó el XML original"
    assert base.llamadas == 1, "La instalación no fue idempotente"

    # Fuera del cambio de hora, se conserva la validación habitual.
    normal = arbol("20261101120000 -0500", "20261101123000 -0500")
    assert base.validate_tree(normal, set(), None) == {"programmes": 1}

    # El cambio de offset no debe ocultar intervalos realmente inválidos.
    malo = arbol("20261101020000 -0500", "20261101010000 -0500")
    try:
        base.validate_tree(malo, set(), None)
    except RuntimeError as exc:
        assert "stop <= start" in str(exc)
    else:
        raise AssertionError("Intervalo realmente inválido aceptado")

    # Incluso con orden horario local creciente, un UTC invertido se rechaza.
    malo_utc = arbol("20261101015000 -0500", "20261101020000 -0400")
    try:
        base.validate_tree(malo_utc, set(), None)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Intervalo invertido en UTC aceptado")

    print("PRUEBAS XMLTV UTC/DST: OK (4 casos e idempotencia)")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        _pruebas()
    else:
        print("Uso: python scripts/xmltv_validation_utc.py --self-test")

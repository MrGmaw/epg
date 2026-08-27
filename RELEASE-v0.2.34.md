# EPG MrG v0.2.34

Corrección de empaquetado/dependencias sobre v0.2.33.

## Problema corregido

GitHub Actions podía superar `py_compile` y fallar después con:

```text
ModuleNotFoundError: No module named 'tc_resilient'
```

`py_compile` valida sintaxis, pero no importa las dependencias. Por eso un
módulo local ausente no se detectaba en la fase de comprobación.

## Solución

- `scripts/restore_local_modules.py` analiza los imports de los generadores.
- Si un módulo local `scripts/<nombre>.py` no está presente pero sí existe en el
  historial Git, restaura la revisión histórica más reciente.
- El análisis es recursivo.
- Tras la restauración se compilan todos los `scripts/*.py`.
- Finalmente el workflow importa realmente los cuatro generadores principales;
  un módulo faltante falla ahí, antes de descargar fuentes o construir XMLTV.

## DW

Se conserva la corrección de v0.2.33:

```text
Deutsche.Welle.cl -> cl/canales/deutsche-welle-espanol
```

Sin offsets manuales; mi.tv se interpreta como UTC y se convierte a
`America/Guayaquil`.

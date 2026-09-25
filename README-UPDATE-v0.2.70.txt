EPG MrG v0.2.70 — Ecuador TV + cabecera XML canónica
======================================================

Corrección sobre v0.2.69
-------------------------
GitHub Actions fallaba en scripts/validate_outputs.py con:
  RuntimeError: Cabecera XML inesperada en public/ec.xml.

Causa
-----
Los overlays de Ecuador TV y TC Televisión reserializaban el XML con lxml.
Aunque el XML era válido, lxml generaba una declaración equivalente pero no
idéntica a la cabecera canónica exigida por el proyecto.

Solución
--------
Los escritores XML de:
- scripts/add_ecuadortv_epg.py
- scripts/add_tc_epg.py

construyen ahora manualmente este prefijo exacto:

<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tv SYSTEM "xmltv.dtd">

<tv generator-info-name="none" generator-info-url="none">

Se mantiene además la identidad exacta entre XML y GZIP.

Ecuador TV
----------
Se conserva íntegramente la corrección v0.2.69:
- Fuente primaria: https://www.ecuadortv.ec/programas
- ID: Canal.Ecuador.TV.ec
- Jueves/lunes-viernes 19:00-20:00: Noticias 7 Estelar
- Si un programa previo cruza las 19:00, se recorta al inicio del bloque.

Pruebas locales realizadas
---------------------------
- py_compile de los tres scripts del overlay: OK
- cabecera exacta en add_ecuadortv_epg.py: OK
- cabecera exacta en add_tc_epg.py: OK
- ec.xml.gz descomprime byte a byte al mismo XML: OK
- regresión 24-09-2026:
    18:30-19:00 Esta es mi canción
    19:00-20:00 Noticias 7 Estelar
  OK

Base
----
Continúa sobre v0.2.68/v0.2.69 sin modificar los IDs, fuentes ni lógica estable
de los demás canales. La versión global pasa a 0.2.70.

Cómo aplicar
------------
1. Descomprimir sobre la raíz del repositorio y reemplazar los archivos.
2. Commit/push.
3. Ejecutar el workflow "Actualizar EPG Ecuador y Latinoamérica".
4. Confirmar que validate_outputs.py ya no reporte "Cabecera XML inesperada".

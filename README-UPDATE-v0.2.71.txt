EPG MrG v0.2.71 — Ecuador TV desde API oficial

Cambio principal
===============
La parrilla de Ecuador TV deja de obtenerse desde el texto/DOM renderizado y deja de
usar bloques horarios manuales. La propia página https://www.ecuadortv.ec/programas
consume esta fuente oficial:

  https://www.ecuadortv.ec/api/schedule/today

v0.2.71 usa ese endpoint como fuente primaria para el día local actual de Ecuador.

Comportamiento
==============
- Descarga /api/schedule/today con requests y cabeceras de navegador.
- Si el servidor exige una sesión de navegador, usa Selenium únicamente como
  fallback para ejecutar fetch() contra EL MISMO endpoint oficial.
- Interpreta el JSON de forma flexible (HH:MM, HHhMM, HHMM, startHour/startMinute,
  minutos desde medianoche, ISO datetime, etc.).
- Antes de modificar la EPG exige al menos 8 programas y una cobertura mínima de 8 h.
- Si la respuesta no supera esa validación, el workflow falla en lugar de publicar
  una parrilla posiblemente incorrecta.
- Solo reemplaza el día que entrega /today. Los demás días quedan intactos desde la
  guía base y se corregirán automáticamente cuando pasen a ser "today" en ejecuciones
  posteriores.
- Se elimina el fallback provisional que insertaba manualmente Noticias 7.
- Se conserva la cabecera XMLTV canónica exigida por scripts/validate_outputs.py.
- Se actualizan ec.xml y latam.xml cuando ambos existen.

Diagnóstico visible en GitHub Actions
=====================================
El script imprime estas líneas:

  ECUADORTV_API_SOURCE
  ECUADORTV_API_FETCH
  ECUADORTV_API_PARSER
  ECUADORTV_API_ROWS

ECUADORTV_API_ROWS permite comprobar exactamente qué horarios y títulos fueron
leídos desde la API antes de sustituir la programación del canal.

Validaciones locales realizadas
===============================
- py_compile: OK
- self-test del parser JSON: OK
- 19:00 Noticias 7 Estelar: OK
- 20:00 Ficción Latina: OK
- 21:00 Fanático: OK
- 22:00 Un Café con JJ: OK
- 22:30 Estas Secretarias: OK
- reemplazo completo del día: OK
- cabecera XML exacta: OK
- ec.xml.gz/latam.xml.gz idénticos a sus XML: OK

Instalación
===========
Subir el contenido del ZIP a la raíz del repositorio reemplazando archivos
coincidentes. Luego ejecutar "Actualizar EPG Ecuador y Latinoamérica".

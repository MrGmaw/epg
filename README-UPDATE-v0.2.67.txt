EPG MrG v0.2.67 — TC Televisión oficial
=============================================

Objetivo
--------
Usar https://tctelevision.com/programacion/ como fuente primaria de la EPG de
TC Televisión (ID XMLTV: Canal.TC.Televisión.ec), sin modificar la reproducción
del canal ni el resto de la guía.

Archivos del overlay
--------------------
VERSION
requirements.txt
scripts/add_tc_epg.py
scripts/patch_dw_mitv.py

Cómo aplicar
------------
1. Descomprimir sobre la raíz del repositorio EPG MrG v0.2.66.
2. Reemplazar los archivos coincidentes; no borrar los demás archivos.
3. Commit/push a main.
4. Ejecutar "Actualizar EPG Ecuador y Latinoamérica" en GitHub Actions.
5. Revisar public/latam-status.json (o epg-data/latam-status.json):
   - version = 0.2.67
   - tc_television_epg.source = https://tctelevision.com/programacion/
   - tc_television_epg.official_dates debe listar los días aceptados.
   - programme_counts["Canal.TC.Televisión.ec"] debe ser > 0.

Diseño de seguridad
-------------------
La página oficial de TC carga la parrilla mediante JavaScript. v0.2.67 utiliza
Selenium + Chrome headless para leer la vista renderizada. Solo sustituye días
con al menos 8 programas y una extensión de al menos 10 horas. Si no consigue
leer ningún día oficial, conserva la parrilla previa de TC y registra el error
en tc_television_epg.errors, sin romper la actualización de los demás canales.

La reproducción de TC (Dailymotion x7wijay / integración del player) permanece
totalmente separada de este cambio.

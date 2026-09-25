EPG MrG v0.2.69 — Ecuador TV oficial
====================================

Objetivo
--------
Corregir la EPG de Ecuador TV (ID XMLTV: Canal.Ecuador.TV.ec) tomando como
fuente primaria https://www.ecuadortv.ec/programas y evitando que fuentes
secundarias sobrescriban bloques informativos con horario oficial.

Corrección verificada que motivó esta versión
---------------------------------------------
Para jueves 24-09-2026, Ecuador TV publica Noticias 7 Estelar de 19:00 a 20:00.
La guía previa mostraba "Esta es mi canción" en ese bloque.

La ficha oficial de Noticias 7 publica además estos horarios:
- Lunes a viernes 07:00-08:30: Noticias 7 Matinal
- Lunes a viernes 12:00-12:03: Micro Informativo
- Lunes a viernes 12:30-13:30: Noticias 7 Central
- Lunes a viernes 19:00-20:00: Noticias 7 Estelar
- Sábados y domingos 11:00-11:15: Noticias 7 Resumen Nacional
- Domingos 10:30-11:00: Noticias 7 Internacional
Fuente: https://www.ecuadortv.ec/programas/noticias-7

Estrategia de seguridad
-----------------------
1. Se intenta leer la parrilla semanal oficial renderizada con Selenium/Chrome.
2. Un día completo solo reemplaza la guía previa si contiene >= 8 programas,
   cubre >= 9 horas y, de lunes a viernes, incluye expresamente
   Noticias 7 Estelar a las 19:00.
3. Si la vista oficial completa no puede leerse, NO se borra el resto del día:
   se conserva la guía previa y se sustituyen únicamente los bloques de
   Noticias 7 cuyo horario está publicado por Ecuador TV.
4. Cuando un programa previo cruza uno de esos bloques, se divide antes/después
   para no eliminar programación ajena al intervalo oficial.
5. Se actualizan ec.xml y latam.xml cuando ambos existen.

Base y compatibilidad
---------------------
Esta actualización continúa sobre v0.2.68 y conserva íntegramente la capa
oficial de TC Televisión. El componente TC sigue identificado internamente como
v0.2.68; la versión global del repositorio pasa a 0.2.69.

Archivos del overlay
--------------------
VERSION
requirements.txt
scripts/add_tc_epg.py
scripts/add_ecuadortv_epg.py
scripts/patch_dw_mitv.py

Cómo aplicar
------------
1. Descomprimir sobre la raíz del repositorio EPG MrG (reemplazar archivos).
2. Commit/push a main.
3. Ejecutar "Actualizar EPG Ecuador y Latinoamérica" en GitHub Actions.
4. Revisar public/status.json y public/latam-status.json:
   - version = 0.2.69
   - ecuador_tv_epg.channel_id = Canal.Ecuador.TV.ec
   - ecuador_tv_epg.source = https://www.ecuadortv.ec/programas
   - ecuador_tv_epg.news_schedule_source = https://www.ecuadortv.ec/programas/noticias-7
5. Verificar en ec.xml/latam.xml que un día laborable tenga:
   19:00-20:00 -> Noticias 7 Estelar

No modifica
-----------
- IDs XMLTV.
- URLs de reproducción de canales.
- La lógica estable de STAR TVE, MakroDigital, TC Televisión, ESPN, Miami,
  Asamblea, El Gourmet u otros canales.

EPG MrG — diagnóstico de fuente real de Ecuador TV
==================================================

Objetivo
--------
Identificar la petición XHR/fetch que entrega los valores visibles en:
https://www.ecuadortv.ec/programas

Este paquete NO constituye la corrección final de Ecuador TV. Añade un diagnóstico
al scraper v0.2.70 para que, al cargar la página con Chrome en GitHub Actions,
inspeccione las respuestas de red y muestre líneas con este prefijo:

  ECUADORTV_NETWORK_CANDIDATE

Qué necesito del Action
------------------------
Ejecuta el workflow normalmente y copia únicamente las líneas que comiencen por:

  ECUADORTV_NETWORK_CANDIDATE

Con esa URL/respuesta se puede sustituir el scraping/hardcode actual por la fuente
real que alimenta las tarjetas de la página oficial.

Nota
----
Los nombres observados el 24-09-2026 se usan únicamente como firmas para localizar
la respuesta correcta en la red. No se usan para generar la EPG.

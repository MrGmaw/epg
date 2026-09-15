# EPG MrG v0.2.65 — STAR TVE multi-fallback

Hotfix sobre v0.2.64.

- GatoTV sigue como fuente primaria.
- Fallback fresco: AmericaTVListings Colombia (`America/Bogota`, UTC-5).
- Si AmericaTVListings bloquea al runner, se intenta la misma URL mediante Jina Reader.
- La caché previa solo completa fechas exactas, sin desplazar días ni offsets.
- Si no hay ninguna fuente ni caché, STAR TVE publica bloques transparentes `Programación temporalmente no disponible` en lugar de abortar todo el workflow.
- `manual_offset_minutes = 0`.
- No modifica ESPN 1–7 ni los demás canales.

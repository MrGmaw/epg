# EPG MrG v0.2.25 — 17 de agosto de 2026

## Motivo

Después de aplicar v0.2.24, TC Televisión dejó de bloquear `latam.xml`, pero la
misma ejecución avanzó al siguiente canal heredado de EPGShare y falló con:

`El canal Canal.Gamavisión.ec no tiene programación en ec.xml.`

Esto confirmó que el problema no era exclusivo de TC: EPGShare puede conservar
los canales en `ec.xml` pero no aportar emisiones dentro de la ventana vigente.

## Corrección estructural

La resiliencia deja de ser exclusiva de TC y pasa a proteger los canales de
LATAM que todavía dependen de EPGShare:

- `Canal.TC.Televisión.ec`
- `Canal.Gamavisión.ec`
- `Canal.RTS.ec`
- `Canal.Ecuador.TV.ec`
- `Ecuavisa.ec` (después de la normalización del generador base)

Para cada uno se mantiene esta prioridad:

1. EPGShare, si contiene programación vigente suficiente.
2. GatoTV del mismo canal, interpretado como horario de Ecuador
   (`America/Guayaquil`) y sin offsets manuales.
3. Última `epg-data/ec.xml` válida, solo cuando existe una plantilla del mismo
   día de semana con programación suficiente.

Si las tres rutas fallan, el workflow se detiene de forma explícita.

## GatoTV de respaldo

- TC Televisión: `https://www.gatotv.com/canal/tc_television`
- Gamavisión: `https://www.gatotv.com/canal/gamavision`
- RTS: `https://www.gatotv.com/canal/rts`
- Ecuador TV: `https://www.gatotv.com/canal/ecuador_tv`
- Ecuavisa nacional: `https://www.gatotv.com/canal/ecuavisa_ecuador`

## Pruebas

Se verificaron de forma determinista, sin red:

- todos los canales vigentes en EPGShare: GatoTV no se consulta;
- TC vigente con Gamavisión y RTS vacíos: solo Gamavisión y RTS pasan a GatoTV;
- caída simulada de GatoTV: TC, Gamavisión, RTS, Ecuador TV y Ecuavisa usan la
  caché del mismo día de semana cuando está disponible;
- carga del wrapper completo `build_epg.py --self-test` con Python 3.13;
- compilación sintáctica de los dos scripts modificados.

## STAR TVE

No se modifica `scripts/build_latam_epg.py`. STAR TVE conserva exactamente la
lógica validada de v0.2.23: AM/PM localizada de GatoTV como primaria en
`America/Guayaquil`; vista 24 h como respaldo `Atlantic/Canary ->
America/Guayaquil`; sin offset manual y sin mezclar vistas.

## Archivos funcionales modificados respecto de v0.2.24

- `VERSION` -> `0.2.25`
- `scripts/build_epg.py`
- `scripts/tc_resilient.py`

El nombre `tc_resilient.py` se conserva para que la actualización sea mínima y
compatible con v0.2.24, aunque desde esta versión el módulo protege varios
canales EPGShare.

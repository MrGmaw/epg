# EPG MrG v0.2.55 — Asamblea Nacional TVL

Base válida: **v0.2.54**.

## Nuevo canal

- `channel-id`: `AsambleaNacional.ec`
- Nombre: `Asamblea Nacional TVL` / `TVL - Televisión Legislativa`
- Fuente oficial: `https://tvl.asambleanacional.gob.ec/`
- Zona fuente: `America/Guayaquil`
- Zona XMLTV: `America/Guayaquil`
- Offset manual: `0`
- Posición: último canal de `latam.xml`
- Total esperado: **36 canales**

## Política de programación

1. Fuente primaria: parrilla semanal oficial de TVL.
2. El parser localiza las pestañas Lunes-Domingo y extrae bloques `HH:MM-HH:MM + título` sin depender de una sola clase CSS.
3. Requiere los 7 días y una cobertura semanal mínima antes de aceptar la parrilla.
4. Si TVL no entrega una parrilla utilizable, intenta reconstruir la semana desde la última `epg-data/latam.xml` válida que ya contenga `AsambleaNacional.ec`.
5. En la primera ejecución, si la fuente oficial falla y aún no existe caché del nuevo canal, el build aborta en vez de publicar una guía inventada o incompleta.

## Control horario

La web oficial publica los horarios en hora continental de Ecuador. No existe conversión ni offset manual. Control determinista incluido: jueves `09:00-09:45 Chakiñán` -> `20260910090000 -0500` a `20260910094500 -0500`.

## Cambio requerido en GitHub Actions

El workflow vigente de v0.2.54 valida exactamente 35 canales. Por esa razón este paquete incluye `APLICAR-v0.2.55.py`, que modifica `.github/workflows/actualizar-epg.yml` de forma puntual e idempotente para:

- incluir el self-test y la ejecución de `scripts/add_asamblea_epg.py` después de STAR TVE;
- elevar el conteo esperado de 35 a 36;
- incluir `AsambleaNacional.ec` entre los IDs obligatorios;
- validar zona horaria, offset y cantidad mínima de programas;
- actualizar el texto de `epg-data/README.md` a 36 canales.

Ejecutar desde la raíz del repositorio, una sola vez:

```bash
python APLICAR-v0.2.55.py
```

Después revisar los cambios, hacer commit/push y ejecutar GitHub Actions.

## Pruebas realizadas

- `scripts/add_asamblea_epg.py --self-test`: OK.
- `python -m py_compile`: OK.
- Integración simulada 35 -> 36 canales: OK.
- `AsambleaNacional.ec` último en orden canónico: OK.
- XMLTV `start/stop` en `-0500`: OK.
- `latam.xml.gz` byte a byte equivalente a `latam.xml`: OK.
- `latam-status.json.version=0.2.55`, `channels=36`: OK.
- Patcher del workflow probado contra los bloques vigentes de v0.2.54: OK.

No se incluye ningún directorio `__pycache__` ni archivo `.pyc`.

#!/usr/bin/env python3
"""Hotfix v0.2.50: parrilla semanal de emergencia para RTS Ecuador.

Conserva la prioridad normal de ``tc_resilient``:
EPGShare -> GatoTV -> epg-data/ec.xml. Añade un CUARTO nivel exclusivamente
para ``Canal.RTS.ec`` cuando las tres rutas anteriores quedan agotadas.

La parrilla se expresa directamente en ``America/Guayaquil`` y se basa en la
programación reciente publicada por GatoTV en septiembre de 2026. No se
aplican offsets manuales.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from lxml import etree

CHANNEL_ID = "Canal.RTS.ec"
SOURCE_MODE = "bundled-weekly-grid"
SOURCE_REVISION = "gatotv-ecuador-rts-week-2026-09-r1"
SOURCE_TIMEZONE = "America/Guayaquil"
MIN_DAILY_PROGRAMMES = 12

# Referencias utilizadas para construir el ciclo semanal. La parrilla laboral
# se repite en los martes 01/09 y 08/09 y coincide con la vista actual del
# miércoles 09/09. Sábado/domingo proceden de 05/09 y 06/09.
REFERENCE_DATES = {
    0: "weekday-pattern-2026-09-01_08_09",
    1: "2026-09-08",
    2: "2026-09-09",
    3: "weekday-pattern-2026-09-01_08_09",
    4: "weekday-pattern-2026-09-01_08_09",
    5: "2026-09-05",
    6: "2026-09-06",
}

# (minuto_del_día, título). Los finales se obtienen del inicio del siguiente
# espacio mediante ``instantiate_weekly_schedule`` del generador base.
WEEKDAY = (
    (0, "Copa"),
    (30, "Nueva novia"),
    (60, "The Walking Dead"),
    (120, "Lucha libre"),
    (240, "Ecuador Multicolor"),
    (300, "Educa"),
    (360, "La noticia"),
    (420, "El despertar de La Noticia"),
    (480, "La noticia"),
    (540, "La noticia en la comunidad"),
    (630, "Noticias de la mañana"),
    (720, "Mujer, casos de la vida real"),
    (780, "Elif"),
    (840, "La Rosa de Guadalupe"),
    (900, "Laura"),
    (960, "Legado de Amor"),
    (1020, "Cuando los ángeles caen"),
    (1080, "Caso Cerrado"),
    (1140, "Esposa por obligación"),
    (1200, "Combate"),
    (1320, "Corazón abandonado"),
    (1380, "La noticia"),
)

SATURDAY = (
    (0, "La noticia"),
    (60, "Copa"),
    (90, "Nueva novia"),
    (135, "The Walking Dead"),
    (180, "Lucha libre"),
    (300, "Ecuador Multicolor"),
    (360, "Educa"),
    (420, "La noticia"),
    (480, "Ranti ranti"),
    (540, "Beyblade Burst"),
    (570, "El show de la pantera rosa"),
    (600, "Una familia de diez"),
    (630, "La hora pico"),
    (660, "Reto cuatro elementos"),
    (780, "Hombre al agua"),
    (840, "Hombre al agua"),
    (900, "The Rookie"),
    (960, "Hudson & Rex"),
    (1020, "Los hombres de Paco"),
    (1080, "Cuando los ángeles caen"),
    (1140, "María la del Barrio"),
    (1200, "María la del Barrio"),
    (1260, "Caso Cerrado"),
    (1320, "Caso Cerrado"),
    (1380, "La Rosa de Guadalupe"),
)

SUNDAY = (
    (0, "María, la del barrio"),
    (60, "Caso Cerrado"),
    (120, "Caso Cerrado"),
    (180, "La Rosa de Guadalupe"),
    (240, "Lucha Libre TNA Impact"),
    (360, "El transportador"),
    (420, "Lucha libre"),
    (540, "Ranti ranti"),
    (600, "Cine de madrugada"),
    (720, "El diván"),
    (780, "Beyblade Burst"),
    (810, "El show de la pantera rosa"),
    (840, "Una familia de diez"),
    (900, "La hora pico"),
    (960, "Reto cuatro elementos"),
    (1080, "Una familia de diez"),
    (1110, "La hora pico"),
    (1140, "The Rookie"),
    (1200, "Hudson & Rex"),
    (1260, "Los hombres de Paco"),
    (1320, "Cuando los ángeles caen"),
    (1380, "María, la del barrio"),
)

WEEKLY_STARTS: tuple[tuple[tuple[int, str], ...], ...] = (
    WEEKDAY, WEEKDAY, WEEKDAY, WEEKDAY, WEEKDAY, SATURDAY, SUNDAY
)


def _weekly_schedule(epg: Any):
    return [
        [epg.ScheduleItem(minute=minute, title=title) for minute, title in day]
        for day in WEEKLY_STARTS
    ]


def build_programmes(epg: Any, start_date: date, days: int) -> list[etree._Element]:
    """Construye XMLTV local de emergencia para RTS."""
    requested_days = max(1, int(days))
    programmes = epg.instantiate_weekly_schedule(
        _weekly_schedule(epg), CHANNEL_ID, start_date, requested_days
    )
    nodes = [epg.make_programme(item) for item in programmes]

    counts: dict[date, int] = {}
    for item in programmes:
        local_start = item.start.astimezone(epg.TZ)
        counts[local_start.date()] = counts.get(local_start.date(), 0) + 1
    for offset in range(requested_days):
        target = start_date + timedelta(days=offset)
        if counts.get(target, 0) < MIN_DAILY_PROGRAMMES:
            raise RuntimeError(
                f"RTS hotfix: cobertura insuficiente para {target.isoformat()}: "
                f"{counts.get(target, 0)} emisiones."
            )
    if len(nodes) < MIN_DAILY_PROGRAMMES:
        raise RuntimeError("RTS hotfix: la plantilla semanal no produjo programación suficiente.")
    return nodes


def _is_expected_exhaustion(exc: RuntimeError) -> bool:
    text = str(exc)
    return (
        "RTS" in text
        and "no tiene programación utilizable" in text
        and "EPGShare" in text
        and "GatoTV" in text
        and "epg-data" in text
    )


def install(tc_resilient: Any, epg: Any) -> None:
    """Instala el cuarto fallback para RTS sin alterar los demás canales."""
    if getattr(tc_resilient, "_rts_weekly_hotfix_installed", False):
        return

    original = tc_resilient._repair_channel

    def repaired(
        epg_module: Any,
        root: etree._Element,
        config: Any,
        cache_xml: Path,
        start_date: date,
        days: int,
    ) -> None:
        try:
            return original(epg_module, root, config, cache_xml, start_date, days)
        except RuntimeError as exc:
            if config.channel_id != CHANNEL_ID or not _is_expected_exhaustion(exc):
                raise

            nodes = build_programmes(epg_module, start_date, max(1, days))
            tc_resilient._replace_channel(root, config, nodes)
            tc_resilient._set_result(config, SOURCE_MODE, len(nodes))
            record = tc_resilient.LAST_RESULTS.get(config.channel_id, {})
            record.update(
                {
                    "fallback": "bundled RTS weekly grid",
                    "fallback_revision": SOURCE_REVISION,
                    "fallback_timezone": SOURCE_TIMEZONE,
                    "reference_dates": dict(REFERENCE_DATES),
                    "manual_offset_minutes": 0,
                }
            )
            epg_module.warn(
                "RTS: EPGShare, GatoTV y epg-data agotados; "
                f"se activa parrilla semanal local de emergencia {SOURCE_REVISION} "
                f"({len(nodes)} emisiones, {SOURCE_TIMEZONE}, offset manual 0)."
            )
            return None

    tc_resilient._repair_channel = repaired
    tc_resilient._rts_weekly_hotfix_original = original
    tc_resilient._rts_weekly_hotfix_installed = True


def self_test(epg: Any, tc_resilient: Any) -> None:
    """Fuerza las tres fallas y comprueba el miércoles 09/09/2026."""
    install(tc_resilient, epg)
    test_date = date(2026, 9, 9)
    root = etree.Element("tv")

    # tc_resilient usa un objeto de configuración para RTS. Buscamos el nombre
    # de forma tolerante para no acoplar el hotfix a una sola revisión.
    config = getattr(tc_resilient, "RTS", None)
    if config is None:
        for value in vars(tc_resilient).values():
            if getattr(value, "channel_id", None) == CHANNEL_ID:
                config = value
                break
    assert config is not None, "No se encontró configuración RTS en tc_resilient"
    root.append(tc_resilient._basic_channel(config))

    original_scraper = epg.scrape_gatotv_range
    try:
        def fail_gatotv(*_args, **_kwargs):
            raise RuntimeError("fallo GatoTV simulado")

        epg.scrape_gatotv_range = fail_gatotv
        tc_resilient._repair_channel(
            epg,
            root,
            config,
            Path("/cache-rts-inexistente.xml"),
            test_date,
            1,
        )
    finally:
        epg.scrape_gatotv_range = original_scraper

    record = tc_resilient.LAST_RESULTS.get(CHANNEL_ID, {})
    assert record.get("source") == SOURCE_MODE, record
    assert record.get("manual_offset_minutes") == 0, record

    programmes = [
        node for node in root.findall("programme") if node.get("channel") == CHANNEL_ID
    ]
    assert len(programmes) >= MIN_DAILY_PROGRAMMES, len(programmes)

    expected = {
        "20260909060000 -0500": "La noticia",
        "20260909090000 -0500": "La noticia en la comunidad",
        "20260909120000 -0500": "Mujer, casos de la vida real",
        "20260909190000 -0500": "Esposa por obligación",
        "20260909200000 -0500": "Combate",
        "20260909220000 -0500": "Corazón abandonado",
        "20260909230000 -0500": "La noticia",
    }
    observed = {node.get("start", ""): (node.findtext("title") or "") for node in programmes}
    for start, title in expected.items():
        assert observed.get(start) == title, (start, observed.get(start), title)

    assert len(WEEKLY_STARTS) == 7
    assert all(len(day) >= MIN_DAILY_PROGRAMMES for day in WEEKLY_STARTS)
    print(
        "Prueba RTS v0.2.50 correcta: cuarto fallback semanal local; "
        "miércoles 06:00/09:00/12:00/19:00/20:00/22:00/23:00 validado; "
        "offset manual 0.",
        flush=True,
    )

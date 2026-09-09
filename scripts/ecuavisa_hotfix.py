#!/usr/bin/env python3
"""Hotfix v0.2.51: parrilla semanal de emergencia para Ecuavisa Ecuador.

Conserva la prioridad normal de ``tc_resilient``:
EPGShare -> GatoTV -> epg-data/ec.xml. Añade un CUARTO nivel exclusivamente
para ``Ecuavisa.ec`` cuando las tres rutas anteriores quedan agotadas.

La parrilla está expresada directamente en ``America/Guayaquil``. Los anclajes
laborables 06:55 Contacto Directo, 13:00 Televistazo y 19:00 Televistazo están
corroborados por la programación oficial vigente de Ecuavisa; la secuencia
restante se normalizó a partir de GatoTV (septiembre de 2026). No hay offsets
manuales.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from lxml import etree

CHANNEL_ID = "Ecuavisa.ec"
SOURCE_MODE = "bundled-weekly-grid"
SOURCE_REVISION = "ecuavisa-ecuador-week-2026-09-r1"
SOURCE_TIMEZONE = "America/Guayaquil"
MIN_DAILY_PROGRAMMES = 10

REFERENCE_DATES = {
    0: "weekday-pattern-2026-09-07_08 + official anchors",
    1: "2026-09-08 + official anchors",
    2: "weekday-pattern-2026-09-08 + official anchors (09 page empty)",
    3: "weekday-pattern-2026-09-03_08 + official anchors",
    4: "weekday-pattern-2026-09-04_08 + official anchors",
    5: "2026-09-05",
    6: "2026-09-06",
}

# Horario laboral local de Ecuador. GatoTV 08/09 en vista AM/PM coincide con
# los anclajes oficiales actuales de Ecuavisa: Contacto Directo 06:55,
# Televistazo 13:00 y Televistazo 19:00. La franja 23:00-00:00 se deja como
# "Programación Ecuavisa" porque la página fuente reciente queda truncada al
# final de la noche; es preferible un rótulo neutro a inventar un título.
WEEKDAY = (
    (0, "Telenovela"),
    (350, "Televistazo en la comunidad"),        # 05:50
    (415, "Contacto directo en Televistazo"),    # 06:55
    (450, "Televistazo en la comunidad"),        # 07:30
    (570, "En contacto"),                         # 09:30
    (780, "Televistazo II"),                      # 13:00
    (840, "Háckers del espectáculo"),             # 14:00
    (930, "Sorpresas del destino"),               # 15:30
    (990, "Demanda de amor"),                     # 16:30
    (1050, "Destilando amor"),                    # 17:30
    (1140, "Televistazo Estelar"),                # 19:00
    (1260, "Leyla"),                              # 21:00
    (1320, "El otro lado del amor"),              # 22:00
    (1380, "Programación Ecuavisa"),              # 23:00
)

# Sábado 05/09/2026, normalizado a hora Ecuador desde la vista AM/PM.
SATURDAY = (
    (0, "Piso 17"),
    (60, "Telenovela"),
    (360, "Así pasa"),
    (405, "Combo amarillo"),
    (420, "A Team"),
    (480, "Ventas Mundo TV"),
    (540, "Tventas"),
    (600, "Pan Nuestro"),
    (630, "Si se puede"),
    (690, "Historias de la vírgen morena"),
    (750, "Más sabe el Diablo"),
    (840, "Carita de Ángel"),
    (900, "Largometraje"),
    (1050, "Previa - Liga Ecuabet"),
    (1080, "Liga Ecuabet"),
    (1200, "Televistazo"),
    (1230, "Largometraje"),
    (1335, "Largometraje"),
)

# Domingo 06/09/2026, normalizado a hora Ecuador desde la vista AM/PM.
SUNDAY = (
    (0, "Largometraje"),                         # continuación 22:15 sábado
    (15, "El auto fantástico"),
    (90, "Combo amarillo"),
    (360, "El Increible Hulk"),
    (420, "A Team"),
    (480, "Vive simple Colombia"),
    (510, "Ser"),
    (570, "Hacia un Nuevo Estilo de Vida"),
    (630, "Panorama internacional"),
    (690, "Políticamente correcto"),
    (750, "Esta Semana con Pedro Jiménez"),
    (810, "Entre flashes"),
    (840, "El auto fantástico"),
    (960, "Largometraje"),
    (1080, "Largometraje"),
    (1200, "Televistazo Dominical"),
    (1260, "Largometraje"),
    (1395, "Largometraje"),
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
                f"Ecuavisa hotfix: cobertura insuficiente para {target.isoformat()}: "
                f"{counts.get(target, 0)} emisiones."
            )
    if len(nodes) < MIN_DAILY_PROGRAMMES:
        raise RuntimeError("Ecuavisa hotfix: la plantilla semanal no produjo programación suficiente.")
    return nodes


def _is_expected_exhaustion(exc: RuntimeError) -> bool:
    text = str(exc)
    return (
        "Ecuavisa" in text
        and "no tiene programación utilizable" in text
        and "EPGShare" in text
        and "GatoTV" in text
        and "epg-data" in text
    )


def install(tc_resilient: Any, epg: Any) -> None:
    """Instala el cuarto fallback para Ecuavisa sin alterar otros canales."""
    if getattr(tc_resilient, "_ecuavisa_weekly_hotfix_installed", False):
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
                    "fallback": "bundled Ecuavisa weekly grid",
                    "fallback_revision": SOURCE_REVISION,
                    "fallback_timezone": SOURCE_TIMEZONE,
                    "reference_dates": dict(REFERENCE_DATES),
                    "manual_offset_minutes": 0,
                    "official_anchors": {
                        "Contacto directo en Televistazo": "06:55",
                        "Televistazo II": "13:00",
                        "Televistazo Estelar": "19:00",
                    },
                }
            )
            epg_module.warn(
                "Ecuavisa: EPGShare, GatoTV y epg-data agotados; "
                f"se activa parrilla semanal local de emergencia {SOURCE_REVISION} "
                f"({len(nodes)} emisiones, {SOURCE_TIMEZONE}, offset manual 0)."
            )
            return None

    tc_resilient._repair_channel = repaired
    tc_resilient._ecuavisa_weekly_hotfix_original = original
    tc_resilient._ecuavisa_weekly_hotfix_installed = True


def self_test(epg: Any, tc_resilient: Any) -> None:
    """Fuerza las tres fallas y comprueba los anclajes del miércoles 09/09/2026."""
    install(tc_resilient, epg)
    test_date = date(2026, 9, 9)
    root = etree.Element("tv")

    config = getattr(tc_resilient, "ECUAVISA", None)
    if config is None:
        for value in vars(tc_resilient).values():
            if getattr(value, "channel_id", None) == CHANNEL_ID:
                config = value
                break
    assert config is not None, "No se encontró configuración Ecuavisa en tc_resilient"
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
            Path("/cache-ecuavisa-inexistente.xml"),
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
        "20260909065500 -0500": "Contacto directo en Televistazo",
        "20260909130000 -0500": "Televistazo II",
        "20260909140000 -0500": "Háckers del espectáculo",
        "20260909190000 -0500": "Televistazo Estelar",
        "20260909210000 -0500": "Leyla",
    }
    actual = {
        node.get("start"): (node.findtext("title") or "")
        for node in programmes
    }
    for start, title in expected.items():
        assert actual.get(start) == title, (start, actual.get(start), title)

    # Cobertura semanal y zona horaria XMLTV.
    week = build_programmes(epg, test_date, 7)
    assert len(week) >= 90, len(week)
    for node in week:
        assert (node.get("start") or "").endswith(" -0500"), node.get("start")
        assert (node.get("stop") or "").endswith(" -0500"), node.get("stop")

    print(
        "Ecuavisa hotfix self-test OK: "
        f"{len(programmes)} emisiones miércoles, {len(week)} en 7 días; "
        "06:55 Contacto Directo, 13:00 Televistazo, 19:00 Televistazo Estelar."
    )

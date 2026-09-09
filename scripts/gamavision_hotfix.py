#!/usr/bin/env python3
"""Hotfix v0.2.49: parrilla semanal de emergencia para Gamavisión.

La capa histórica ``tc_resilient`` conserva la prioridad normal:
EPGShare -> GatoTV -> epg-data/ec.xml. Este módulo añade UN CUARTO nivel,
exclusivamente para ``Canal.Gamavisión.ec``, cuando las tres fuentes anteriores
fallan.

La parrilla está expresada directamente en ``America/Guayaquil`` y fue
normalizada a partir de la programación reciente publicada por GatoTV para la
semana del 3 al 9 de septiembre de 2026. No se aplican offsets manuales.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from lxml import etree

CHANNEL_ID = "Canal.Gamavisión.ec"
SOURCE_MODE = "bundled-weekly-grid"
SOURCE_REVISION = "gatotv-ecuador-week-2026-09-03_09-r1"
SOURCE_TIMEZONE = "America/Guayaquil"
MIN_DAILY_PROGRAMMES = 10

# Referencias de la plantilla semanal. Lunes/martes/miércoles proceden de
# 2026-09-07/08/09; jueves/viernes/sábado/domingo de 2026-09-03/04/05/06.
REFERENCE_DATES = {
    0: "2026-09-07",
    1: "2026-09-08",
    2: "2026-09-09",
    3: "2026-09-03",
    4: "2026-09-04",
    5: "2026-09-05",
    6: "2026-09-06",
}

# (minuto_del_día, título). Los finales se obtienen del inicio del siguiente
# espacio mediante ``instantiate_weekly_schedule`` del generador base.
WEEKLY_STARTS: tuple[tuple[tuple[int, str], ...], ...] = (
    # Lunes. 00:00-00:30 es la continuación recortada de Verdades o mentiras
    # iniciada el domingo a las 23:00.
    (
        (0, "Verdades o mentiras"),
        (30, "Los Protagonistas"),
        (60, "Programación reprise"),
        (390, "Ojo clínico"),
        (420, "Encanto de Japón"),
        (450, "NCC ciencia, tecnología y cultura"),
        (480, "A fondo"),
        (540, "Pensadores positivos"),
        (570, "Sabroso y saludable"),
        (600, "Ventas Mundo TV"),
        (660, "Vidas y bebidas"),
        (690, "Con Olor a Región"),
        (720, "Complejamente"),
        (780, "Todo lo que sé"),
        (810, "Gamanoticias - Emisión central"),
        (840, "Los Protagonistas"),
        (870, "Bisturí"),
        (900, "Promo TV"),
        (1080, "Educa"),
        (1140, "Puro Teatro"),
        (1200, "Gamanoticias estelar"),
        (1260, "Virgencitas Ecuador"),
        (1320, "Córdova un general llamado Arrojo"),
        (1350, "Tiempo de vuelta"),
        (1380, "Empieza en casa"),
    ),
    # Martes.
    (
        (0, "Los Protagonistas"),
        (30, "Encanto de Japón"),
        (60, "Programación reprise"),
        (390, "Ojo clínico"),
        (420, "Encanto de Japón"),
        (450, "NCC Salud"),
        (480, "A fondo"),
        (540, "Pensadores positivos"),
        (570, "Promo TV"),
        (600, "Ventas Mundo TV"),
        (660, "Vidas y bebidas"),
        (690, "Promo TV"),
        (720, "Complejamente"),
        (780, "Todo lo que sé"),
        (810, "Gamanoticias - Emisión central"),
        (840, "Los Protagonistas"),
        (870, "Bisturí"),
        (900, "Tv Médica"),
        (960, "Educa"),
        (1020, "El camino del paciente"),
        (1050, "Promo TV"),
        (1140, "Puro Teatro"),
        (1200, "Gamanoticias estelar"),
        (1260, "Virgencitas Ecuador"),
        (1320, "Córdova un general llamado Arrojo"),
        (1350, "Tiempo de vuelta"),
        (1380, "Verdades o mentiras"),
    ),
    # Miércoles (control principal 2026-09-09).
    (
        (0, "Los Protagonistas"),
        (30, "Encanto de Japón"),
        (60, "Programación reprise"),
        (390, "Ojo clínico"),
        (420, "Encanto de Japón"),
        (450, "NCC Salud"),
        (480, "A fondo"),
        (540, "Pensadores positivos"),
        (570, "Promo TV"),
        (600, "Ventas Mundo TV"),
        (660, "Vidas y bebidas"),
        (690, "Promo TV"),
        (720, "Complejamente"),
        (780, "Todo lo que sé"),
        (810, "Gamanoticias - Emisión central"),
        (840, "Los Protagonistas"),
        (870, "Bisturí"),
        (900, "Tv Médica"),
        (960, "Educa"),
        (1020, "El camino del paciente"),
        (1050, "Promo TV"),
        (1140, "Puro Teatro"),
        (1200, "Gamanoticias estelar"),
        (1260, "Virgencitas Ecuador"),
        (1320, "Córdova un general llamado Arrojo"),
        (1350, "Tiempo de vuelta"),
        (1380, "Verdades o mentiras"),
    ),
    # Jueves.
    (
        (0, "Los Protagonistas"),
        (30, "Encanto de Japón"),
        (60, "Programación reprise"),
        (390, "Ojo clínico"),
        (420, "Encanto de Japón"),
        (450, "NCC ciencia, tecnología y cultura"),
        (480, "A fondo"),
        (540, "Pensadores positivos"),
        (570, "Sabroso y saludable"),
        (600, "Ventas Mundo TV"),
        (660, "Vidas y bebidas"),
        (690, "Con Olor a Región"),
        (720, "Complejamente"),
        (780, "Todo lo que sé"),
        (810, "Gamanoticias - Emisión central"),
        (840, "Los Protagonistas"),
        (870, "Bisturí"),
        (900, "Promo TV"),
        (1080, "Educa"),
        (1140, "Puro Teatro"),
        (1200, "Gamanoticias estelar"),
        (1260, "Virgencitas Ecuador"),
        (1320, "Córdova un general llamado Arrojo"),
        (1350, "Tiempo de vuelta"),
        (1380, "Memorias"),
    ),
    # Viernes.
    (
        (0, "Los Protagonistas"),
        (30, "Encanto de Japón"),
        (60, "Programación reprise"),
        (390, "Ojo clínico"),
        (420, "Encanto de Japón"),
        (450, "NCC iberoamérica en órbita"),
        (480, "A fondo"),
        (540, "Pensadores positivos"),
        (570, "Sabroso y saludable"),
        (600, "Ventas Mundo TV"),
        (660, "Vidas y bebidas"),
        (690, "Con Olor a Región"),
        (720, "Complejamente"),
        (780, "Todo lo que sé"),
        (810, "Gamanoticias - Emisión central"),
        (840, "Los Protagonistas"),
        (870, "Bisturí"),
        (900, "Promo TV"),
        (1080, "Educa"),
        (1140, "Puro Teatro"),
        (1200, "Gamanoticias estelar"),
        (1260, "Virgencitas Ecuador"),
        (1320, "Córdova un general llamado Arrojo"),
        (1350, "Tiempo de vuelta"),
        (1380, "Esta es mi canción"),
    ),
    # Sábado.
    (
        (0, "Los Protagonistas"),
        (30, "Encanto de Japón"),
        (60, "Programación reprise"),
        (390, "Ojo clínico"),
        (420, "Outlet TV"),
        (510, "Promo TV"),
        (540, "A la conquista del sabor"),
        (660, "Outlet TV"),
        (720, "Promo TV"),
        (780, "Fuerza latina"),
        (810, "Cultura.21"),
        (840, "Con Olor a Región"),
        (900, "Espejo retrovisor"),
        (960, "Bisturí"),
        (1020, "El reportero"),
        (1050, "Pensadores positivos"),
        (1080, "Tv Médica"),
        (1140, "Educación financiera"),
        (1170, "NCC Salud"),
        (1200, "Esta es mi canción"),
        (1260, "Especial - Miss Ecuador"),
        (1290, "Puro Teatro"),
        (1350, "Cada vida importa"),
        (1410, "Memorias"),
    ),
    # Domingo. 00:00-00:30 continúa Memorias del sábado.
    (
        (0, "Memorias"),
        (30, "RPM"),
        (60, "Programación reprise"),
        (390, "Ojo clínico"),
        (420, "Outlet TV"),
        (540, "Promo TV"),
        (600, "Ventas Mundo TV"),
        (1020, "Vidas y bebidas"),
        (1050, "Pensadores positivos"),
        (1080, "Complejamente"),
        (1140, "Educación financiera"),
        (1170, "Los Protagonistas"),
        (1200, "NCC Iberoamérica"),
        (1230, "NCC ciencia, tecnología y cultura"),
        (1260, "El actuario"),
        (1320, "El candidato ideal"),
        (1380, "Verdades o mentiras"),
    ),
)


def _weekly_schedule(epg: Any):
    return [
        [epg.ScheduleItem(minute=minute, title=title) for minute, title in day]
        for day in WEEKLY_STARTS
    ]


def build_programmes(epg: Any, start_date: date, days: int) -> list[etree._Element]:
    """Construye XMLTV local para Gamavisión a partir de la plantilla semanal."""
    requested_days = max(1, int(days))
    weekly = _weekly_schedule(epg)
    programmes = epg.instantiate_weekly_schedule(
        weekly,
        CHANNEL_ID,
        start_date,
        requested_days,
    )
    nodes = [epg.make_programme(item) for item in programmes]

    # Validación de cobertura por cada fecha pedida. Se usa la función histórica
    # de ventana si está disponible mediante tc_resilient durante la instalación;
    # aquí hacemos una comprobación independiente por fecha de inicio local.
    counts: dict[date, int] = {}
    for item in programmes:
        local_start = item.start.astimezone(epg.TZ)
        counts[local_start.date()] = counts.get(local_start.date(), 0) + 1
    for offset in range(requested_days):
        target = start_date + timedelta(days=offset)
        if counts.get(target, 0) < MIN_DAILY_PROGRAMMES:
            raise RuntimeError(
                f"Gamavisión hotfix: cobertura insuficiente para {target.isoformat()}: "
                f"{counts.get(target, 0)} emisiones."
            )
    if len(nodes) < MIN_DAILY_PROGRAMMES:
        raise RuntimeError("Gamavisión hotfix: la plantilla semanal no produjo programación suficiente.")
    return nodes


def _is_expected_exhaustion(exc: RuntimeError) -> bool:
    text = str(exc)
    return (
        "Gamavisión" in text
        and "no tiene programación utilizable" in text
        and "EPGShare" in text
        and "GatoTV" in text
        and "epg-data" in text
    )


def install(tc_resilient: Any, epg: Any) -> None:
    """Instala el cuarto fallback sin modificar los otros canales protegidos."""
    if getattr(tc_resilient, "_gamavision_weekly_hotfix_installed", False):
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
                    "fallback": "bundled Gamavisión weekly grid",
                    "fallback_revision": SOURCE_REVISION,
                    "fallback_timezone": SOURCE_TIMEZONE,
                    "reference_dates": dict(REFERENCE_DATES),
                    "manual_offset_minutes": 0,
                }
            )
            epg_module.warn(
                "Gamavisión: EPGShare, GatoTV y epg-data agotados; "
                f"se activa parrilla semanal local de emergencia {SOURCE_REVISION} "
                f"({len(nodes)} emisiones, {SOURCE_TIMEZONE}, offset manual 0)."
            )
            return None

    tc_resilient._repair_channel = repaired
    tc_resilient._gamavision_weekly_hotfix_original = original
    tc_resilient._gamavision_weekly_hotfix_installed = True


def self_test(epg: Any, tc_resilient: Any) -> None:
    """Prueba determinista: fuerza las tres fallas y verifica el miércoles ancla."""
    install(tc_resilient, epg)
    test_date = date(2026, 9, 9)  # miércoles
    root = etree.Element("tv")
    root.append(tc_resilient._basic_channel(tc_resilient.GAMAVISION))

    original_scraper = epg.scrape_gatotv_range
    try:
        def fail_gatotv(*_args, **_kwargs):
            raise RuntimeError("fallo GatoTV simulado")

        epg.scrape_gatotv_range = fail_gatotv
        tc_resilient._repair_channel(
            epg,
            root,
            tc_resilient.GAMAVISION,
            Path("/cache-gamavision-inexistente.xml"),
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
        "20260909133000 -0500": "Gamanoticias - Emisión central",
        "20260909190000 -0500": "Puro Teatro",
        "20260909200000 -0500": "Gamanoticias estelar",
        "20260909210000 -0500": "Virgencitas Ecuador",
        "20260909230000 -0500": "Verdades o mentiras",
    }
    observed: dict[str, str] = {}
    for node in programmes:
        title = node.findtext("title") or ""
        observed[node.get("start", "")] = title
    for start, title in expected.items():
        assert observed.get(start) == title, (start, observed.get(start), title)

    # La plantilla completa debe tener los siete días y suficiente densidad.
    assert len(WEEKLY_STARTS) == 7
    assert all(len(day) >= MIN_DAILY_PROGRAMMES for day in WEEKLY_STARTS)
    print(
        "Prueba Gamavisión v0.2.49 correcta: cuarto fallback semanal local; "
        "miércoles 13:30/19:00/20:00/21:00/23:00 validado; offset manual 0.",
        flush=True,
    )

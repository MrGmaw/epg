#!/usr/bin/env python3
"""Funciones compartidas para extraer mi.tv y convertir UTC a Ecuador.

mi.tv publica la parrilla mediante un endpoint HTML asíncrono. Las horas
recibidas se interpretan primero como UTC y luego se convierten a
``America/Guayaquil``. Este módulo sirve tanto a la guía histórica ``ec.xml``
(CNN en Español y NTN24) como a la nueva guía curada ``latam.xml``.
"""

from __future__ import annotations

import time as time_module
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

import build_epg_base as epg

MITV_SOURCE_TZ = ZoneInfo("UTC")
MITV_LOCAL_MAX_DAYS = 2
MITV_REQUEST_PAUSE_SECONDS = 1.0


def parse_mitv_page_utc(
    page: str,
    guide_date: date,
    channel_id: str,
) -> list[epg.Programme]:
    """Interpreta una fecha de mi.tv en UTC y devuelve horas de Ecuador."""

    soup = epg.BeautifulSoup(page, "lxml")
    items = soup.select("#listings > ul > li")
    if not items:
        raise RuntimeError(
            f"mi.tv {channel_id}: no se encontraron elementos en #listings."
        )

    starts: list[tuple[datetime, str, str | None]] = []
    source_event_date = guide_date
    previous_source_start: datetime | None = None

    for item in items:
        time_node = item.select_one("a > div.content > span.time")
        title_node = item.select_one("a > div.content > h2")
        if time_node is None or title_node is None:
            continue

        start_clock = epg.parse_mitv_clock(time_node.get_text(" ", strip=True))
        title = epg.normalize_text(title_node.get_text(" ", strip=True))
        if start_clock is None or not title:
            continue

        source_start = datetime.combine(
            source_event_date,
            start_clock,
            tzinfo=MITV_SOURCE_TZ,
        )
        if previous_source_start is not None and source_start < previous_source_start:
            source_event_date += timedelta(days=1)
            source_start = datetime.combine(
                source_event_date,
                start_clock,
                tzinfo=MITV_SOURCE_TZ,
            )

        description_node = item.select_one("a > div.content > p.synopsis")
        description = None
        if description_node is not None:
            description = epg.normalize_text(
                description_node.get_text(" ", strip=True)
            ) or None

        starts.append(
            (
                source_start.astimezone(epg.TZ),
                title,
                description,
            )
        )
        previous_source_start = source_start

    if len(starts) < 5:
        raise RuntimeError(
            f"mi.tv {channel_id}: solo se encontraron {len(starts)} emisiones "
            f"para {guide_date.isoformat()}."
        )

    programmes: list[epg.Programme] = []
    for index, (start, title, description) in enumerate(starts):
        stop = (
            starts[index + 1][0]
            if index + 1 < len(starts)
            else start + timedelta(hours=1)
        )
        if stop <= start:
            stop = start + timedelta(hours=1)
        programmes.append(
            epg.Programme(
                channel_id=channel_id,
                start=start,
                stop=stop,
                title=title,
                description=description,
            )
        )

    return programmes


def scrape_mitv_channel(
    *,
    country: str,
    slug: str,
    channel_id: str,
    start_date: date,
    local_days: int = MITV_LOCAL_MAX_DAYS,
    pause_seconds: float = MITV_REQUEST_PAUSE_SECONDS,
) -> tuple[list[epg.Programme], int]:
    """Descarga una ventana local completa desde el endpoint UTC de mi.tv.

    Para cubrir una fecha local de Ecuador se necesita también la siguiente
    fecha UTC, porque las 00:00–04:59 UTC pertenecen a la noche anterior en
    Ecuador. Por ello se solicita un día UTC adicional y después se recorta la
    salida a la ventana local requerida.
    """

    if country not in {"ar", "cl", "co"}:
        raise ValueError(f"País de mi.tv no soportado: {country!r}")
    if not 1 <= local_days <= MITV_LOCAL_MAX_DAYS:
        raise ValueError(
            f"local_days debe estar entre 1 y {MITV_LOCAL_MAX_DAYS}."
        )

    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=local_days)

    all_programmes: list[epg.Programme] = []
    loaded_source_days = 0
    # Un día UTC adicional completa la última noche local.
    for offset in range(local_days + 1):
        source_date = start_date + timedelta(days=offset)
        url = (
            f"https://mi.tv/{country}/async/channel/"
            f"{slug}/{source_date.isoformat()}/0"
        )
        try:
            page = epg.fetch_text(
                url,
                headers={
                    "Referer": f"https://mi.tv/{country}/canales/{slug}",
                    "Accept-Language": (
                        "es-AR,es;q=0.9,en;q=0.4"
                        if country == "ar"
                        else "es-CL,es;q=0.9,en;q=0.4"
                        if country == "cl"
                        else "es-CO,es;q=0.9,en;q=0.4"
                    ),
                },
            )
            day_programmes = parse_mitv_page_utc(page, source_date, channel_id)
        except (requests.RequestException, RuntimeError) as exc:
            epg.warn(f"mi.tv {channel_id} {source_date.isoformat()}: {exc}")
        else:
            all_programmes.extend(day_programmes)
            loaded_source_days += 1
            epg.log(
                f"mi.tv {channel_id}: fecha UTC {source_date.isoformat()}="
                f"{len(day_programmes)} emisiones."
            )
        finally:
            if pause_seconds > 0 and offset < local_days:
                time_module.sleep(pause_seconds)

    deduplicated: dict[tuple[str, str], epg.Programme] = {}
    for programme in all_programmes:
        if programme.start >= window_end or programme.stop <= window_start:
            continue
        key = (
            programme.start.isoformat(),
            epg.normalized_key(programme.title),
        )
        deduplicated.setdefault(key, programme)

    result = sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.title),
    )
    minimum_loaded_days = min(2, local_days + 1)
    if loaded_source_days < minimum_loaded_days or len(result) < 8:
        raise RuntimeError(
            f"mi.tv {channel_id}: no se obtuvo programación suficiente "
            f"para la ventana local solicitada (fechas UTC cargadas: "
            f"{loaded_source_days}/{local_days + 1})."
        )

    return result, loaded_source_days


def _sample_page(times_and_titles: list[tuple[str, str]]) -> str:
    items = "\n".join(
        """
        <li><a><div class="content">
          <span class="time">{clock}</span>
          <h2>{title}</h2>
          <p class="synopsis">Prueba de conversión horaria</p>
        </div></a></li>
        """.format(clock=clock, title=title)
        for clock, title in times_and_titles
    )
    return f'<div id="listings"><ul>{items}</ul></div>'


def self_test() -> None:
    """Pruebas deterministas sin acceso a Internet."""

    page = _sample_page(
        [
            ("3:00pm", "Conclusiones"),
            ("4:00pm", "Programa 2"),
            ("5:00pm", "Programa 3"),
            ("6:00pm", "Programa 4"),
            ("7:00pm", "Programa 5"),
            ("8:00pm", "Programa 6"),
        ]
    )
    programmes = parse_mitv_page_utc(
        page,
        date(2026, 8, 6),
        "Canal.CNN.en.Español.ec",
    )
    first = programmes[0]
    assert first.title == "Conclusiones"
    assert first.start.isoformat() == "2026-08-06T10:00:00-05:00"
    assert epg.format_xmltv_datetime(first.start) == "20260806100000 -0500"

    previous_local_day = _sample_page(
        [
            ("2:00am", "Programa nocturno"),
            ("3:00am", "Programa 2"),
            ("4:00am", "Programa 3"),
            ("5:00am", "Programa 4"),
            ("6:00am", "Programa 5"),
        ]
    )
    converted = parse_mitv_page_utc(
        previous_local_day,
        date(2026, 8, 7),
        "CanalRCN.co",
    )
    assert converted[0].start.isoformat() == "2026-08-06T21:00:00-05:00"

    rollover_page = _sample_page(
        [
            ("11:00pm", "Programa A"),
            ("11:30pm", "Programa B"),
            ("12:00am", "Programa C"),
            ("1:00am", "Programa D"),
            ("2:00am", "Programa E"),
        ]
    )
    rollover = parse_mitv_page_utc(
        rollover_page,
        date(2026, 8, 6),
        "NTN24.co",
    )
    assert [item.start.isoformat() for item in rollover[:3]] == [
        "2026-08-06T18:00:00-05:00",
        "2026-08-06T18:30:00-05:00",
        "2026-08-06T19:00:00-05:00",
    ]
    assert all(
        current.start < following.start
        for current, following in zip(rollover, rollover[1:])
    )

    print(
        "Prueba mi.tv correcta: UTC→America/Guayaquil, cambio de fecha "
        "y cruce de medianoche validados."
    )

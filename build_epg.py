#!/usr/bin/env python3
"""Ejecuta el generador EPG vigente corrigiendo la zona horaria de mi.tv.

El generador base estable se descarga desde un commit inmutable del propio
repositorio durante el workflow. Esta capa sustituye únicamente
``parse_mitv_page`` para interpretar las horas de CNN en Español y NTN24 como
UTC y convertirlas a ``America/Guayaquil`` antes de escribir XMLTV.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import build_epg_base as epg

MITV_TZ = ZoneInfo("UTC")


def parse_mitv_page_utc(
    page: str,
    guide_date: date,
    channel_id: str,
) -> list[epg.Programme]:
    """Lee la parrilla de mi.tv en UTC y devuelve emisiones en Ecuador."""

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
            tzinfo=MITV_TZ,
        )
        if previous_source_start is not None and source_start < previous_source_start:
            source_event_date += timedelta(days=1)
            source_start = datetime.combine(
                source_event_date,
                start_clock,
                tzinfo=MITV_TZ,
            )

        local_start = source_start.astimezone(epg.TZ)

        description_node = item.select_one("a > div.content > p.synopsis")
        description = None
        if description_node is not None:
            description = epg.normalize_text(
                description_node.get_text(" ", strip=True)
            ) or None

        starts.append((local_start, title, description))
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
    """Pruebas deterministas que no requieren conexión a Internet."""

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
        "Prueba mi.tv correcta: 15:00 UTC se publica como "
        "10:00 America/Guayaquil."
    )


def main() -> int:
    # scrape_mitv_range() consulta esta función global al ejecutarse; una sola
    # sustitución corrige simultáneamente CNN en Español y NTN24.
    epg.parse_mitv_page = parse_mitv_page_utc
    return epg.main()


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    raise SystemExit(main())

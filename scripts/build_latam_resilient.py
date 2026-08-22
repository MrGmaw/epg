#!/usr/bin/env python3
"""Construye LATAM sin STAR TVE y añade Antena 3 / Star Channel desde mi.tv.

Compatibilidad con v0.2.29:
- ``TVEStarHD.es`` continúa excluido completamente.
- Se añaden ``Antena3-America.co`` y ``Star-Channel.co`` desde mi.tv Colombia.

Regla horaria especial de estos dos canales:
las horas publicadas por sus páginas de mi.tv se interpretan directamente como
``America/Guayaquil``. No se convierten desde UTC y no se aplica ningún offset
manual. Los demás canales de mi.tv conservan la lógica UTC -> Guayaquil que ya
usa ``scripts/mitv_utc.py``.
"""

from __future__ import annotations

import json
import sys
import time as time_module
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from lxml import etree

import build_latam_epg as latam

STAR_TVE_ID = "TVEStarHD.es"
ANTENA3_ID = "Antena3-America.co"
STAR_CHANNEL_ID = "Star-Channel.co"
LOCAL_MITV_IDS = frozenset({ANTENA3_ID, STAR_CHANNEL_ID})
EXPECTED_CHANNELS = 28
MITV_LOCAL_MAX_DAYS = 2
MITV_REQUEST_PAUSE_SECONDS = 1.0

# Guardamos la función original antes de sustituirla. Así todos los canales ya
# existentes de mi.tv siguen usando exactamente su parser UTC habitual.
_ORIGINAL_SCRAPE_MITV_CHANNEL = latam.scrape_mitv_channel

LOCAL_MITV_CHANNELS: tuple[latam.MitvChannel, ...] = (
    latam.MitvChannel(
        "co",
        "antena3",
        ANTENA3_ID,
        ("Antena 3", "Antena3"),
        "https://mi.tv/co/canales/antena3",
    ),
    latam.MitvChannel(
        "co",
        "fox",
        STAR_CHANNEL_ID,
        ("Star Channel", "STAR Channel"),
        "https://mi.tv/co/canales/fox",
    ),
)


def _arg_path(argv: list[str], name: str, default: Path) -> Path:
    prefix = name + "="
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return Path(argv[index + 1])
        if value.startswith(prefix):
            return Path(value.split("=", 1)[1])
    return default


def _output_dir(argv: list[str]) -> Path:
    return _arg_path(argv, "--output", Path("public"))


def parse_mitv_page_guayaquil(
    page: str,
    guide_date: date,
    channel_id: str,
) -> list[latam.epg.Programme]:
    """Interpreta las horas de una página mi.tv directamente en Guayaquil."""
    soup = latam.epg.BeautifulSoup(page, "lxml")
    items = soup.select("#listings > ul > li")
    if not items:
        raise RuntimeError(
            f"mi.tv local {channel_id}: no se encontraron elementos en #listings."
        )

    starts: list[tuple[datetime, str, str | None]] = []
    event_date = guide_date
    previous_start: datetime | None = None

    for item in items:
        time_node = item.select_one("a > div.content > span.time")
        title_node = item.select_one("a > div.content > h2")
        if time_node is None or title_node is None:
            continue

        start_clock = latam.epg.parse_mitv_clock(time_node.get_text(" ", strip=True))
        title = latam.epg.normalize_text(title_node.get_text(" ", strip=True))
        if start_clock is None or not title:
            continue

        start = datetime.combine(event_date, start_clock, tzinfo=latam.epg.TZ)
        if previous_start is not None and start < previous_start:
            event_date += timedelta(days=1)
            start = datetime.combine(event_date, start_clock, tzinfo=latam.epg.TZ)

        description_node = item.select_one("a > div.content > p.synopsis")
        description = None
        if description_node is not None:
            description = latam.epg.normalize_text(
                description_node.get_text(" ", strip=True)
            ) or None

        starts.append((start, title, description))
        previous_start = start

    if len(starts) < 5:
        raise RuntimeError(
            f"mi.tv local {channel_id}: solo se encontraron {len(starts)} emisiones "
            f"para {guide_date.isoformat()}."
        )

    programmes: list[latam.epg.Programme] = []
    for index, (start, title, description) in enumerate(starts):
        stop = starts[index + 1][0] if index + 1 < len(starts) else start + timedelta(hours=1)
        if stop <= start:
            stop = start + timedelta(hours=1)
        programmes.append(
            latam.epg.Programme(
                channel_id=channel_id,
                start=start,
                stop=stop,
                title=title,
                description=description,
            )
        )
    return programmes


def scrape_mitv_channel_guayaquil(
    *,
    country: str,
    slug: str,
    channel_id: str,
    start_date: date,
    local_days: int = MITV_LOCAL_MAX_DAYS,
    pause_seconds: float = MITV_REQUEST_PAUSE_SECONDS,
) -> tuple[list[latam.epg.Programme], int]:
    """Descarga mi.tv sin conversión horaria para los dos canales nuevos."""
    if country != "co":
        raise ValueError(f"mi.tv local: país no soportado: {country!r}")
    if channel_id not in LOCAL_MITV_IDS:
        raise ValueError(f"mi.tv local: canal no soportado: {channel_id!r}")
    if not 1 <= local_days <= MITV_LOCAL_MAX_DAYS:
        raise ValueError(
            f"local_days debe estar entre 1 y {MITV_LOCAL_MAX_DAYS}."
        )

    window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=latam.epg.TZ)
    window_end = window_start + timedelta(days=local_days)
    all_programmes: list[latam.epg.Programme] = []
    loaded_days = 0

    for offset in range(local_days):
        source_date = start_date + timedelta(days=offset)
        url = f"https://mi.tv/{country}/async/channel/{slug}/{source_date.isoformat()}/0"
        try:
            page = latam.epg.fetch_text(
                url,
                headers={
                    "Referer": f"https://mi.tv/{country}/canales/{slug}",
                    "Accept-Language": "es-CO,es;q=0.9,en;q=0.4",
                },
            )
            day_programmes = parse_mitv_page_guayaquil(page, source_date, channel_id)
        except (requests.RequestException, RuntimeError) as exc:
            latam.epg.warn(f"mi.tv local {channel_id} {source_date.isoformat()}: {exc}")
        else:
            all_programmes.extend(day_programmes)
            loaded_days += 1
            latam.epg.log(
                f"mi.tv local {channel_id}: fecha Guayaquil "
                f"{source_date.isoformat()}={len(day_programmes)} emisiones."
            )
        finally:
            if pause_seconds > 0 and offset < local_days - 1:
                time_module.sleep(pause_seconds)

    deduplicated: dict[tuple[str, str], latam.epg.Programme] = {}
    for programme in all_programmes:
        if programme.start >= window_end or programme.stop <= window_start:
            continue
        key = (
            programme.start.isoformat(),
            latam.epg.normalized_key(programme.title),
        )
        deduplicated.setdefault(key, programme)

    result = sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.title),
    )
    # Un día futuro de mi.tv puede aún no estar publicado. Al no existir
    # conversión UTC para estos canales, un día local cargado ya es utilizable.
    minimum_loaded_days = 1
    if loaded_days < minimum_loaded_days or len(result) < 8:
        raise RuntimeError(
            f"mi.tv local {channel_id}: no se obtuvo programación suficiente "
            f"para la ventana Guayaquil solicitada (fechas cargadas: "
            f"{loaded_days}/{local_days})."
        )

    return result, loaded_days


def scrape_mitv_channel_dispatch(**kwargs):
    """Usa hora local solo en Antena 3 y Star Channel; el resto queda intacto."""
    if kwargs.get("channel_id") in LOCAL_MITV_IDS:
        return scrape_mitv_channel_guayaquil(**kwargs)
    return _ORIGINAL_SCRAPE_MITV_CHANNEL(**kwargs)


def configure_channels() -> None:
    """Retira STAR TVE y añade los dos canales mi.tv con IDs estables."""
    latam.GATOTV_CHANNELS = tuple(
        config for config in latam.GATOTV_CHANNELS if config.channel_id != STAR_TVE_ID
    )

    # Idempotencia: si se invoca más de una vez, no duplica canales.
    latam.MITV_CHANNELS = tuple(
        config for config in latam.MITV_CHANNELS if config.channel_id not in LOCAL_MITV_IDS
    ) + LOCAL_MITV_CHANNELS

    latam.LATAM_CHANNEL_IDS = (
        *latam.BASE_CHANNEL_IDS,
        *(config.channel_id for config in latam.MITV_CHANNELS),
        *(config.channel_id for config in latam.GATOTV_CHANNELS),
        latam.MAKRODIGITAL_ID,
        latam.ECUADOR_TV_ID,
    )
    latam.scrape_mitv_channel = scrape_mitv_channel_dispatch

    if STAR_TVE_ID in latam.LATAM_CHANNEL_IDS:
        raise RuntimeError("STAR TVE reapareció en LATAM_CHANNEL_IDS.")
    if any(config.channel_id == STAR_TVE_ID for config in latam.GATOTV_CHANNELS):
        raise RuntimeError("STAR TVE reapareció en GATOTV_CHANNELS.")
    if len(latam.LATAM_CHANNEL_IDS) != EXPECTED_CHANNELS:
        raise RuntimeError(
            f"La guía debe contener {EXPECTED_CHANNELS} canales; "
            f"obtenidos={len(latam.LATAM_CHANNEL_IDS)}."
        )
    if len(set(latam.LATAM_CHANNEL_IDS)) != EXPECTED_CHANNELS:
        raise RuntimeError("La guía LATAM contiene IDs duplicados.")
    for channel_id in LOCAL_MITV_IDS:
        if channel_id not in latam.LATAM_CHANNEL_IDS:
            raise RuntimeError(f"Falta el nuevo canal {channel_id}.")


def _clean_and_annotate_status(output_dir: Path) -> None:
    """Limpia metadatos STAR TVE y registra la política horaria nueva."""
    status_path = output_dir / "latam-status.json"
    if not status_path.is_file():
        return

    status = json.loads(status_path.read_text(encoding="utf-8"))
    for key in list(status):
        if key.startswith("star_tve_"):
            status.pop(key, None)

    for key in (
        "programme_counts",
        "gatotv_source_days",
        "gatotv_daily_counts",
        "gatotv_source_timezones",
        "gatotv_ampm_local_preferred",
    ):
        value = status.get(key)
        if isinstance(value, dict):
            value.pop(STAR_TVE_ID, None)

    sources = status.get("sources")
    if isinstance(sources, dict):
        gato_tv = sources.get("gato_tv")
        if isinstance(gato_tv, dict):
            gato_tv.pop(STAR_TVE_ID, None)

    status["channels"] = EXPECTED_CHANNELS
    status["mitv_local_time_channels"] = {
        ANTENA3_ID: {
            "source": "https://mi.tv/co/canales/antena3",
            "timezone": "America/Guayaquil",
            "conversion": "none",
        },
        STAR_CHANNEL_ID: {
            "source": "https://mi.tv/co/canales/fox",
            "timezone": "America/Guayaquil",
            "conversion": "none",
        },
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _assert_output(output_dir: Path) -> None:
    """Guardia final: 28 canales, nuevos IDs presentes y STAR TVE ausente."""
    xml_path = output_dir / "latam.xml"
    if not xml_path.is_file():
        raise RuntimeError("No se generó latam.xml.")

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    root = etree.parse(str(xml_path), parser).getroot()

    if root.xpath("./channel[@id=$channel_id]", channel_id=STAR_TVE_ID):
        raise RuntimeError("latam.xml todavía contiene STAR TVE.")
    if root.xpath("./programme[@channel=$channel_id]", channel_id=STAR_TVE_ID):
        raise RuntimeError("latam.xml todavía contiene emisiones STAR TVE.")

    channel_ids = [node.get("id", "") for node in root.findall("channel")]
    if len(channel_ids) != EXPECTED_CHANNELS or len(set(channel_ids)) != EXPECTED_CHANNELS:
        raise RuntimeError(
            f"latam.xml debe contener {EXPECTED_CHANNELS} canales únicos; "
            f"obtenidos={len(channel_ids)}."
        )

    for channel_id in (ANTENA3_ID, STAR_CHANNEL_ID):
        if channel_id not in channel_ids:
            raise RuntimeError(f"latam.xml no contiene {channel_id}.")
        programmes = root.xpath("./programme[@channel=$channel_id]", channel_id=channel_id)
        if len(programmes) < 5:
            raise RuntimeError(
                f"latam.xml contiene programación insuficiente para {channel_id}: "
                f"{len(programmes)} emisiones."
            )
        for programme in programmes:
            if not programme.get("start", "").endswith(" -0500"):
                raise RuntimeError(f"Hora no Guayaquil en {channel_id}: {programme.get('start')}")
            if not programme.get("stop", "").endswith(" -0500"):
                raise RuntimeError(f"Hora no Guayaquil en {channel_id}: {programme.get('stop')}")

    status_path = output_dir / "latam-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if int(status.get("channels", 0)) != EXPECTED_CHANNELS:
        raise RuntimeError("latam-status.json no informa 28 canales.")
    counts = status.get("programme_counts", {})
    for channel_id in (ANTENA3_ID, STAR_CHANNEL_ID):
        if int(counts.get(channel_id, 0)) < 5:
            raise RuntimeError(f"latam-status.json no registra programación de {channel_id}.")

    local_modes = status.get("mitv_local_time_channels", {})
    expected_sources = {
        ANTENA3_ID: "https://mi.tv/co/canales/antena3",
        STAR_CHANNEL_ID: "https://mi.tv/co/canales/fox",
    }
    for channel_id, source_url in expected_sources.items():
        mode = local_modes.get(channel_id, {})
        if mode.get("source") != source_url:
            raise RuntimeError(f"Fuente mi.tv inesperada para {channel_id}.")
        if mode.get("timezone") != "America/Guayaquil" or mode.get("conversion") != "none":
            raise RuntimeError(f"Política horaria inesperada para {channel_id}: {mode!r}")


def _sample_page(times_and_titles: list[tuple[str, str]]) -> str:
    items = "\n".join(
        """
        <li><a><div class="content">
          <span class="time">{clock}</span>
          <h2>{title}</h2>
          <p class="synopsis">Prueba hora local Ecuador</p>
        </div></a></li>
        """.format(clock=clock, title=title)
        for clock, title in times_and_titles
    )
    return f'<div id="listings"><ul>{items}</ul></div>'


def self_test() -> None:
    configure_channels()
    assert len(latam.LATAM_CHANNEL_IDS) == EXPECTED_CHANNELS
    assert STAR_TVE_ID not in latam.LATAM_CHANNEL_IDS
    assert ANTENA3_ID in latam.LATAM_CHANNEL_IDS
    assert STAR_CHANNEL_ID in latam.LATAM_CHANNEL_IDS

    sample = _sample_page(
        [
            ("3:00pm", "Programa 1"),
            ("4:00pm", "Programa 2"),
            ("5:00pm", "Programa 3"),
            ("6:00pm", "Programa 4"),
            ("7:00pm", "Programa 5"),
            ("8:00pm", "Programa 6"),
        ]
    )
    programmes = parse_mitv_page_guayaquil(sample, date(2026, 8, 21), ANTENA3_ID)
    assert programmes[0].start.isoformat() == "2026-08-21T15:00:00-05:00"
    assert programmes[0].stop.isoformat() == "2026-08-21T16:00:00-05:00"
    assert programmes[0].channel_id == ANTENA3_ID

    programmes_star = parse_mitv_page_guayaquil(sample, date(2026, 8, 21), STAR_CHANNEL_ID)
    assert programmes_star[0].start.isoformat() == "2026-08-21T15:00:00-05:00"

    print(
        "Prueba v0.2.30 correcta: 28 canales; STAR TVE excluido; "
        "Antena 3 y Star Channel interpretados directamente en America/Guayaquil."
    )


def main() -> int:
    configure_channels()
    result = latam.main()
    if result == 0:
        output_dir = _output_dir(sys.argv[1:])
        _clean_and_annotate_status(output_dir)
        _assert_output(output_dir)
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (etree.XMLSyntaxError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

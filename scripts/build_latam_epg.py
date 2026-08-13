#!/usr/bin/env python3
"""Construye ``latam.xml`` con los 26 canales seleccionados.

La guía principal ``ec.xml`` se genera primero y actúa como fuente estable
para los canales base, excepto TVE Internacional. TVE Internacional toma su
programación exclusivamente de mi.tv Colombia. Después se añaden los otros
canales de mi.tv, cuatro parrillas de GatoTV y la parrilla oficial de Ecuador TV
cuando está disponible.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import requests
from bs4 import BeautifulSoup, Tag
from lxml import etree

import build_epg_base as epg
from mitv_utc import scrape_mitv_channel
from mitv_logos import load_logo_urls

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
EPG_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
ECUADOR_TV_URL = "https://www.ecuadortv.ec/programas"
ECUADOR_TV_HOME_URL = "https://www.ecuadortv.ec/"
ECUADOR_TV_SCHEDULE_URLS = (ECUADOR_TV_URL, ECUADOR_TV_HOME_URL)
ECUADOR_TV_ID = "Canal.Ecuador.TV.ec"
TVE_ID = "Canal.TVE.Internacional.(Televisión.Española).ec"
TVE_MITV_COUNTRY = "co"
TVE_MITV_SLUG = "tve"
TVE_MITV_URL = "https://mi.tv/co/canales/tve"

BASE_CHANNEL_IDS: tuple[str, ...] = (
    "Canal.TC.Televisión.ec",
    "Canal.Gamavisión.ec",
    "Canal.RTS.ec",
    TVE_ID,
    "TeleamazonasQuito.ec",
    "TeleamazonasGuayaquil.ec",
    "Ecuavisa.ec",
    "EcuavisaInternacional.ec",
    "TVC.ec",
    "Canal.CNN.en.Español.ec",
    "NTN24.co",
)


@dataclass(frozen=True)
class MitvChannel:
    country: str
    slug: str
    channel_id: str
    names: tuple[str, ...]
    website: str


@dataclass(frozen=True)
class GatoTvChannel:
    slug: str
    channel_id: str
    names: tuple[str, ...]
    website: str
    time_offset_minutes: int = 0

    @property
    def base_url(self) -> str:
        return f"https://www.gatotv.com/canal/{self.slug}"


TVE_MITV_CHANNEL = MitvChannel(
    TVE_MITV_COUNTRY,
    TVE_MITV_SLUG,
    TVE_ID,
    ("TVE Internacional", "TVE"),
    TVE_MITV_URL,
)


MITV_CHANNELS: tuple[MitvChannel, ...] = (
    MitvChannel(
        "co",
        "rcn",
        "CanalRCN.co",
        ("Canal RCN", "RCN"),
        "https://www.canalrcn.com/",
    ),
    MitvChannel(
        "co",
        "caracol",
        "CaracolTV.co",
        ("Caracol TV", "Caracol"),
        "https://www.caracoltv.com/",
    ),
    MitvChannel(
        "co",
        "el-gourmet",
        "Canal.Elgourmet.ec",
        ("El Gourmet", "elGourmet"),
        "https://elgourmet.com/",
    ),
    MitvChannel(
        "co",
        "history",
        "Canal.History.co",
        ("History", "History Channel"),
        "https://www.historylatam.com/",
    ),
    MitvChannel(
        "co",
        "h2",
        "Canal.History.2.co",
        ("History 2", "H2"),
        "https://www.historylatam.com/",
    ),
    MitvChannel(
        "ar",
        "canal-7-capital",
        "TV.Publica.canal.7.ar",
        ("TV Pública", "Televisión Pública Argentina"),
        "https://www.tvpublica.com.ar/",
    ),
    MitvChannel(
        "ar",
        "telefe",
        "Telefe.ar",
        ("Telefe",),
        "https://mitelefe.com/",
    ),
    MitvChannel(
        "cl",
        "deutsche-welle-espanol",
        "Deutsche.Welle.cl",
        ("Deutsche Welle Español", "DW Español"),
        "https://www.dw.com/es/",
    ),
    MitvChannel(
        "ar",
        "hgtv",
        "hgtv.ar",
        ("HGTV",),
        "https://mi.tv/ar/canales/hgtv",
    ),
    MitvChannel(
        "ar",
        "france-24-espanol",
        "France24Espanol.fr",
        ("France 24 Español", "France 24 en Español"),
        "https://www.france24.com/es/",
    ),
)

GATOTV_CHANNELS: tuple[GatoTvChannel, ...] = (
    GatoTvChannel(
        "24_horas_tve",
        "Canal24Horas.es",
        ("Canal 24 Horas (TVE)", "24 Horas TVE"),
        "https://www.rtve.es/play/24-horas/",
    ),
    GatoTvChannel(
        "la_1",
        "La1.es",
        ("La 1", "TVE La 1"),
        "https://www.rtve.es/television/",
    ),
    GatoTvChannel(
        "star_tve",
        "TVEStarHD.es",
        ("STAR TVE", "Star TVE"),
        "https://www.gatotv.com/canal/star_tve",
        -60,
    ),
    GatoTvChannel(
        "clan_tve",
        "Clan.es",
        ("Clan TVE", "Clan"),
        "https://www.rtve.es/infantil/",
    ),
)


LATAM_CHANNEL_IDS: tuple[str, ...] = (
    *BASE_CHANNEL_IDS,
    *(channel.channel_id for channel in MITV_CHANNELS),
    *(channel.channel_id for channel in GATOTV_CHANNELS),
    ECUADOR_TV_ID,
)

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}
ECUADOR_TV_CATEGORIES = (
    "Educación, Cultura y Medio Ambiente",
    "Hogar y Estilo de vida",
    "Informativo y opinión",
    "Series y Novelas",
    "Aventuras Infantiles",
    "Salud y Bienestar",
    "Noticias 7",
    "Deportivo",
    "Infantil",
)
DATE_RE = re.compile(
    r"(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s*,?\s*)?"
    r"(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+"
    r"(?P<year>\d{4})",
    re.I,
)
TIME_RANGE_RE = re.compile(
    r"(?P<start>(?:[01]?\d|2[0-3]):[0-5]\d)\s*"
    r"(?:-|–|—|\ba\b)\s*"
    r"(?P<stop>(?:[01]?\d|2[0-3]):[0-5]\d)",
    re.I,
)
RECURRENCE_RE = re.compile(
    r"\b(?:de\s+)?lunes\s+a\s+(?:viernes|domingo)\b|"
    r"\b(?:sabados|domingos|fines\s+de\s+semana)\b|"
    r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+y\s+"
    r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
    re.I,
)


def normalized(value: str) -> str:
    value = epg.normalize_text(value).casefold()
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def parse_xmltv_datetime(value: str) -> datetime:
    value = value.strip()
    for pattern in ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M %z"):
        try:
            return datetime.strptime(value, pattern).astimezone(epg.TZ)
        except ValueError:
            continue
    raise ValueError(f"Fecha XMLTV no reconocida: {value!r}")


def parse_source_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
    )
    tree = etree.parse(str(path), parser)
    if tree.getroot().tag != "tv":
        raise RuntimeError(f"La raíz de {path} no es <tv>.")
    return tree


def source_channel(root: etree._Element, channel_id: str) -> etree._Element:
    matches = root.xpath("./channel[@id=$channel_id]", channel_id=channel_id)
    if len(matches) != 1:
        raise RuntimeError(
            f"Se esperaba un canal {channel_id!r} en ec.xml; encontrados: "
            f"{len(matches)}."
        )
    return matches[0]


def source_programmes(
    root: etree._Element,
    channel_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[etree._Element]:
    result: list[etree._Element] = []
    for programme in root.xpath(
        "./programme[@channel=$channel_id]",
        channel_id=channel_id,
    ):
        try:
            start = parse_xmltv_datetime(programme.get("start", ""))
            stop = parse_xmltv_datetime(programme.get("stop", ""))
        except ValueError:
            continue
        if start < window_end and stop > window_start:
            result.append(copy.deepcopy(programme))
    if not result:
        raise RuntimeError(f"El canal {channel_id} no tiene programación en ec.xml.")
    return result


def make_channel(
    channel_id: str,
    names: Sequence[str],
    website: str,
    icon_url: str | None = None,
) -> etree._Element:
    channel = etree.Element("channel", id=channel_id)
    for name in names:
        display_name = etree.SubElement(channel, "display-name", lang="es")
        display_name.text = name
    if icon_url:
        etree.SubElement(channel, "icon", src=icon_url)
    url = etree.SubElement(channel, "url")
    url.text = website
    return channel


def set_channel_icon(channel: etree._Element, icon_url: str | None) -> None:
    """Sustituye el icono de un canal por la copia estable de GitHub Pages."""

    if not icon_url:
        return
    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    icon = etree.Element("icon", src=icon_url)
    children = list(channel)
    insert_at = len(children)
    for index, child in enumerate(children):
        if child.tag == "url":
            insert_at = index
            break
    channel.insert(insert_at, icon)


def parse_spanish_date(value: str) -> date | None:
    match = DATE_RE.search(value)
    if match is None:
        return None
    month_key = normalized(match.group("month"))
    month = SPANISH_MONTHS.get(month_key)
    if month is None:
        return None
    try:
        return date(
            int(match.group("year")),
            month,
            int(match.group("day")),
        )
    except ValueError:
        return None


def date_for_weekday(base_date: date, weekday_name: str) -> date | None:
    weekday = WEEKDAYS.get(normalized(weekday_name))
    if weekday is None:
        return None
    offset = (weekday - base_date.weekday()) % 7
    return base_date + timedelta(days=offset)


def clean_ecuador_tv_title(value: str) -> str:
    value = epg.normalize_text(value)
    value = re.sub(r"\bon\s*air\b", "", value, flags=re.I)
    value = re.sub(r"^(?:categor[ií]a\s+programa\s*)+", "", value, flags=re.I)
    for category in sorted(ECUADOR_TV_CATEGORIES, key=len, reverse=True):
        if normalized(value).startswith(normalized(category)):
            value = value[len(category) :].strip(" :-–—|")
            break
    value = re.sub(r"^(?:categor[ií]a\s+programa\s*)+", "", value, flags=re.I)
    return epg.normalize_text(value)


def programmes_from_schedule_text(
    value: str,
    guide_date: date,
    channel_id: str,
    previous_text: str | None = None,
) -> list[epg.Programme]:
    """Extrae uno o varios bloques horarios contenidos en una misma línea."""

    matches = list(TIME_RANGE_RE.finditer(value))
    if not matches:
        return []

    programmes: list[epg.Programme] = []
    previous_end = 0
    for index, match in enumerate(matches):
        start_clock = datetime.strptime(match.group("start"), "%H:%M").time()
        stop_clock = datetime.strptime(match.group("stop"), "%H:%M").time()
        prefix = value[previous_end : match.start()].strip(" :-–—|")
        title = clean_ecuador_tv_title(prefix)
        if not title and index == 0 and previous_text:
            title = clean_ecuador_tv_title(previous_text)
        previous_end = match.end()

        if not title or normalized(title) in {
            "lunes",
            "martes",
            "miercoles",
            "jueves",
            "viernes",
            "sabado",
            "domingo",
        }:
            continue

        start = datetime.combine(guide_date, start_clock, tzinfo=epg.TZ)
        stop_date = guide_date if stop_clock > start_clock else guide_date + timedelta(days=1)
        stop = datetime.combine(stop_date, stop_clock, tzinfo=epg.TZ)
        if stop <= start:
            continue
        programmes.append(
            epg.Programme(
                channel_id=channel_id,
                start=start,
                stop=stop,
                title=title,
            )
        )
    return programmes


def programme_from_schedule_text(
    value: str,
    guide_date: date,
    channel_id: str,
    previous_text: str | None = None,
) -> epg.Programme | None:
    programmes = programmes_from_schedule_text(
        value,
        guide_date,
        channel_id,
        previous_text=previous_text,
    )
    return programmes[0] if programmes else None


def parse_ecuador_tv_page(
    page: str,
    start_date: date,
    days: int,
    channel_id: str = ECUADOR_TV_ID,
) -> tuple[list[epg.Programme], set[date]]:
    """Extrae emisiones válidas de la parrilla oficial de Ecuador TV.

    La página ha usado estructuras dinámicas distintas. El parser trabaja con
    el texto visible del HTML y reconoce fechas españolas, pestañas por día y
    rangos ``HH:MM - HH:MM``. Desde v0.2.3 también acepta una parrilla oficial
    parcial: esos bloques se superponen sobre EPGShare sin descartar el resto
    del día. Esto evita que un único bloque oficial correcto (por ejemplo el
    programa actualmente al aire) se pierda por no alcanzar un mínimo diario.
    """

    soup = BeautifulSoup(page, "lxml")
    lines = [epg.normalize_text(value) for value in soup.stripped_strings]
    lines = [value for value in lines if value]

    window_end_date = start_date + timedelta(days=days)
    current_date: date | None = None
    previous_line: str | None = None
    by_date: dict[date, list[epg.Programme]] = defaultdict(list)

    for line in lines:
        explicit_date = parse_spanish_date(line)
        if explicit_date is not None:
            current_date = explicit_date
            if TIME_RANGE_RE.search(line) is None:
                previous_line = line
                continue
            line = DATE_RE.sub("", line).strip(" ,:-–—|")

        weekday_line = normalized(line).strip(" ,:")
        if weekday_line in WEEKDAYS and TIME_RANGE_RE.search(line) is None:
            current_date = date_for_weekday(start_date, weekday_line)
            previous_line = line
            continue

        if TIME_RANGE_RE.search(line) is None:
            previous_line = line
            continue
        if RECURRENCE_RE.search(normalized(line)) is not None:
            # Horarios generales de fichas de programas, no la parrilla diaria.
            previous_line = line
            continue

        if current_date is None:
            # La vista principal suele corresponder al día local actual.
            current_date = start_date

        if not start_date <= current_date < window_end_date:
            previous_line = line
            continue

        line_programmes = programmes_from_schedule_text(
            line,
            current_date,
            channel_id,
            previous_text=previous_line,
        )
        by_date[current_date].extend(line_programmes)
        previous_line = line

    accepted_dates: set[date] = set()
    programmes: list[epg.Programme] = []
    for guide_date, entries in sorted(by_date.items()):
        deduplicated: dict[tuple[str, str, str], epg.Programme] = {}
        for programme in entries:
            key = (
                programme.start.isoformat(),
                programme.stop.isoformat(),
                normalized(programme.title),
            )
            deduplicated.setdefault(key, programme)
        day_programmes = sorted(
            deduplicated.values(),
            key=lambda item: (item.start, item.stop, item.title),
        )
        overlap_count = sum(
            1
            for current, following in zip(day_programmes, day_programmes[1:])
            if following.start < current.stop
        )
        if not day_programmes:
            continue
        if overlap_count > max(2, len(day_programmes) // 3):
            epg.warn(
                "Ecuador TV oficial: se descartó "
                f"{guide_date.isoformat()} porque contiene "
                f"{len(day_programmes)} emisiones y {overlap_count} solapamientos."
            )
            continue
        accepted_dates.add(guide_date)
        programmes.extend(day_programmes)

    if accepted_dates:
        epg.log(
            "Ecuador TV oficial: días aceptados="
            + ", ".join(day.isoformat() for day in sorted(accepted_dates))
            + f"; total={len(programmes)} emisiones."
        )
    else:
        epg.warn(
            "Ecuador TV oficial: no se encontraron bloques válidos; "
            "se utilizará EPGShare como respaldo."
        )

    return programmes, accepted_dates


def parse_gatotv_page(
    page: str,
    guide_date: date,
    channel_id: str,
) -> list[epg.Programme]:
    """Lee una fecha de GatoTV conservando correctamente el cruce de medianoche.

    Algunas parrillas comienzan mostrando el programa que empezó la noche
    anterior y termina después de las 00:00. En ese caso la primera fila se
    fecha en ``guide_date - 1``; el resto pertenece a ``guide_date``.
    """

    soup = BeautifulSoup(page, "lxml")
    rows: list[tuple[time, time, str, str | None]] = []
    for row in soup.find_all("tr"):
        parts = [epg.normalize_text(value) for value in row.stripped_strings]
        parts = [value for value in parts if value]
        if not parts:
            continue

        start_result = None
        start_index = 0
        for index in range(min(len(parts), 5)):
            start_result = epg.parse_clock(parts, index)
            if start_result is not None:
                start_index = index
                break
        if start_result is None or start_index > 4:
            continue
        start_clock, after_start = start_result

        stop_result = None
        for index in range(after_start, len(parts)):
            stop_result = epg.parse_clock(parts, index)
            if stop_result is not None:
                break
        if stop_result is None:
            continue
        stop_clock, after_stop = stop_result

        title_parts = epg.clean_title_parts(parts[after_stop:])
        if not title_parts:
            continue
        title = title_parts[0]
        description = " — ".join(title_parts[1:]) or None
        rows.append((start_clock, stop_clock, title, description))

    if len(rows) < 5:
        # Conserva el respaldo del generador base para un eventual cambio de
        # maquetación en GatoTV. La estructura tabular es la vía preferida.
        return epg.parse_gatotv_page(page, guide_date, channel_id)

    programmes: list[epg.Programme] = []
    first_start, first_stop, _, _ = rows[0]
    first_is_carryover = (
        first_stop <= first_start
        and any(start_clock < first_start for start_clock, _, _, _ in rows[1:])
    )

    for index, (start_clock, stop_clock, title, description) in enumerate(rows):
        start_day = guide_date
        if index == 0 and first_is_carryover:
            start_day -= timedelta(days=1)
        stop_day = start_day if stop_clock > start_clock else start_day + timedelta(days=1)
        start = datetime.combine(start_day, start_clock, tzinfo=epg.TZ)
        stop = datetime.combine(stop_day, stop_clock, tzinfo=epg.TZ)
        if stop <= start:
            continue
        programmes.append(
            epg.Programme(
                channel_id=channel_id,
                start=start,
                stop=stop,
                title=title,
                description=description,
            )
        )

    deduplicated: dict[tuple[str, str, str], epg.Programme] = {}
    for programme in programmes:
        key = (
            programme.start.isoformat(),
            programme.stop.isoformat(),
            normalized(programme.title),
        )
        deduplicated.setdefault(key, programme)
    result = sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.stop, item.title),
    )
    if len(result) < 5:
        raise RuntimeError(
            f"GatoTV: solo se encontraron {len(result)} emisiones "
            f"para {guide_date.isoformat()}."
        )
    return result


def shift_programmes(
    programmes: list[epg.Programme],
    minutes: int,
) -> list[epg.Programme]:
    """Desplaza una parrilla completa sin alterar duraciones ni contenidos."""

    if minutes == 0:
        return programmes
    delta = timedelta(minutes=minutes)
    return [
        epg.Programme(
            channel_id=item.channel_id,
            start=item.start + delta,
            stop=item.stop + delta,
            title=item.title,
            description=item.description,
        )
        for item in programmes
    ]


def scrape_gatotv_channel(
    config: GatoTvChannel,
    start_date: date,
    days: int,
) -> tuple[list[epg.Programme], int, dict[str, int]]:
    """Descarga GatoTV tolerando días futuros aún no publicados.

    GatoTV puede tener la parrilla de hoy completa y días posteriores vacíos o
    parciales. Cada fecha se valida de forma independiente; una fecha futura
    fallida genera solo una advertencia. El canal completo falla únicamente si
    no se consigue ninguna fecha utilizable.
    """

    all_programmes: list[epg.Programme] = []
    loaded_days = 0
    daily_counts: dict[str, int] = {}
    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        dated_url = f"{config.base_url}/{guide_date.isoformat()}"
        try:
            page = epg.fetch_text(
                dated_url,
                headers={"Referer": f"{config.base_url}/"},
            )
            day_programmes = parse_gatotv_page(
                page,
                guide_date,
                config.channel_id,
            )
        except (requests.RequestException, RuntimeError) as exc:
            if offset == 0:
                epg.warn(
                    f"GatoTV {config.channel_id} {guide_date.isoformat()}: "
                    f"falló la URL fechada ({exc}). Se probará la página principal."
                )
                try:
                    page = epg.fetch_text(
                        config.base_url,
                        headers={"Referer": "https://www.gatotv.com/"},
                    )
                    day_programmes = parse_gatotv_page(
                        page,
                        guide_date,
                        config.channel_id,
                    )
                except (requests.RequestException, RuntimeError) as fallback_exc:
                    epg.warn(
                        f"GatoTV {config.channel_id} {guide_date.isoformat()}: "
                        f"también falló la página principal: {fallback_exc}"
                    )
                    continue
            else:
                epg.warn(
                    f"GatoTV {config.channel_id} {guide_date.isoformat()}: {exc}"
                )
                continue

        day_programmes = shift_programmes(
            day_programmes,
            config.time_offset_minutes,
        )
        all_programmes.extend(day_programmes)
        loaded_days += 1
        daily_counts[guide_date.isoformat()] = len(day_programmes)
        epg.log(
            f"GatoTV {config.channel_id}: {guide_date.isoformat()}="
            f"{len(day_programmes)} emisiones."
        )

    deduplicated: dict[tuple[str, str, str], epg.Programme] = {}
    for programme in all_programmes:
        key = (
            programme.start.isoformat(),
            programme.stop.isoformat(),
            normalized(programme.title),
        )
        deduplicated.setdefault(key, programme)
    result = sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.stop, item.title),
    )
    if loaded_days == 0 or len(result) < 5:
        raise RuntimeError(
            f"GatoTV {config.channel_id}: no se obtuvo programación suficiente."
        )
    return result, loaded_days, daily_counts


def _xml_programme_interval(programme: etree._Element) -> tuple[datetime, datetime]:
    return (
        parse_xmltv_datetime(programme.get("start", "")),
        parse_xmltv_datetime(programme.get("stop", "")),
    )


def _programme_overlaps_interval(
    programme: etree._Element,
    start: datetime,
    stop: datetime,
) -> bool:
    try:
        current_start, current_stop = _xml_programme_interval(programme)
    except ValueError:
        return False
    return current_start < stop and current_stop > start


def combine_ecuador_tv(
    *,
    source_root: etree._Element,
    start_date: date,
    days: int,
) -> tuple[etree._Element, list[etree._Element], dict[str, object]]:
    """Superpone la parrilla oficial sobre EPGShare por intervalo horario.

    La web oficial puede entregar solo una parte del día dependiendo de la
    plantilla o de cómo se renderice en el runner. En lugar de exigir un día
    completo, cada bloque oficial válido reemplaza únicamente los programas de
    EPGShare que se solapen con él. Los huecos siguen cubiertos por EPGShare.
    """

    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=days)
    channel = copy.deepcopy(source_channel(source_root, ECUADOR_TV_ID))
    epg.ensure_display_name(channel, "Ecuador TV", aliases=("Ecuador TV Canal 7",))
    official_url = channel.find("url")
    if official_url is None:
        official_url = etree.SubElement(channel, "url")
    official_url.text = ECUADOR_TV_URL

    fallback = source_programmes(
        source_root,
        ECUADOR_TV_ID,
        window_start,
        window_end,
    )

    official_by_key: dict[tuple[str, str], epg.Programme] = {}
    official_sources: list[str] = []
    for schedule_url in ECUADOR_TV_SCHEDULE_URLS:
        try:
            page = epg.fetch_text(
                schedule_url,
                headers={"Referer": "https://www.ecuadortv.ec/"},
            )
            page_programmes, _page_dates = parse_ecuador_tv_page(
                page,
                start_date,
                days,
            )
            if page_programmes:
                official_sources.append(schedule_url)
            for item in page_programmes:
                key = (
                    item.start.isoformat(),
                    item.stop.isoformat(),
                )
                official_by_key.setdefault(key, item)
        except (requests.RequestException, RuntimeError) as exc:
            epg.warn(f"Ecuador TV oficial {schedule_url}: {exc}")

    official_programmes = sorted(
        official_by_key.values(),
        key=lambda item: (item.start, item.stop, item.title),
    )
    official_dates = {item.start.date() for item in official_programmes}

    kept_fallback = list(fallback)
    replaced_fallback = 0
    for official in official_programmes:
        before = len(kept_fallback)
        kept_fallback = [
            programme
            for programme in kept_fallback
            if not _programme_overlaps_interval(
                programme,
                official.start,
                official.stop,
            )
        ]
        replaced_fallback += before - len(kept_fallback)

    official_elements = [epg.make_programme(item) for item in official_programmes]
    combined = kept_fallback + official_elements
    combined.sort(key=lambda item: (item.get("start", ""), item.get("stop", "")))

    fallback_dates = sorted(
        {
            parse_xmltv_datetime(programme.get("start", "")).date()
            for programme in kept_fallback
        }
    )
    if official_programmes and kept_fallback:
        source_name = "official_overlay+epgshare_fallback"
    elif official_programmes:
        source_name = "official"
    else:
        source_name = "epgshare_fallback"

    if official_programmes:
        epg.log(
            "Ecuador TV oficial: "
            f"{len(official_programmes)} bloques superpuestos; "
            f"{replaced_fallback} bloques EPGShare reemplazados."
        )
    else:
        epg.warn("Ecuador TV oficial: sin bloques utilizables; se conserva EPGShare.")

    return channel, combined, {
        "source": source_name,
        "official_dates": [day.isoformat() for day in sorted(official_dates)],
        "fallback_dates": [day.isoformat() for day in fallback_dates],
        "official_programmes": len(official_programmes),
        "fallback_programmes_kept": len(kept_fallback),
        "fallback_programmes_replaced": replaced_fallback,
        "official_sources": official_sources,
    }


def validate_latam_tree(
    tree: etree._ElementTree,
    dtd_path: Path | None,
) -> dict[str, int]:
    root = tree.getroot()
    if root.attrib != {
        "generator-info-name": "none",
        "generator-info-url": "none",
    }:
        raise RuntimeError(f"Atributos inesperados de <tv>: {dict(root.attrib)!r}")

    channel_ids = [channel.get("id", "") for channel in root.findall("channel")]
    if channel_ids != list(LATAM_CHANNEL_IDS):
        raise RuntimeError(
            "Orden o conjunto de canales inesperado en latam.xml.\n"
            f"Esperado: {list(LATAM_CHANNEL_IDS)!r}\n"
            f"Obtenido: {channel_ids!r}"
        )
    expected_count = len(LATAM_CHANNEL_IDS)
    if len(channel_ids) != expected_count or len(set(channel_ids)) != expected_count:
        raise RuntimeError(
            f"latam.xml debe contener exactamente {expected_count} canales únicos."
        )

    counts = Counter(
        programme.get("channel", "")
        for programme in root.findall("programme")
    )
    missing_programmes = [channel_id for channel_id in channel_ids if counts[channel_id] == 0]
    if missing_programmes:
        raise RuntimeError(
            f"Canales de latam.xml sin programación: {missing_programmes}"
        )

    for programme in root.findall("programme"):
        if programme.get("channel") not in set(channel_ids):
            raise RuntimeError("Existe un programme asociado a un canal no publicado.")
        start = parse_xmltv_datetime(programme.get("start", ""))
        stop = parse_xmltv_datetime(programme.get("stop", ""))
        if stop <= start:
            raise RuntimeError(
                f"Rango inválido en {programme.get('channel')}: "
                f"{programme.get('start')} → {programme.get('stop')}"
            )
        if programme.find("title") is None:
            raise RuntimeError("Existe un programme sin title.")

    if dtd_path is not None:
        with dtd_path.open("rb") as handle:
            dtd = etree.DTD(handle)
        if not dtd.validate(tree):
            errors = "\n".join(
                str(error)
                for error in dtd.error_log.filter_from_errors()[:20]
            )
            raise RuntimeError(f"latam.xml no supera XMLTV DTD:\n{errors}")

    return {channel_id: counts[channel_id] for channel_id in channel_ids}


def write_xml_and_gzip(
    tree: etree._ElementTree,
    xml_path: Path,
    gz_path: Path,
) -> None:
    payload = etree.tostring(
        tree.getroot(),
        encoding="UTF-8",
        xml_declaration=False,
        pretty_print=True,
    )
    header = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n'
    )
    xml_bytes = header + payload
    xml_path.write_bytes(xml_bytes)
    with gz_path.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            compresslevel=9,
            mtime=0,
        ) as gz_handle:
            gz_handle.write(xml_bytes)
    if gzip.decompress(gz_path.read_bytes()) != xml_bytes:
        raise RuntimeError(f"{gz_path.name} no coincide con {xml_path.name}.")


def write_index(output_dir: Path) -> None:
    now = datetime.now(epg.TZ)
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EPG MrG v{EPG_VERSION}</title>
</head>
<body>
  <h1>EPG MrG v{EPG_VERSION}</h1>
  <h2>Guía principal Ecuador</h2>
  <ul>
    <li><a href="./ec.xml">ec.xml</a></li>
    <li><a href="./ec.xml.gz">ec.xml.gz</a></li>
    <li><a href="./status.json">status.json</a></li>
  </ul>
  <h2>Guía seleccionada Ecuador y Latinoamérica</h2>
  <ul>
    <li><a href="./latam.xml">latam.xml</a></li>
    <li><a href="./latam.xml.gz">latam.xml.gz</a></li>
    <li><a href="./latam-status.json">latam-status.json</a></li>
  </ul>
  <h2>Logos locales de mi.tv</h2>
  <ul>
    <li><a href="./logos/manifest.json">logos/manifest.json</a></li>
  </ul>
  <p><a href="./xmltv.dtd">xmltv.dtd</a></p>
  <p>Última generación: {now.strftime('%Y-%m-%d %H:%M:%S')} (Ecuador).</p>
  <p><code>https://mrgmaw.github.io/epg/latam.xml.gz</code></p>
  <p>GSE Smart IPTV: <code>https://cdn.jsdelivr.net/gh/MrGmaw/epg@epg-data/latam.xml.gz</code></p>
</body>
</html>
"""
    (output_dir / "index.html").write_text(html, encoding="utf-8", newline="\n")
    (output_dir / ".nojekyll").touch()


def build_latam(
    *,
    source_xml: Path,
    output_dir: Path,
    dtd_path: Path | None,
    days: int,
    mitv_days: int,
    gatotv_days: int,
    logos_manifest: Path | None = None,
) -> dict[str, object]:
    start_date = datetime.now(epg.TZ).date()
    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=days)

    source_tree = parse_source_xml(source_xml)
    source_root = source_tree.getroot()
    logo_urls = load_logo_urls(logos_manifest)
    root = etree.Element(
        "tv",
        **{
            "generator-info-name": "none",
            "generator-info-url": "none",
        },
    )

    channel_elements: list[etree._Element] = []
    programme_elements: list[etree._Element] = []
    mitv_source_days: dict[str, int] = {}
    gatotv_source_days: dict[str, int] = {}
    gatotv_daily_counts: dict[str, dict[str, int]] = {}

    for channel_id in BASE_CHANNEL_IDS:
        if channel_id == TVE_ID:
            config = TVE_MITV_CHANNEL
            channel_elements.append(
                make_channel(
                    config.channel_id,
                    config.names,
                    config.website,
                    icon_url=logo_urls.get(config.channel_id),
                )
            )
            programmes, loaded_days = scrape_mitv_channel(
                country=config.country,
                slug=config.slug,
                channel_id=config.channel_id,
                start_date=start_date,
                local_days=mitv_days,
            )
            mitv_source_days[config.channel_id] = loaded_days
            programme_elements.extend(epg.make_programme(item) for item in programmes)
            continue

        channel_element = copy.deepcopy(source_channel(source_root, channel_id))
        set_channel_icon(channel_element, logo_urls.get(channel_id))
        channel_elements.append(channel_element)
        programme_elements.extend(
            source_programmes(
                source_root,
                channel_id,
                window_start,
                window_end,
            )
        )

    for config in MITV_CHANNELS:
        channel_elements.append(
            make_channel(
                config.channel_id,
                config.names,
                config.website,
                icon_url=logo_urls.get(config.channel_id),
            )
        )
        programmes, loaded_days = scrape_mitv_channel(
            country=config.country,
            slug=config.slug,
            channel_id=config.channel_id,
            start_date=start_date,
            local_days=mitv_days,
        )
        mitv_source_days[config.channel_id] = loaded_days
        programme_elements.extend(epg.make_programme(item) for item in programmes)

    for config in GATOTV_CHANNELS:
        channel_elements.append(
            make_channel(
                config.channel_id,
                config.names,
                config.website,
                icon_url=logo_urls.get(config.channel_id),
            )
        )
        programmes, loaded_days, daily_counts = scrape_gatotv_channel(
            config,
            start_date,
            gatotv_days,
        )
        gatotv_source_days[config.channel_id] = loaded_days
        gatotv_daily_counts[config.channel_id] = daily_counts
        programme_elements.extend(epg.make_programme(item) for item in programmes)

    ecuador_channel, ecuador_programmes, ecuador_status = combine_ecuador_tv(
        source_root=source_root,
        start_date=start_date,
        days=days,
    )
    channel_elements.append(ecuador_channel)
    programme_elements.extend(ecuador_programmes)

    for channel in channel_elements:
        root.append(channel)
    programme_elements.sort(
        key=lambda item: (
            item.get("start", ""),
            item.get("channel", ""),
            " ".join(item.xpath("./title/text()")),
        )
    )
    for programme in programme_elements:
        root.append(programme)

    tree = etree.ElementTree(root)
    programme_counts = validate_latam_tree(tree, dtd_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_xml_and_gzip(
        tree,
        output_dir / "latam.xml",
        output_dir / "latam.xml.gz",
    )

    now = datetime.now(epg.TZ)
    status: dict[str, object] = {
        "version": EPG_VERSION,
        "generated_at": now.isoformat(),
        "base_date": start_date.isoformat(),
        "window_days": days,
        "mitv_local_days": mitv_days,
        "gatotv_requested_days": gatotv_days,
        "channels": len(LATAM_CHANNEL_IDS),
        "programmes": sum(programme_counts.values()),
        "programme_counts": programme_counts,
        "mitv_source_days": mitv_source_days,
        "gatotv_source_days": gatotv_source_days,
        "gatotv_daily_counts": gatotv_daily_counts,
        "gatotv_time_offsets_minutes": {
            config.channel_id: config.time_offset_minutes
            for config in GATOTV_CHANNELS
        },
        "logos_manifest": logos_manifest.name if logos_manifest is not None else None,
        "logos_available": sorted(logo_urls),
        "ecuador_tv": ecuador_status,
        "sources": {
            "base_guide": source_xml.name,
            "epgshare": epg.EPGSHARE_URL,
            "ecuador_tv_official": ECUADOR_TV_URL,
            "ecuador_tv_official_home": ECUADOR_TV_HOME_URL,
            "mi_tv": {
                TVE_ID: TVE_MITV_URL,
                **{
                    config.channel_id: (
                        f"https://mi.tv/{config.country}/canales/{config.slug}"
                    )
                    for config in MITV_CHANNELS
                },
            },
            "gato_tv": {
                config.channel_id: config.base_url
                for config in GATOTV_CHANNELS
            },
        },
    }
    (output_dir / "latam-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_index(output_dir)
    return status


def self_test() -> None:
    assert len(LATAM_CHANNEL_IDS) == 26
    assert LATAM_CHANNEL_IDS[3] == TVE_ID
    assert TVE_MITV_CHANNEL.country == "co"
    assert TVE_MITV_CHANNEL.slug == "tve"
    assert TVE_MITV_CHANNEL.channel_id == TVE_ID
    assert len(set(LATAM_CHANNEL_IDS)) == len(LATAM_CHANNEL_IDS)

    sample = """
    <html><body>
      <h2>jueves, 06 de agosto de 2026</h2>
      <div>Noticias 7 Noticias 7 Primera Emisión 07:00 - 08:30 onAir</div>
      <div>Hogar y Estilo de vida Esto es Ecuador 08:30 - 09:30</div>
      <div>Educación, Cultura y Medio Ambiente Aprendamos 09:30 - 10:00</div>
      <div>Series y Novelas El cuento de la rosa 10:00 - 11:00</div>
      <div>Deportivo Fanático 11:00 - 12:00</div>
      <div>Informativo y opinión Perspectiva 7 12:00 - 13:00</div>
    </body></html>
    """
    programmes, dates = parse_ecuador_tv_page(
        sample,
        date(2026, 8, 6),
        2,
    )
    assert dates == {date(2026, 8, 6)}
    assert len(programmes) == 6
    assert programmes[0].title == "Noticias 7 Primera Emisión"
    assert programmes[0].start.isoformat() == "2026-08-06T07:00:00-05:00"

    partial_sample = """
    <html><body>
      <div>Categoría Programa Series y Novelas Honores Policiales 20:00 - 20:30</div>
      <div>Categoría Programa Deportivo Fanático 21:00 - 22:00</div>
    </body></html>
    """
    partial_programmes, partial_dates = parse_ecuador_tv_page(
        partial_sample,
        date(2026, 8, 12),
        1,
    )
    assert partial_dates == {date(2026, 8, 12)}
    assert len(partial_programmes) == 2
    assert partial_programmes[0].title == "Honores Policiales"
    assert partial_programmes[0].start.isoformat() == "2026-08-12T20:00:00-05:00"

    packed_sample = """
    <html><body>
      <div>Honores Policiales 20:00 - 20:30 Categoría Programa Deportivo Fanático 21:00 - 22:00</div>
    </body></html>
    """
    packed_programmes, packed_dates = parse_ecuador_tv_page(
        packed_sample,
        date(2026, 8, 12),
        1,
    )
    assert packed_dates == {date(2026, 8, 12)}
    assert [item.title for item in packed_programmes] == ["Honores Policiales", "Fanático"]

    combined = programme_from_schedule_text(
        "Series y Novelas Estas Secretarias 22:30 - 23:30",
        date(2026, 8, 6),
        ECUADOR_TV_ID,
    )
    assert combined is not None
    assert combined.title == "Estas Secretarias"

    assert len(LATAM_CHANNEL_IDS) == 26
    assert len(set(LATAM_CHANNEL_IDS)) == 26
    assert "hgtv.ar" in LATAM_CHANNEL_IDS
    assert "France24Espanol.fr" in LATAM_CHANNEL_IDS
    assert "Canal24Horas.es" in LATAM_CHANNEL_IDS
    assert "La1.es" in LATAM_CHANNEL_IDS
    assert "TVEStarHD.es" in LATAM_CHANNEL_IDS
    assert "Clan.es" in LATAM_CHANNEL_IDS
    assert LATAM_CHANNEL_IDS[-1] == ECUADOR_TV_ID

    gatotv_sample = """
    <html><body><table>
      <tr><th>Hora Inicio</th><th>Hora Fin</th><th>Programa</th></tr>
      <tr><td>23:20</td><td>00:10</td><td>Víctimas del misterio</td></tr>
      <tr><td>00:10</td><td>01:10</td><td>Salón de té La Moderna</td></tr>
      <tr><td>01:10</td><td>02:10</td><td>Seis hermanas</td></tr>
      <tr><td>02:10</td><td>02:35</td><td>Flash moda</td></tr>
      <tr><td>02:35</td><td>03:05</td><td>Centenario Tous</td></tr>
    </table></body></html>
    """
    gatotv_programmes = parse_gatotv_page(
        gatotv_sample,
        date(2026, 8, 11),
        "TVEStarHD.es",
    )
    assert len(gatotv_programmes) == 5
    assert gatotv_programmes[0].start.isoformat() == "2026-08-10T23:20:00-05:00"
    assert gatotv_programmes[0].stop.isoformat() == "2026-08-11T00:10:00-05:00"

    # STAR TVE: corrección observada en la señal real de Ecuador el 11-08-2026.
    star_config = next(
        config for config in GATOTV_CHANNELS if config.channel_id == "TVEStarHD.es"
    )
    assert star_config.time_offset_minutes == -60
    star_sample = [
        epg.Programme(
            channel_id="TVEStarHD.es",
            start=datetime(2026, 8, 11, 20, 15, tzinfo=epg.TZ),
            stop=datetime(2026, 8, 11, 21, 10, tzinfo=epg.TZ),
            title="La promesa",
            description=None,
        ),
        epg.Programme(
            channel_id="TVEStarHD.es",
            start=datetime(2026, 8, 11, 21, 10, tzinfo=epg.TZ),
            stop=datetime(2026, 8, 11, 22, 15, tzinfo=epg.TZ),
            title="Los misterios de Laura",
            description=None,
        ),
    ]
    shifted = shift_programmes(star_sample, star_config.time_offset_minutes)
    assert shifted[0].start.isoformat() == "2026-08-11T19:15:00-05:00"
    assert shifted[0].stop.isoformat() == "2026-08-11T20:10:00-05:00"
    assert shifted[1].start.isoformat() == "2026-08-11T20:10:00-05:00"
    assert shifted[1].stop.isoformat() == "2026-08-11T21:15:00-05:00"
    print(
        "Prueba latam correcta: 26 IDs únicos, France 24 Español y 4 canales GatoTV incluidos; STAR TVE -60 min y overlay parcial Ecuador TV validados."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-xml", type=Path, default=Path("public/ec.xml"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--dtd", type=Path)
    parser.add_argument(
        "--logos-manifest",
        type=Path,
        default=Path("public/logos/manifest.json"),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("GUIDE_DAYS", "7")),
    )
    parser.add_argument(
        "--mitv-days",
        type=int,
        default=int(os.environ.get("MITV_LOCAL_DAYS", "2")),
    )
    parser.add_argument(
        "--gatotv-days",
        type=int,
        default=int(os.environ.get("GATOTV_DAYS", os.environ.get("GUIDE_DAYS", "7"))),
    )
    args = parser.parse_args()

    if not args.source_xml.is_file():
        parser.error(f"No existe la guía base: {args.source_xml}")
    if not 1 <= args.days <= 7:
        parser.error("--days debe estar entre 1 y 7.")
    if not 1 <= args.mitv_days <= 2:
        parser.error("--mitv-days debe estar entre 1 y 2.")
    if not 1 <= args.gatotv_days <= 7:
        parser.error("--gatotv-days debe estar entre 1 y 7.")
    if args.dtd is not None and not args.dtd.is_file():
        parser.error(f"No existe el DTD: {args.dtd}")
    if args.logos_manifest is not None and not args.logos_manifest.is_file():
        epg.warn(
            f"No existe el manifiesto de logos {args.logos_manifest}; "
            "la guía se generará sin logos locales nuevos."
        )
        args.logos_manifest = None

    status = build_latam(
        source_xml=args.source_xml,
        output_dir=args.output,
        dtd_path=args.dtd,
        days=args.days,
        mitv_days=args.mitv_days,
        gatotv_days=args.gatotv_days,
        logos_manifest=args.logos_manifest,
    )
    epg.log(json.dumps(status, ensure_ascii=False, indent=2))
    epg.log(f"Guía latam generada en: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    try:
        raise SystemExit(main())
    except (requests.RequestException, etree.XMLSyntaxError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)

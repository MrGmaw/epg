#!/usr/bin/env python3
"""Construye ``latam.xml`` con los 27 canales seleccionados.

La guía principal ``ec.xml`` se genera primero y actúa como fuente estable
para los canales base, excepto TVE Internacional. TVE Internacional toma su
programación exclusivamente de mi.tv Colombia. Después se añaden los otros
canales de mi.tv, cuatro parrillas de GatoTV, MakroDigital TV desde su parrilla
oficial semanal y la parrilla oficial de Ecuador TV cuando está disponible.
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
from zoneinfo import ZoneInfo
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
ECUADOR_TV_NEWS_URL = "https://www.ecuadortv.ec/noticias"
ECUADOR_TV_PROBE_URLS = (
    "https://www.ecuadortv.ec/programas/deportivo/fanatico",
    "https://www.ecuadortv.ec/programas/informativo-y-opinion/perspectiva-7",
    "https://www.ecuadortv.ec/programas/hogar-y-estilo-de-vida/esto-es-ecuador",
    "https://www.ecuadortv.ec/programas/series-y-novelas/honores-policiales",
)
ECUADOR_TV_SCHEDULE_URLS = (
    ECUADOR_TV_URL,
    *ECUADOR_TV_PROBE_URLS,
    ECUADOR_TV_NEWS_URL,
    ECUADOR_TV_HOME_URL,
)
# Guardia temporal basada en la parrilla oficial visible y contraste de señal
# del 13-08-2026. Solo entra cuando el HTML oficial no aporta el bloque.
# Caduca para no convertir una parrilla verificada hoy en una verdad eterna.
ECUADOR_TV_VERIFIED_EVENING_VALID_UNTIL = date(2026, 8, 31)
ECUADOR_TV_VERIFIED_EVENING = (
    (time(20, 0), time(21, 0), "Honores Policiales"),
    (time(21, 0), time(22, 0), "Fanático"),
    (time(22, 0), time(22, 30), "Un Café con JJ"),
    (time(22, 30), time(23, 30), "Estas Secretarias"),
    (time(23, 30), time(0, 0), "Noticiero NCC Climático"),
)
ECUADOR_TV_ID = "Canal.Ecuador.TV.ec"
MAKRODIGITAL_URL = "https://makrodigitaltelevision.com/programacion/"
MAKRODIGITAL_WEBSITE = "https://makrodigitaltelevision.com/"
MAKRODIGITAL_ID = "MakroDigitalTV.ec"
MAKRODIGITAL_SOURCE_TIMEZONE = "America/New_York"
# GatoTV entrega para STAR TVE el reloj de origen en notación 24 h o AM/PM
# según la respuesta. El 13-08-2026, 16:00 de ese reloj correspondió a una
# emisión comprobada en Ecuador a las 10:00. Ambas notaciones se interpretan
# con esta zona IANA y se convierten a America/Guayaquil, sin offset manual.
STAR_GATOTV_SOURCE_TIMEZONE = "Atlantic/Canary"
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
    source_timezone: str | None = None
    prefer_ampm_local: bool = False

    @property
    def base_url(self) -> str:
        return f"https://www.gatotv.com/canal/{self.slug}"


@dataclass(frozen=True)
class MakroWeeklyItem:
    title: str
    start: time
    stop: time


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
        source_timezone=STAR_GATOTV_SOURCE_TIMEZONE,
        prefer_ampm_local=False,
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
    MAKRODIGITAL_ID,
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
MAKRO_WEEKDAYS = {
    **WEEKDAYS,
    "sabados": 5,
    "domingos": 6,
}
MAKRO_TIME_RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}(?::\d{2})?\s*(?:AM|PM))\s*"
    r"(?:-|–|—|\ba\b)\s*"
    r"(?P<stop>\d{1,2}(?::\d{2})?\s*(?:AM|PM))",
    re.I,
)
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


def _is_ecuador_tv_metadata(value: str) -> bool:
    """Indica si un fragmento cercano a un horario no puede ser un título."""

    raw = epg.normalize_text(value).strip()
    if raw.startswith("(") and raw.endswith(")"):
        return True
    text = raw.strip(" ·|:-–—()[]")
    if not text:
        return True
    key = normalized(text)
    if key in {
        "categoria programa",
        "programacion",
        "programación",
        "onair",
        "on air",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
    }:
        return True
    if any(key == normalized(category) for category in ECUADOR_TV_CATEGORIES):
        return True
    if key in {
        "entretenimiento",
        "opinion",
        "informativo",
        "deportivo",
        "formativo",
        "infantil",
    }:
        return True
    if key.startswith("clasificacion") or key.startswith("clasificación"):
        return True
    if key.startswith("apto para"):
        return True
    return False


def _recent_ecuador_tv_title(recent_lines: Sequence[str]) -> str | None:
    """Busca hacia atrás el título real de la tarjeta de programación.

    En la web oficial el DOM puede separar ``título``, clasificación, categoría
    y rango horario en nodos distintos. v0.2.3 solo miraba el nodo anterior;
    v0.2.4 salta esos metadatos y recupera el título de la misma tarjeta.
    """

    for candidate in reversed(recent_lines[-8:]):
        if TIME_RANGE_RE.search(candidate) is not None:
            break
        if parse_spanish_date(candidate) is not None:
            continue
        if RECURRENCE_RE.search(normalized(candidate)) is not None:
            continue
        if _is_ecuador_tv_metadata(candidate):
            continue
        title = clean_ecuador_tv_title(candidate)
        if not title or _is_ecuador_tv_metadata(title):
            continue
        if len(title) > 140:
            continue
        return title
    return None


def parse_ecuador_tv_page(
    page: str,
    start_date: date,
    days: int,
    channel_id: str = ECUADOR_TV_ID,
) -> tuple[list[epg.Programme], set[date]]:
    """Extrae emisiones válidas de la parrilla oficial de Ecuador TV.

    La parrilla puede separar título, clasificación, categoría y horario en
    nodos HTML distintos. Además, la misma página contiene fechas históricas de
    noticias o vídeos que no deben cambiar la fecha de la parrilla vigente.
    Desde v0.2.4 se mantiene una ventana de contexto por tarjeta, se ignoran
    fechas ajenas a la ventana solicitada y se deduplican las versiones
    desktop/móvil por hora de inicio.
    """

    soup = BeautifulSoup(page, "lxml")
    for unwanted in soup.find_all(("script", "style", "noscript", "svg")):
        unwanted.decompose()
    lines = [epg.normalize_text(value) for value in soup.stripped_strings]
    lines = [value for value in lines if value]

    window_end_date = start_date + timedelta(days=days)
    # La cabecera de programación de Ecuador TV corresponde al día local actual.
    # Solo una fecha explícita DENTRO de la ventana puede cambiar esta fecha.
    current_date = start_date
    recent_lines: list[str] = []
    by_date: dict[date, list[epg.Programme]] = defaultdict(list)

    for raw_line in lines:
        line = raw_line
        explicit_date = parse_spanish_date(line)
        if explicit_date is not None:
            if start_date <= explicit_date < window_end_date:
                current_date = explicit_date
            # Fechas históricas de artículos/vídeos no contaminan la parrilla.
            if TIME_RANGE_RE.search(line) is None:
                recent_lines.append(line)
                recent_lines = recent_lines[-12:]
                continue
            line = DATE_RE.sub("", line).strip(" ,:-–—|")

        weekday_line = normalized(line).strip(" ,:")
        if weekday_line in WEEKDAYS and TIME_RANGE_RE.search(line) is None:
            weekday_date = date_for_weekday(start_date, weekday_line)
            if weekday_date is not None and start_date <= weekday_date < window_end_date:
                current_date = weekday_date
            recent_lines.append(line)
            recent_lines = recent_lines[-12:]
            continue

        if TIME_RANGE_RE.search(line) is None:
            recent_lines.append(line)
            recent_lines = recent_lines[-12:]
            continue
        if RECURRENCE_RE.search(normalized(line)) is not None:
            # Horarios generales de fichas de programas, no la parrilla diaria.
            recent_lines.append(line)
            recent_lines = recent_lines[-12:]
            continue

        previous_title = _recent_ecuador_tv_title(recent_lines)
        line_programmes = programmes_from_schedule_text(
            line,
            current_date,
            channel_id,
            previous_text=previous_title,
        )
        by_date[current_date].extend(line_programmes)
        recent_lines.append(line)
        recent_lines = recent_lines[-12:]

    accepted_dates: set[date] = set()
    programmes: list[epg.Programme] = []
    for guide_date, entries in sorted(by_date.items()):
        # La página puede repetir la parrilla para escritorio/móvil o en varias
        # zonas del DOM. Una sola emisión puede comenzar a una hora determinada;
        # conservamos la primera aparición, que corresponde a la fuente prioritaria.
        deduplicated: dict[str, epg.Programme] = {}
        for programme in sorted(entries, key=lambda item: (item.start, item.stop)):
            if not programme.title or _is_ecuador_tv_metadata(programme.title):
                continue
            deduplicated.setdefault(programme.start.isoformat(), programme)
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


def _gatotv_rows(container: Tag | BeautifulSoup) -> tuple[list[tuple[time, time, str, str | None]], int]:
    """Extrae filas horarias y cuenta cuántas usan AM/PM explícito."""

    rows: list[tuple[time, time, str, str | None]] = []
    meridiem_rows = 0
    for row in container.find_all("tr"):
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
        if any(re.search(r"\b(?:AM|PM)\b", value, re.I) for value in parts[:after_stop]):
            meridiem_rows += 1
        rows.append((start_clock, stop_clock, title, description))
    return rows, meridiem_rows




def _gatotv_24h_rows_from_flat_text(
    container: Tag | BeautifulSoup,
) -> list[tuple[time, time, str, str | None]]:
    """Fallback para la representación 24 h de GatoTV sin filas ``<tr>``.

    GatoTV no siempre entrega al runner de GitHub la parrilla 24 h como una
    tabla HTML tradicional. En algunas respuestas los datos siguen presentes
    en el texto de la página, pero distribuidos en ``div``/``span`` u otros
    nodos. Este parser trabaja únicamente con pares de relojes de 24 horas;
    deliberadamente NO acepta AM/PM para que STAR TVE no vuelva a mezclar la
    representación horaria alternativa.
    """

    text = epg.normalize_text(container.get_text(" ", strip=True))
    if not text:
        return []

    # Acotar el análisis a la parrilla evita confundir fechas, canales y otros
    # relojes de navegación con emisiones reales.
    # Preferir el encabezado de columnas porque GatoTV puede repetir
    # "Horarios de Programación" en menús y navegación antes de la parrilla.
    # En v0.2.7 se tomaba la primera coincidencia y luego se recortaba en el
    # primer símbolo ‹, que puede aparecer ANTES de las emisiones reales.
    # Eso dejaba el texto vacío en GitHub Actions.
    columns_header = "Hora Inicio Hora Fin Programa"
    columns_index = text.find(columns_header)
    if columns_index >= 0:
        text = text[columns_index:]
    else:
        schedule_index = text.rfind("Horarios de Programación")
        if schedule_index >= 0:
            text = text[schedule_index:]

    for marker in ("Etiquetas:", "Disponibilidad", "La guía de Televisión"):
        index = text.find(marker)
        if index >= 0:
            text = text[:index]

    # No recortar por los símbolos ‹/›: también se usan en la navegación que
    # precede a la tabla. Si quedan pegados al último título, se limpian por
    # fila más abajo.

    # Los rótulos de franja pueden quedar entre el título anterior y el reloj
    # siguiente al aplanar el HTML. Se eliminan antes de dividir las filas.
    text = re.sub(r"\b(?:Madrugada|Mañana|Tarde|Noche)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()

    clock = r"(?:[01]?\d|2[0-3]):[0-5]\d"
    row_pattern = re.compile(
        rf"(?<![\d:])(?P<start>{clock})\s*(?:[-–—]\s*)?"
        rf"(?P<stop>{clock})\s+"
        rf"(?P<body>.*?)"
        rf"(?=(?:{clock})\s*(?:[-–—]\s*)?(?:{clock})\s+|$)",
        re.I | re.S,
    )

    rows: list[tuple[time, time, str, str | None]] = []
    for match in row_pattern.finditer(text):
        body = epg.normalize_text(match.group("body")).strip(" :-–—|")
        if not body:
            continue
        # Evitar que la navegación final quede pegada al último título si el
        # sitio cambia de símbolo pero mantiene el mismo patrón textual.
        body = re.split(r"\s+[‹›]\s*", body, maxsplit=1)[0].strip()
        if not body:
            continue
        try:
            start_clock = datetime.strptime(match.group("start"), "%H:%M").time()
            stop_clock = datetime.strptime(match.group("stop"), "%H:%M").time()
        except ValueError:
            continue
        rows.append((start_clock, stop_clock, body, None))

    return rows


def _gatotv_rows_from_flat_text_any_clock(
    container: Tag | BeautifulSoup,
) -> tuple[list[tuple[time, time, str, str | None]], int]:
    """Recupera la parrilla aplanada en 24 h o AM/PM.

    GitHub Actions puede recibir GatoTV sin filas ``<tr>`` y, además, con la
    notación AM/PM. Para STAR TVE la notación no determina la zona: tanto 24 h
    como AM/PM representan el reloj de origen y después se convierten mediante
    ``source_timezone``. Se devuelve también el número de filas AM/PM para
    diagnóstico/selección.
    """

    text = epg.normalize_text(container.get_text(" ", strip=True))
    if not text:
        return [], 0

    columns_header = "Hora Inicio Hora Fin Programa"
    columns_index = text.find(columns_header)
    if columns_index >= 0:
        text = text[columns_index:]
    else:
        schedule_index = text.rfind("Horarios de Programación")
        if schedule_index >= 0:
            text = text[schedule_index:]

    for marker_text in ("Etiquetas:", "Disponibilidad", "La guía de Televisión"):
        index = text.find(marker_text)
        if index >= 0:
            text = text[:index]

    text = re.sub(r"\b(?:Madrugada|Mañana|Tarde|Noche)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()

    # Acepta 16:00 o 4:00 PM / 04:00 P.M. El segundo reloj debe usar la misma
    # sintaxis general, no necesariamente el mismo meridiem.
    clock = r"(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*(?:A\.?M\.?|P\.?M\.?))?"
    row_pattern = re.compile(
        rf"(?<![\d:])(?P<start>{clock})\s*(?:[-–—]\s*)?"
        rf"(?P<stop>{clock})\s+"
        rf"(?P<body>.*?)"
        rf"(?=(?:{clock})\s*(?:[-–—]\s*)?(?:{clock})\s+|$)",
        re.I | re.S,
    )

    def parse_clock_token(value: str) -> time | None:
        token = re.sub(r"\.", "", epg.normalize_text(value)).upper()
        token = re.sub(r"\s+", " ", token).strip()
        for pattern in ("%H:%M", "%I:%M %p"):
            try:
                return datetime.strptime(token, pattern).time()
            except ValueError:
                continue
        return None

    rows: list[tuple[time, time, str, str | None]] = []
    meridiem_rows = 0
    for match in row_pattern.finditer(text):
        body = epg.normalize_text(match.group("body")).strip(" :-–—|")
        body = re.split(r"\s+[‹›]\s*", body, maxsplit=1)[0].strip()
        if not body:
            continue
        start_text = match.group("start")
        stop_text = match.group("stop")
        start_clock = parse_clock_token(start_text)
        stop_clock = parse_clock_token(stop_text)
        if start_clock is None or stop_clock is None:
            continue
        if re.search(r"\b(?:A\.?M\.?|P\.?M\.?)\b", start_text + " " + stop_text, re.I):
            meridiem_rows += 1
        rows.append((start_clock, stop_clock, body, None))

    return rows, meridiem_rows


def _convert_gatotv_rows(
    rows: list[tuple[time, time, str, str | None]],
    guide_date: date,
    channel_id: str,
    clock_timezone: ZoneInfo,
) -> list[epg.Programme]:
    """Convierte el reloj de una tabla GatoTV a ``America/Guayaquil``."""

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
        source_start = datetime.combine(start_day, start_clock, tzinfo=clock_timezone)
        source_stop = datetime.combine(stop_day, stop_clock, tzinfo=clock_timezone)
        start = source_start.astimezone(epg.TZ)
        stop = source_stop.astimezone(epg.TZ)
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
    return sorted(
        deduplicated.values(),
        key=lambda item: (item.start, item.stop, item.title),
    )


def parse_gatotv_page(
    page: str,
    guide_date: date,
    channel_id: str,
    *,
    source_timezone: str | None = None,
    prefer_ampm_local: bool = False,
) -> list[epg.Programme]:
    """Lee una fecha de GatoTV y normaliza el resultado a Guayaquil.

    Cuando ``source_timezone`` está definido, esa zona es la única referencia
    horaria aceptada. GatoTV puede servir la misma parrilla en notación 24 h o
    AM/PM; ambas se fechan en la zona fuente y se convierten con ``ZoneInfo`` a
    ``America/Guayaquil``. La notación AM/PM nunca se interpreta directamente
    como hora local de Ecuador. No se aplica ningún desplazamiento fijo.
    """

    soup = BeautifulSoup(page, "lxml")
    candidates: list[
        tuple[list[tuple[time, time, str, str | None]], int]
    ] = []
    for table in soup.find_all("table"):
        rows, meridiem_rows = _gatotv_rows(table)
        if len(rows) >= 5:
            candidates.append((rows, meridiem_rows))

    if not candidates:
        rows, meridiem_rows = _gatotv_rows(soup)
        if len(rows) >= 5:
            candidates.append((rows, meridiem_rows))

    # STAR TVE puede llegar al runner en dos notaciones del MISMO reloj de
    # origen: 24 h o AM/PM. Lo importante no es la notación, sino la zona que
    # representa ese reloj. En ambos casos se interpreta con ``source_timezone``
    # y después se convierte con ZoneInfo a America/Guayaquil. Así evitamos
    # depender del formato que GatoTV decida servir a GitHub Actions.
    #
    # Si no hay tabla/fila estructurada, conservamos además el fallback 24 h
    # desde texto aplanado.
    if source_timezone is not None:
        flat_rows, flat_meridiem_rows = _gatotv_rows_from_flat_text_any_clock(soup)
        if len(flat_rows) >= 5:
            candidates.append((flat_rows, flat_meridiem_rows))
        else:
            # Conservamos el parser 24 h específico como segunda defensa ante
            # cambios menores de espaciado/markup.
            flat_24h_rows = _gatotv_24h_rows_from_flat_text(soup)
            if len(flat_24h_rows) >= 5:
                candidates.append((flat_24h_rows, 0))

    if not candidates:
        if source_timezone is not None:
            raise RuntimeError(
                "GatoTV: no se encontró programación suficiente en tabla "
                "ni en el texto estructurado de la página."
            )
        return epg.parse_gatotv_page(page, guide_date, channel_id)

    if source_timezone is not None:
        # Tanto 24 h como AM/PM son solo formas de escribir el mismo reloj de
        # origen. Nunca se interpreta AM/PM directamente como Guayaquil.
        selected = max(candidates, key=lambda item: len(item[0]))
        clock_timezone = ZoneInfo(source_timezone)
    elif prefer_ampm_local:
        ampm_candidates = [item for item in candidates if item[1] >= 5]
        selected = max(ampm_candidates or candidates, key=lambda item: len(item[0]))
        clock_timezone = epg.TZ
    else:
        selected = max(candidates, key=lambda item: len(item[0]))
        clock_timezone = epg.TZ
    rows, _meridiem_rows = selected

    result = _convert_gatotv_rows(
        rows,
        guide_date,
        channel_id,
        clock_timezone,
    )
    if len(result) < 5:
        raise RuntimeError(
            f"GatoTV: solo se encontraron {len(result)} emisiones "
            f"para {guide_date.isoformat()}."
        )
    return result


def scrape_gatotv_channel(
    config: GatoTvChannel,
    start_date: date,
    days: int,
) -> tuple[list[epg.Programme], int, dict[str, int]]:
    """Descarga GatoTV tolerando días futuros aún no publicados.

    Un canal con ``source_timezone`` consulta un día fuente adicional para que
    la conversión a Guayaquil no deje sin cubrir las últimas horas del último
    día local solicitado. El resultado final siempre se recorta a la ventana
    local solicitada.
    """

    all_programmes: list[epg.Programme] = []
    loaded_days = 0
    daily_counts: dict[str, int] = {}
    fetch_days = days + (1 if config.source_timezone is not None else 0)
    for offset in range(fetch_days):
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
                source_timezone=config.source_timezone,
                prefer_ampm_local=config.prefer_ampm_local,
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
                        source_timezone=config.source_timezone,
                        prefer_ampm_local=config.prefer_ampm_local,
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

        all_programmes.extend(day_programmes)
        loaded_days += 1
        daily_counts[guide_date.isoformat()] = len(day_programmes)
        epg.log(
            f"GatoTV {config.channel_id}: {guide_date.isoformat()}="
            f"{len(day_programmes)} emisiones."
        )

    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=days)
    deduplicated: dict[tuple[str, str, str], epg.Programme] = {}
    for programme in all_programmes:
        if not (programme.start < window_end and programme.stop > window_start):
            continue
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


def parse_makro_clock(value: str) -> time:
    text = re.sub(r"\s+", " ", epg.normalize_text(value)).upper()
    for pattern in ("%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    raise ValueError(f"Hora MakroDigital no reconocida: {value!r}")


def _makro_day_headings(soup: BeautifulSoup) -> list[tuple[Tag, int]]:
    headings: list[tuple[Tag, int]] = []
    for tag in soup.find_all(["h2", "h3", "h4", "h5", "h6"]):
        key = normalized(tag.get_text(" ", strip=True))
        if key in MAKRO_WEEKDAYS:
            headings.append((tag, MAKRO_WEEKDAYS[key]))
    return headings


def _is_makro_placeholder_title(value: str | None) -> bool:
    """Detecta separadores/decoración que nunca deben convertirse en título."""

    if value is None:
        return True
    cleaned = epg.normalize_text(value).strip()
    if not cleaned:
        return True
    # El sitio inserta guiones/separadores como nodos de texto entre el título
    # y el rango horario. Si se aceptan, XMLTV termina con <title>-</title>.
    return re.fullmatch(r"[-–—|•·_.:/\\]+", cleaned) is not None


def _makro_section_lines(heading: Tag) -> list[str]:
    lines: list[str] = []
    for element in heading.next_elements:
        if element is heading:
            continue
        if isinstance(element, Tag):
            if element.name in {"h2", "h3", "h4", "h5", "h6"}:
                key = normalized(element.get_text(" ", strip=True))
                if key in MAKRO_WEEKDAYS:
                    break
            continue
        if not isinstance(element, str):
            continue
        value = epg.normalize_text(element)
        if value:
            lines.append(value)
    return lines


def parse_makro_weekly(page: str) -> dict[int, list[MakroWeeklyItem]]:
    """Extrae la parrilla semanal oficial de MakroDigital Televisión."""

    soup = BeautifulSoup(page, "lxml")
    headings = _makro_day_headings(soup)
    weekly: dict[int, list[MakroWeeklyItem]] = defaultdict(list)
    clock_only_re = re.compile(r"^\d{1,2}(?::\d{2})?\s*(?:AM|PM)$", re.I)

    for heading, weekday in headings:
        recent_title: str | None = None
        pending_start: str | None = None
        for line in _makro_section_lines(heading):
            matches = list(MAKRO_TIME_RANGE_RE.finditer(line))
            if matches:
                for match in matches:
                    prefix = epg.normalize_text(line[: match.start()]).strip(" :-–—|")
                    if _is_makro_placeholder_title(prefix):
                        prefix = ""
                    title = prefix or recent_title
                    if _is_makro_placeholder_title(title):
                        continue
                    try:
                        start_clock = parse_makro_clock(match.group("start"))
                        stop_clock = parse_makro_clock(match.group("stop"))
                    except ValueError:
                        continue
                    weekly[weekday].append(
                        MakroWeeklyItem(
                            title=epg.normalize_text(title),
                            start=start_clock,
                            stop=stop_clock,
                        )
                    )
                recent_title = None
                pending_start = None
                continue

            if clock_only_re.fullmatch(line):
                if pending_start is None:
                    pending_start = line
                    continue
                if recent_title:
                    try:
                        weekly[weekday].append(
                            MakroWeeklyItem(
                                title=epg.normalize_text(recent_title),
                                start=parse_makro_clock(pending_start),
                                stop=parse_makro_clock(line),
                            )
                        )
                    except ValueError:
                        pass
                pending_start = None
                recent_title = None
                continue

            key = normalized(line).strip(" :-–—|")
            if key in MAKRO_WEEKDAYS or key in {
                "programacion",
                "read more",
                "hora inicio",
                "hora fin",
                "programa",
            }:
                continue
            if (
                not re.search(r"\d{1,2}(?::\d{2})?\s*(?:AM|PM)", line, re.I)
                and not _is_makro_placeholder_title(line)
            ):
                recent_title = line

    result: dict[int, list[MakroWeeklyItem]] = {}
    for weekday in range(7):
        deduplicated: dict[tuple[str, str], MakroWeeklyItem] = {}
        for item in weekly.get(weekday, []):
            key = (item.start.isoformat(), normalized(item.title))
            deduplicated.setdefault(key, item)
        items = sorted(deduplicated.values(), key=lambda item: (item.start, item.title))
        invalid_titles = [item.title for item in items if _is_makro_placeholder_title(item.title)]
        if invalid_titles:
            raise RuntimeError(
                f"MakroDigital: títulos decorativos inválidos detectados: {invalid_titles!r}."
            )
        if len(items) < 5:
            raise RuntimeError(
                "MakroDigital: la parrilla oficial no contiene suficientes "
                f"emisiones para el día semanal {weekday}."
            )
        result[weekday] = items
    return result


def makro_programmes_for_window(
    weekly: dict[int, list[MakroWeeklyItem]],
    start_date: date,
    days: int,
) -> tuple[list[epg.Programme], int]:
    """Instancia la parrilla NEW YORK y la convierte a Guayaquil con DST."""

    source_tz = ZoneInfo(MAKRODIGITAL_SOURCE_TIMEZONE)
    window_start = datetime.combine(start_date, time.min, tzinfo=epg.TZ)
    window_end = window_start + timedelta(days=days)
    programmes: list[epg.Programme] = []
    repaired_ranges = 0

    for source_offset in range(-1, days + 2):
        source_date = start_date + timedelta(days=source_offset)
        items = weekly[source_date.weekday()]
        next_date = source_date + timedelta(days=1)
        next_day_items = weekly[next_date.weekday()]

        for index, item in enumerate(items):
            source_start = datetime.combine(source_date, item.start, tzinfo=source_tz)
            stop_date = source_date if item.stop > item.start else source_date + timedelta(days=1)
            source_stop = datetime.combine(stop_date, item.stop, tzinfo=source_tz)

            if index + 1 < len(items):
                next_item = items[index + 1]
                next_start = datetime.combine(source_date, next_item.start, tzinfo=source_tz)
                if next_start <= source_start:
                    next_start += timedelta(days=1)
            elif next_day_items:
                next_start = datetime.combine(next_date, next_day_items[0].start, tzinfo=source_tz)
            else:
                next_start = None

            # La web contiene al menos un rango histórico mal formado
            # (5:30 AM - 5:00 AM). Si el fin cruza por encima del siguiente
            # inicio o produce una duración absurda, el siguiente inicio es la
            # frontera más segura del bloque.
            if next_start is not None and (
                source_stop > next_start
                or source_stop - source_start > timedelta(hours=8)
            ):
                source_stop = next_start
                repaired_ranges += 1

            if source_stop <= source_start:
                continue
            local_start = source_start.astimezone(epg.TZ)
            local_stop = source_stop.astimezone(epg.TZ)
            if not (local_start < window_end and local_stop > window_start):
                continue
            programmes.append(
                epg.Programme(
                    channel_id=MAKRODIGITAL_ID,
                    start=local_start,
                    stop=local_stop,
                    title=item.title,
                    description=None,
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
        raise RuntimeError("MakroDigital: no se obtuvo programación suficiente.")
    return result, repaired_ranges


def scrape_makrodigital(
    start_date: date,
    days: int,
) -> tuple[list[epg.Programme], dict[str, int], int]:
    page = epg.fetch_text(
        MAKRODIGITAL_URL,
        headers={"Referer": MAKRODIGITAL_WEBSITE},
    )
    weekly = parse_makro_weekly(page)
    programmes, repaired_ranges = makro_programmes_for_window(
        weekly,
        start_date,
        days,
    )
    weekly_counts = {
        str(weekday): len(items)
        for weekday, items in sorted(weekly.items())
    }
    epg.log(
        f"MakroDigital TV: {len(programmes)} emisiones locales; "
        f"rangos reparados={repaired_ranges}."
    )
    return programmes, weekly_counts, repaired_ranges


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


def verified_ecuador_tv_evening_programmes(
    start_date: date,
    days: int,
) -> list[epg.Programme]:
    """Guardia de contingencia para la franja oficial verificada en vivo.

    Se usa únicamente hasta la fecha de caducidad y solo de lunes a viernes.
    La fuente oficial scrapeada siempre tiene prioridad; estos bloques evitan
    que EPGShare vuelva a publicar ``Telediario`` cuando el sitio oficial se
    renderiza vacío para GitHub Actions.
    """

    programmes: list[epg.Programme] = []
    for offset in range(days):
        guide_date = start_date + timedelta(days=offset)
        if guide_date > ECUADOR_TV_VERIFIED_EVENING_VALID_UNTIL:
            continue
        if guide_date.weekday() >= 5:
            continue
        for start_clock, stop_clock, title in ECUADOR_TV_VERIFIED_EVENING:
            stop_date = guide_date if stop_clock > start_clock else guide_date + timedelta(days=1)
            programmes.append(
                epg.Programme(
                    channel_id=ECUADOR_TV_ID,
                    start=datetime.combine(guide_date, start_clock, tzinfo=epg.TZ),
                    stop=datetime.combine(stop_date, stop_clock, tzinfo=epg.TZ),
                    title=title,
                    description=None,
                )
            )
    return programmes


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

    official_by_key: dict[str, epg.Programme] = {}
    official_sources: list[str] = []
    for schedule_url in ECUADOR_TV_SCHEDULE_URLS:
        try:
            page = epg.fetch_text(
                schedule_url,
                headers={
                    "Referer": "https://www.ecuadortv.ec/",
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/139.0 Safari/537.36"
                    ),
                    "Accept-Language": "es-EC,es;q=0.9,en;q=0.5",
                },
            )
            page_programmes, _page_dates = parse_ecuador_tv_page(
                page,
                start_date,
                days,
            )
            if page_programmes:
                official_sources.append(schedule_url)
            for item in page_programmes:
                # Una sola emisión por hora de inicio. El orden de
                # ECUADOR_TV_SCHEDULE_URLS define la prioridad entre vistas.
                official_by_key.setdefault(item.start.isoformat(), item)
        except (requests.RequestException, RuntimeError) as exc:
            epg.warn(f"Ecuador TV oficial {schedule_url}: {exc}")

    # Guardia de contingencia de la franja nocturna verificada. La parrilla
    # scrapeada conserva prioridad; si existe el mismo título a la misma hora
    # pero con un fin anterior a la siguiente tarjeta verificada, se amplía al
    # fin verificado (caso Honores Policiales 20:00 -> siguiente inicio 21:00).
    verified_candidates = verified_ecuador_tv_evening_programmes(start_date, days)
    verified_used: list[epg.Programme] = []
    verified_adjusted = 0
    for verified in verified_candidates:
        key = verified.start.isoformat()
        current = official_by_key.get(key)
        if current is None:
            official_by_key[key] = verified
            verified_used.append(verified)
            continue
        if (
            normalized(current.title) == normalized(verified.title)
            and current.stop < verified.stop
        ):
            official_by_key[key] = verified
            verified_used.append(verified)
            verified_adjusted += 1

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
        source_name = "official_or_verified_overlay+epgshare_fallback"
    elif official_programmes:
        source_name = "official_or_verified"
    else:
        source_name = "epgshare_fallback"

    if official_programmes:
        epg.log(
            "Ecuador TV: "
            f"{len(official_programmes)} bloques oficial/verificados superpuestos; "
            f"{len(verified_used)} de contingencia; "
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
        "verified_evening_programmes": len(verified_used),
        "verified_evening_adjusted": verified_adjusted,
        "verified_evening_valid_until": ECUADOR_TV_VERIFIED_EVENING_VALID_UNTIL.isoformat(),
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

    channel_elements.append(
        make_channel(
            MAKRODIGITAL_ID,
            ("MakroDigital TV", "MakroDigital Televisión"),
            MAKRODIGITAL_WEBSITE,
        )
    )
    makro_programmes, makro_weekly_counts, makro_repaired_ranges = scrape_makrodigital(
        start_date,
        days,
    )
    programme_elements.extend(epg.make_programme(item) for item in makro_programmes)

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
        "gatotv_source_timezones": {
            config.channel_id: (config.source_timezone or "America/Guayaquil")
            for config in GATOTV_CHANNELS
        },
        "gatotv_ampm_local_preferred": {
            config.channel_id: config.prefer_ampm_local
            for config in GATOTV_CHANNELS
        },
        "makrodigital": {
            "source": MAKRODIGITAL_URL,
            "source_timezone": MAKRODIGITAL_SOURCE_TIMEZONE,
            "target_timezone": "America/Guayaquil",
            "weekly_counts": makro_weekly_counts,
            "programmes": len(makro_programmes),
            "repaired_ranges": makro_repaired_ranges,
        },
        "logos_manifest": logos_manifest.name if logos_manifest is not None else None,
        "logos_available": sorted(logo_urls),
        "ecuador_tv": ecuador_status,
        "sources": {
            "base_guide": source_xml.name,
            "epgshare": epg.EPGSHARE_URL,
            "ecuador_tv_official": ECUADOR_TV_URL,
            "ecuador_tv_official_news": ECUADOR_TV_NEWS_URL,
            "ecuador_tv_official_home": ECUADOR_TV_HOME_URL,
            "ecuador_tv_official_probes": list(ECUADOR_TV_PROBE_URLS),
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
            "makrodigital_official": MAKRODIGITAL_URL,
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
    assert len(LATAM_CHANNEL_IDS) == 27
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

    # Estructura observada en la web oficial el 12-08-2026: el título puede
    # quedar separado de la hora por clasificación/categoría. También hay
    # fechas históricas de contenido que no deben mover la parrilla vigente.
    card_sample = """
    <html><body>
      <div>martes, 04 de agosto de 2026</div>
      <article><h3>Honores Policiales</h3><span>A</span><span>(Entretenimiento)</span><time>20:00 - 20:30</time></article>
      <article><h3>Fanático</h3><span>A</span><span>(Deportivo)</span><time>21:00 - 22:00</time></article>
      <article><h3>Un Café con JJ</h3><span>A</span><span>(Opinión)</span><time>22:00 - 22:30</time></article>
      <article><h3>Estas Secretarias</h3><span>B</span><span>(Entretenimiento)</span><time>22:30 - 23:30</time></article>
      <article><h3>Noticiero NCC Climático</h3><span>A</span><span>(Informativo)</span><time>23:30 - 00:00</time></article>
    </body></html>
    """
    card_programmes, card_dates = parse_ecuador_tv_page(
        card_sample,
        date(2026, 8, 12),
        1,
    )
    assert card_dates == {date(2026, 8, 12)}
    assert [(item.title, item.start.strftime("%H:%M"), item.stop.strftime("%H:%M")) for item in card_programmes] == [
        ("Honores Policiales", "20:00", "20:30"),
        ("Fanático", "21:00", "22:00"),
        ("Un Café con JJ", "22:00", "22:30"),
        ("Estas Secretarias", "22:30", "23:30"),
        ("Noticiero NCC Climático", "23:30", "00:00"),
    ]

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

    assert len(LATAM_CHANNEL_IDS) == 27
    assert len(set(LATAM_CHANNEL_IDS)) == 27
    assert "hgtv.ar" in LATAM_CHANNEL_IDS
    assert "France24Espanol.fr" in LATAM_CHANNEL_IDS
    assert "Canal24Horas.es" in LATAM_CHANNEL_IDS
    assert "La1.es" in LATAM_CHANNEL_IDS
    assert "TVEStarHD.es" in LATAM_CHANNEL_IDS
    assert "Clan.es" in LATAM_CHANNEL_IDS
    assert MAKRODIGITAL_ID in LATAM_CHANNEL_IDS
    assert LATAM_CHANNEL_IDS[-2] == MAKRODIGITAL_ID
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

    # STAR TVE se reconstruye sin offsets manuales. La representación 24 h
    # observada en GatoTV el 13-08-2026 sitúa Salón de té La Moderna a las
    # 16:00; interpretada con la zona fuente inferida y convertida a Guayaquil
    # debe quedar exactamente 10:00-11:00, como en la señal real.
    star_config = next(
        config for config in GATOTV_CHANNELS if config.channel_id == "TVEStarHD.es"
    )
    assert star_config.source_timezone == STAR_GATOTV_SOURCE_TIMEZONE
    assert star_config.prefer_ampm_local is False
    assert not hasattr(star_config, "time_offset_minutes")
    star_24h_sample = """
    <html><body><table>
      <tr><th>Hora Inicio</th><th>Hora Fin</th><th>Programa</th></tr>
      <tr><td>14:30</td><td>15:30</td><td>El condensador de Fluzo</td></tr>
      <tr><td>15:30</td><td>16:00</td><td>Viaje al centro de la tele</td></tr>
      <tr><td>16:00</td><td>17:00</td><td>Salón de té La Moderna</td></tr>
      <tr><td>17:00</td><td>17:50</td><td>La promesa</td></tr>
      <tr><td>17:50</td><td>18:50</td><td>La promesa</td></tr>
    </table></body></html>
    """
    star_programmes = parse_gatotv_page(
        star_24h_sample,
        date(2026, 8, 13),
        "TVEStarHD.es",
        source_timezone=star_config.source_timezone,
        prefer_ampm_local=star_config.prefer_ampm_local,
    )
    salon = next(item for item in star_programmes if item.title == "Salón de té La Moderna")
    assert salon.start.isoformat() == "2026-08-13T10:00:00-05:00"
    assert salon.stop.isoformat() == "2026-08-13T11:00:00-05:00"

    # Regresión v0.2.9: GitHub Actions puede recibir la misma parrilla en
    # notación AM/PM. Esa notación NO es hora de Guayaquil: sigue siendo el
    # reloj Atlantic/Canary y debe pasar por la misma conversión ZoneInfo.
    star_ampm_source_sample = """
    <html><body><table>
      <tr><th>Hora Inicio</th><th>Hora Fin</th><th>Programa</th></tr>
      <tr><td>2:30 PM</td><td>3:30 PM</td><td>El condensador de Fluzo</td></tr>
      <tr><td>3:30 PM</td><td>4:00 PM</td><td>Viaje al centro de la tele</td></tr>
      <tr><td>4:00 PM</td><td>5:00 PM</td><td>Salón de té La Moderna</td></tr>
      <tr><td>5:00 PM</td><td>5:50 PM</td><td>La promesa</td></tr>
      <tr><td>5:50 PM</td><td>6:50 PM</td><td>La promesa</td></tr>
    </table></body></html>
    """
    star_ampm_source = parse_gatotv_page(
        star_ampm_source_sample,
        date(2026, 8, 13),
        "TVEStarHD.es",
        source_timezone=star_config.source_timezone,
        prefer_ampm_local=star_config.prefer_ampm_local,
    )
    ampm_salon = next(
        item for item in star_ampm_source if item.title == "Salón de té La Moderna"
    )
    assert ampm_salon.start.isoformat() == "2026-08-13T10:00:00-05:00"
    assert ampm_salon.stop.isoformat() == "2026-08-13T11:00:00-05:00"

    star_ampm_evening_sample = """
    <html><body><table>
      <tr><th>Hora Inicio</th><th>Hora Fin</th><th>Programa</th></tr>
      <tr><td>12:10 AM</td><td>1:00 AM</td><td>Acacias 38</td></tr>
      <tr><td>1:00 AM</td><td>2:00 AM</td><td>La promesa</td></tr>
      <tr><td>2:00 AM</td><td>3:05 AM</td><td>Estoy vivo</td></tr>
      <tr><td>3:05 AM</td><td>4:00 AM</td><td>Seis hermanas</td></tr>
      <tr><td>4:00 AM</td><td>5:00 AM</td><td>La Moderna</td></tr>
    </table></body></html>
    """
    star_ampm_evening = parse_gatotv_page(
        star_ampm_evening_sample,
        date(2026, 8, 14),
        "TVEStarHD.es",
        source_timezone=star_config.source_timezone,
        prefer_ampm_local=star_config.prefer_ampm_local,
    )
    ampm_estoy_vivo = next(
        item for item in star_ampm_evening if item.title == "Estoy vivo"
    )
    assert ampm_estoy_vivo.start.isoformat() == "2026-08-13T20:00:00-05:00"
    assert ampm_estoy_vivo.stop.isoformat() == "2026-08-13T21:05:00-05:00"

    star_flat_ampm_sample = """
    <html><body>
      <section>
        <h2>Horarios de Programación</h2>
        <div>Hora Inicio Hora Fin Programa</div>
        <div>2:30 PM</div><div>3:30 PM</div><div>El condensador de Fluzo</div>
        <div>3:30 PM</div><div>4:00 PM</div><div>Viaje al centro de la tele</div>
        <div>4:00 PM</div><div>5:00 PM</div><div>Salón de té La Moderna</div>
        <div>5:00 PM</div><div>5:50 PM</div><div>La promesa</div>
        <div>5:50 PM</div><div>6:50 PM</div><div>La promesa</div>
        <div>Etiquetas:</div>
      </section>
    </body></html>
    """
    star_flat_ampm = parse_gatotv_page(
        star_flat_ampm_sample,
        date(2026, 8, 13),
        "TVEStarHD.es",
        source_timezone=star_config.source_timezone,
        prefer_ampm_local=star_config.prefer_ampm_local,
    )
    flat_ampm_salon = next(
        item for item in star_flat_ampm if item.title == "Salón de té La Moderna"
    )
    assert flat_ampm_salon.start.isoformat() == "2026-08-13T10:00:00-05:00"
    assert flat_ampm_salon.stop.isoformat() == "2026-08-13T11:00:00-05:00"

    # Regresión v0.2.8: GatoTV puede entregar la misma parrilla 24 h sin
    # filas <tr>. Debe recuperarse desde el texto sin aceptar la variante
    # AM/PM que también puede aparecer en la página.
    star_flat_24h_sample = """
    <html><body>
      <div>AM/PM 24 Hrs</div>
      <section>
        <h2>Horarios de Programación</h2>
        <div>Hora Inicio Hora Fin Programa</div>
        <div>Tarde</div>
        <div>14:30</div><div>15:30</div><div>El condensador de Fluzo</div>
        <div>15:30</div><div>16:00</div><div>Viaje al centro de la tele</div>
        <div>16:00</div><div>17:00</div><div>Salón de té La Moderna</div>
        <div>17:00</div><div>17:50</div><div>La promesa</div>
        <div>17:50</div><div>18:50</div><div>La promesa</div>
        <div>Etiquetas:</div>
      </section>
    </body></html>
    """
    star_flat_programmes = parse_gatotv_page(
        star_flat_24h_sample,
        date(2026, 8, 13),
        "TVEStarHD.es",
        source_timezone=star_config.source_timezone,
        prefer_ampm_local=star_config.prefer_ampm_local,
    )
    assert len(star_flat_programmes) == 5
    flat_salon = next(
        item for item in star_flat_programmes if item.title == "Salón de té La Moderna"
    )
    assert flat_salon.start.isoformat() == "2026-08-13T10:00:00-05:00"
    assert flat_salon.stop.isoformat() == "2026-08-13T11:00:00-05:00"

    # Regresión v0.2.8 para la estructura real observada en GitHub: GatoTV
    # puede incluir un enlace ‹ día anterior › antes del encabezado de columnas.
    # Ese símbolo no debe truncar la parrilla.
    star_nav_before_rows_sample = """
    <html><body>
      <nav><span>Horarios de Programación</span></nav>
      <div>‹ Jueves 13 Horarios para el viernes 14 de agosto de 2026 Sábado 15 ›</div>
      <section>
        <h2>Horarios de Programación</h2>
        <div>Hora Inicio Hora Fin Programa</div>
        <div>Madrugada</div>
        <div>00:05</div><div>01:10</div><div>Salón de té La Moderna</div>
        <div>01:10</div><div>02:00</div><div>Acacias 38</div>
        <div>02:00</div><div>03:00</div><div>La promesa</div>
        <div>03:00</div><div>04:05</div><div>Estoy vivo</div>
        <div>04:05</div><div>05:10</div><div>Un país para reírlo</div>
        <div>‹ Jueves 13 Sábado 15 ›</div>
        <div>Etiquetas:</div>
      </section>
    </body></html>
    """
    star_nav_programmes = parse_gatotv_page(
        star_nav_before_rows_sample,
        date(2026, 8, 14),
        "TVEStarHD.es",
        source_timezone=star_config.source_timezone,
        prefer_ampm_local=star_config.prefer_ampm_local,
    )
    assert len(star_nav_programmes) == 5
    nav_estoy_vivo = next(
        item for item in star_nav_programmes if item.title == "Estoy vivo"
    )
    assert nav_estoy_vivo.start.isoformat() == "2026-08-13T21:00:00-05:00"
    assert nav_estoy_vivo.stop.isoformat() == "2026-08-13T22:05:00-05:00"

    # Prueba de regresión real del 13-08-2026 por la noche: en la tabla fuente
    # del 14-08, ``Estoy vivo`` 02:00-03:05 Atlantic/Canary debe convertirse
    # exactamente en 20:00-21:05 del 13-08 en Guayaquil.
    star_evening_sample = """
    <html><body><table>
      <tr><th>Hora Inicio</th><th>Hora Fin</th><th>Programa</th></tr>
      <tr><td>00:10</td><td>01:00</td><td>Acacias 38</td></tr>
      <tr><td>01:00</td><td>02:00</td><td>La promesa</td></tr>
      <tr><td>02:00</td><td>03:05</td><td>Estoy vivo</td></tr>
      <tr><td>03:05</td><td>04:00</td><td>Seis hermanas</td></tr>
      <tr><td>04:00</td><td>05:00</td><td>La Moderna</td></tr>
    </table></body></html>
    """
    star_evening = parse_gatotv_page(
        star_evening_sample,
        date(2026, 8, 14),
        "TVEStarHD.es",
        source_timezone=star_config.source_timezone,
        prefer_ampm_local=star_config.prefer_ampm_local,
    )
    estoy_vivo = next(item for item in star_evening if item.title == "Estoy vivo")
    assert estoy_vivo.start.isoformat() == "2026-08-13T20:00:00-05:00"
    assert estoy_vivo.stop.isoformat() == "2026-08-13T21:05:00-05:00"

    # MakroDigital publica una parrilla semanal en horario NEW YORK. Se prueba
    # la conversión DST-aware a Guayaquil y la reparación del rango anómalo
    # 5:30 AM - 5:00 AM usando el siguiente inicio (6:00 AM).
    regular = """
      <p>MakroNoticias</p><span>-</span><p>12:00 AM - 12:30 AM</p>
      <p>STV Noticias</p><span>—</span><p>12:30 AM - 1:00 AM</p>
      <p>Vis a Vis con Janet Hinostroza</p><p>1:00 AM - 3:00 AM</p>
      <p>Vis a Vis con Janet Hinostroza</p><p>9:00 AM - 11:00 AM</p>
      <p>MakroNoticias</p><p>11:00 AM - 11:30 AM</p>
    """
    wednesday = """
      <p>MakroNoticias</p><p>12:00 AM - 12:30 AM</p>
      <p>Explorando Ecuador</p><p>4:30 AM - 5:00 AM</p>
      <p>Migración al Día</p><p>5:00 AM - 5:30 AM</p>
      <p>Parada Juvenil</p><p>5:30 AM - 5:00 AM</p>
      <p>Nuestras Riquezas</p><p>6:00 AM - 7:00 AM</p>
      <p>Super Libro Clásico</p><p>7:00 AM - 8:00 AM</p>
    """
    makro_sample = "<html><body>" + "".join(
        f"<h3>{day_name}</h3>" + (wednesday if day_name == "Miércoles" else regular)
        for day_name in (
            "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábados", "Domingos"
        )
    ) + "</body></html>"
    weekly = parse_makro_weekly(makro_sample)
    assert all(
        not _is_makro_placeholder_title(item.title)
        for items in weekly.values()
        for item in items
    )
    assert any(item.title == "MakroNoticias" for item in weekly[3])
    makro_thursday, _ = makro_programmes_for_window(
        weekly, date(2026, 8, 13), 1
    )
    makro_news = next(
        item for item in makro_thursday
        if item.title == "MakroNoticias" and item.start.hour == 10
    )
    assert makro_news.start.isoformat() == "2026-08-13T10:00:00-05:00"
    assert makro_news.stop.isoformat() == "2026-08-13T10:30:00-05:00"
    makro_wednesday, repairs = makro_programmes_for_window(
        weekly, date(2026, 8, 12), 1
    )
    parada = next(item for item in makro_wednesday if item.title == "Parada Juvenil")
    assert parada.start.isoformat() == "2026-08-12T04:30:00-05:00"
    assert parada.stop.isoformat() == "2026-08-12T05:00:00-05:00"
    assert repairs >= 1

    verified_ec = verified_ecuador_tv_evening_programmes(date(2026, 8, 13), 1)
    assert [(item.title, item.start.strftime("%H:%M"), item.stop.strftime("%H:%M")) for item in verified_ec] == [
        ("Honores Policiales", "20:00", "21:00"),
        ("Fanático", "21:00", "22:00"),
        ("Un Café con JJ", "22:00", "22:30"),
        ("Estas Secretarias", "22:30", "23:30"),
        ("Noticiero NCC Climático", "23:30", "00:00"),
    ]
    print(
        "Prueba latam correcta: 27 IDs únicos; STAR TVE 24 h Canary→Guayaquil, "
        "MakroDigital con títulos válidos y contingencia Ecuador TV validadas."
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

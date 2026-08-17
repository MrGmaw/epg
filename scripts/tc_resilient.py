#!/usr/bin/env python3
"""Respaldo resiliente para canales ecuatorianos heredados de EPGShare.

Esta capa existe porque ``ec.xml`` conserva muchos canales de EPGShare, mientras
``latam.xml`` exige programación vigente para un subconjunto de ellos. EPGShare
puede publicar el canal y conservar emisiones antiguas, pero dejar vacía la
ventana actual. En ese caso no conviene derribar toda la guía.

Prioridad por canal protegido:

1. EPGShare, cuando contiene programación vigente suficiente.
2. GatoTV del mismo canal, interpretado directamente en ``America/Guayaquil``
   por el parser genérico del generador base.
3. Última ``ec.xml`` válida de ``epg-data``, reproyectada por día de semana.

Canales protegidos en v0.2.25:
- TC Televisión
- Gamavisión
- RTS
- Ecuador TV
- Ecuavisa nacional (después de su normalización a ``Ecuavisa.ec``)

No se aplican offsets manuales ni se inventan emisiones. Si las tres fuentes
fallan para un canal necesario, la construcción falla de forma explícita.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from lxml import etree
import requests

DEFAULT_CACHE_XML = Path(".cache/previous-ec.xml")
MIN_PROGRAMMES = 5


@dataclass(frozen=True)
class ResilientChannel:
    channel_id: str
    name: str
    gatotv_slug: str

    @property
    def gatotv_base(self) -> str:
        return f"https://www.gatotv.com/canal/{self.gatotv_slug}"


TC = ResilientChannel("Canal.TC.Televisión.ec", "TC Televisión", "tc_television")
GAMAVISION = ResilientChannel("Canal.Gamavisión.ec", "Gamavisión", "gamavision")
RTS = ResilientChannel("Canal.RTS.ec", "RTS", "rts")
ECUADOR_TV = ResilientChannel("Canal.Ecuador.TV.ec", "Ecuador TV", "ecuador_tv")
ECUAVISA = ResilientChannel("Ecuavisa.ec", "Ecuavisa", "ecuavisa_ecuador")

# Estos identificadores ya existen con este nombre dentro de EPGShare y pueden
# repararse inmediatamente después de parse_epgshare(). Ecuavisa es distinto:
# el generador base primero normaliza uno o más IDs de origen a Ecuavisa.ec.
DIRECT_CHANNELS: tuple[ResilientChannel, ...] = (TC, GAMAVISION, RTS, ECUADOR_TV)

# Compatibilidad con el módulo v0.2.24 y trazabilidad ampliada v0.2.25.
TC_ID = TC.channel_id
GATOTV_TC_BASE = TC.gatotv_base
LAST_SOURCE: str | None = None
LAST_PROGRAMMES: int = 0
LAST_GATOTV_DAYS: int = 0
LAST_RESULTS: dict[str, dict[str, object]] = {}


def _parse_xmltv_datetime(value: str, tz) -> datetime:
    """Convierte una fecha XMLTV a ``tz`` tolerando formatos habituales."""
    raw = (value or "").strip()
    for fmt in (
        "%Y%m%d%H%M%S %z",
        "%Y%m%d%H%M %z",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    raise ValueError(f"Fecha XMLTV no reconocida: {value!r}")


def _window(start_date: date, days: int, tz) -> tuple[datetime, datetime]:
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=tz)
    return start, start + timedelta(days=max(1, days))


def _overlaps(programme: etree._Element, start: datetime, end: datetime, tz) -> bool:
    try:
        p_start = _parse_xmltv_datetime(programme.get("start", ""), tz)
        p_stop = _parse_xmltv_datetime(programme.get("stop", ""), tz)
    except ValueError:
        return False
    return p_start < end and p_stop > start


def _current_programmes(
    root: etree._Element,
    channel_id: str,
    start_date: date,
    days: int,
    tz,
) -> list[etree._Element]:
    start, end = _window(start_date, days, tz)
    return [
        programme
        for programme in root.findall("programme")
        if programme.get("channel") == channel_id
        and _overlaps(programme, start, end, tz)
    ]


def _channel_from_root(root: etree._Element, channel_id: str) -> etree._Element | None:
    return next(
        (channel for channel in root.findall("channel") if channel.get("id") == channel_id),
        None,
    )


def _basic_channel(config: ResilientChannel) -> etree._Element:
    channel = etree.Element("channel", id=config.channel_id)
    name = etree.SubElement(channel, "display-name", lang="es")
    name.text = config.name
    url = etree.SubElement(channel, "url")
    url.text = config.gatotv_base
    return channel


def _insert_channel_before_programmes(root: etree._Element, channel: etree._Element) -> None:
    children = list(root)
    index = next(
        (i for i, child in enumerate(children) if child.tag == "programme"),
        len(children),
    )
    root.insert(index, channel)


def _replace_channel(
    root: etree._Element,
    config: ResilientChannel,
    programmes: list[etree._Element],
    *,
    channel: etree._Element | None = None,
) -> None:
    """Sustituye solo ``config`` y conserva intactos todos los demás canales."""
    existing = _channel_from_root(root, config.channel_id)
    source_channel = channel if channel is not None else existing
    replacement = copy.deepcopy(
        source_channel if source_channel is not None else _basic_channel(config)
    )
    replacement.set("id", config.channel_id)

    if existing is not None:
        root.remove(existing)
    for programme in list(root.findall("programme")):
        if programme.get("channel") == config.channel_id:
            root.remove(programme)

    _insert_channel_before_programmes(root, replacement)
    for programme in programmes:
        node = copy.deepcopy(programme)
        node.set("channel", config.channel_id)
        root.append(node)


def _read_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    return etree.parse(str(path), parser)


def load_cached_channel(
    epg,
    cache_xml: Path,
    config: ResilientChannel,
    start_date: date,
    days: int,
) -> tuple[list[etree._Element], etree._Element | None]:
    """Reproyecta la última parrilla válida del canal por día de semana."""
    if not cache_xml.is_file():
        raise RuntimeError(f"No existe la caché XMLTV: {cache_xml}.")

    tree = _read_xml(cache_xml)
    root = tree.getroot()
    source_channel = _channel_from_root(root, config.channel_id)
    if source_channel is None:
        raise RuntimeError(
            f"La caché {cache_xml} no contiene el canal {config.channel_id}."
        )

    by_weekday: dict[int, dict[date, list[tuple[etree._Element, datetime, datetime]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for programme in root.findall("programme"):
        if programme.get("channel") != config.channel_id:
            continue
        try:
            p_start = _parse_xmltv_datetime(programme.get("start", ""), epg.TZ)
            p_stop = _parse_xmltv_datetime(programme.get("stop", ""), epg.TZ)
        except ValueError:
            continue
        if p_stop <= p_start:
            continue
        by_weekday[p_start.weekday()][p_start.date()].append((programme, p_start, p_stop))

    result: list[etree._Element] = []
    for offset in range(max(1, days)):
        target_date = start_date + timedelta(days=offset)
        candidates = by_weekday.get(target_date.weekday(), {})
        valid_days = [
            source_date
            for source_date, rows in candidates.items()
            if len(rows) >= MIN_PROGRAMMES
        ]
        if not valid_days:
            raise RuntimeError(
                f"La caché de {config.name} no contiene una parrilla suficiente "
                f"para weekday={target_date.weekday()} ({target_date.isoformat()})."
            )

        # La fecha más reciente del mismo día de semana es la mejor plantilla.
        source_date = max(valid_days)
        delta = target_date - source_date
        rows = sorted(candidates[source_date], key=lambda item: item[1])
        for programme, p_start, p_stop in rows:
            node = copy.deepcopy(programme)
            node.set("channel", config.channel_id)
            node.set("start", epg.format_xmltv_datetime(p_start + delta))
            node.set("stop", epg.format_xmltv_datetime(p_stop + delta))
            result.append(node)

    if len(result) < MIN_PROGRAMMES:
        raise RuntimeError(
            f"La caché de {config.name} no produjo una parrilla suficiente."
        )
    return result, copy.deepcopy(source_channel)


def _set_result(
    config: ResilientChannel,
    source: str,
    programmes: int,
    gatotv_days: int = 0,
) -> None:
    global LAST_SOURCE, LAST_PROGRAMMES, LAST_GATOTV_DAYS

    record: dict[str, object] = {
        "name": config.name,
        "source": source,
        "programmes": programmes,
    }
    if source == "gatotv":
        record["gatotv"] = config.gatotv_base
        record["gatotv_days"] = gatotv_days
    elif source == "epg-data-cache":
        record["fallback"] = "epg-data/ec.xml"
    LAST_RESULTS[config.channel_id] = record

    # Mantiene las variables que v0.2.24 exponía específicamente para TC.
    if config.channel_id == TC_ID:
        LAST_SOURCE = source
        LAST_PROGRAMMES = programmes
        LAST_GATOTV_DAYS = gatotv_days


def _repair_channel(
    epg,
    root: etree._Element,
    config: ResilientChannel,
    cache_xml: Path,
    start_date: date,
    days: int,
) -> None:
    current = _current_programmes(
        root,
        config.channel_id,
        start_date,
        days,
        epg.TZ,
    )
    if len(current) >= MIN_PROGRAMMES:
        _set_result(config, "epgshare", len(current))
        epg.log(
            f"{config.name}: EPGShare vigente "
            f"({len(current)} emisiones en ventana)."
        )
        return

    epg.warn(
        f"{config.name}: EPGShare no contiene programación vigente suficiente "
        f"({len(current)} emisiones); se probará GatoTV."
    )

    try:
        gatotv_programmes, loaded_days = epg.scrape_gatotv_range(
            config.gatotv_base,
            config.channel_id,
            start_date,
            max(1, days),
        )
        gatotv_nodes = [epg.make_programme(item) for item in gatotv_programmes]
        if len(gatotv_nodes) < MIN_PROGRAMMES:
            raise RuntimeError(
                f"GatoTV produjo solo {len(gatotv_nodes)} emisiones para {config.name}."
            )
        _replace_channel(root, config, gatotv_nodes)
        _set_result(config, "gatotv", len(gatotv_nodes), loaded_days)
        epg.log(
            f"{config.name}: respaldo GatoTV activado; "
            f"{len(gatotv_nodes)} emisiones / {loaded_days} día(s)."
        )
        return
    except (requests.RequestException, RuntimeError, ValueError, OSError) as gatotv_exc:
        epg.warn(
            f"{config.name}: GatoTV no produjo una parrilla utilizable "
            f"({gatotv_exc}); se probará epg-data/ec.xml."
        )

    try:
        cached_nodes, cached_channel = load_cached_channel(
            epg,
            cache_xml,
            config,
            start_date,
            max(1, days),
        )
        _replace_channel(root, config, cached_nodes, channel=cached_channel)
    except (OSError, etree.XMLSyntaxError, RuntimeError, ValueError) as cache_exc:
        raise RuntimeError(
            f"{config.name} ({config.channel_id}) no tiene programación utilizable "
            "en EPGShare, GatoTV ni en la última ec.xml válida de epg-data. "
            f"Último error: {cache_exc}"
        ) from cache_exc

    _set_result(config, "epg-data-cache", len(cached_nodes))
    epg.log(
        f"{config.name}: respaldo epg-data activado; "
        f"{len(cached_nodes)} emisiones reproyectadas por día de semana."
    )


def make_resilient_epgshare_parser(
    epg,
    original_parser: Callable[[], etree._ElementTree],
    cache_xml: Path = DEFAULT_CACHE_XML,
    days: int = 7,
) -> Callable[[], etree._ElementTree]:
    """Envuelve ``parse_epgshare`` y protege los IDs directos usados por LATAM."""

    def resilient_parser() -> etree._ElementTree:
        global LAST_SOURCE, LAST_PROGRAMMES, LAST_GATOTV_DAYS
        LAST_RESULTS.clear()
        LAST_SOURCE = None
        LAST_PROGRAMMES = 0
        LAST_GATOTV_DAYS = 0

        tree = original_parser()
        root = tree.getroot()
        today = datetime.now(epg.TZ).date()
        for config in DIRECT_CHANNELS:
            _repair_channel(
                epg,
                root,
                config,
                cache_xml,
                today,
                max(1, days),
            )
        return tree

    return resilient_parser


def make_resilient_ecuavisa_normalizer(
    epg,
    original_normalizer: Callable[[etree._Element], int],
    cache_xml: Path = DEFAULT_CACHE_XML,
    days: int = 7,
) -> Callable[[etree._Element], int]:
    """Protege Ecuavisa nacional una vez normalizada a ``Ecuavisa.ec``.

    El generador base identifica uno o más IDs de Ecuavisa en EPGShare y los
    consolida en ``Ecuavisa.ec``. Solo después de ese paso podemos comprobar la
    vigencia con el mismo ID que consume ``latam.xml``.
    """

    def resilient_normalizer(root: etree._Element) -> int:
        original_count = 0
        try:
            original_count = original_normalizer(root)
        except RuntimeError as exc:
            # Las dos fallas esperables del normalizador base son ausencia del
            # canal o ausencia total de emisiones. Ambas pueden recuperarse con
            # GatoTV/caché. Cualquier RuntimeError ajeno se vuelve a lanzar.
            if "Ecuavisa" not in str(exc):
                raise
            epg.warn(
                f"Ecuavisa nacional: normalización EPGShare incompleta ({exc}); "
                "se intentará respaldo resiliente."
            )

        today = datetime.now(epg.TZ).date()
        _repair_channel(
            epg,
            root,
            ECUAVISA,
            cache_xml,
            today,
            max(1, days),
        )
        return original_count

    return resilient_normalizer


def _test_programmes(epg, config: ResilientChannel, start_date: date, days: int = 7):
    result = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        for index in range(6):
            start = datetime.combine(
                day,
                datetime.min.time(),
                tzinfo=epg.TZ,
            ) + timedelta(hours=index * 3)
            result.append(
                epg.Programme(
                    channel_id=config.channel_id,
                    start=start,
                    stop=start + timedelta(hours=1),
                    title=f"{config.name} prueba {day.isoformat()} {index}",
                )
            )
    return result


def _test_xml(
    epg,
    start_date: date,
    days: int = 7,
    configs: tuple[ResilientChannel, ...] = DIRECT_CHANNELS,
) -> etree._ElementTree:
    root = etree.Element("tv")
    for config in configs:
        root.append(_basic_channel(config))
        for item in _test_programmes(epg, config, start_date, days):
            root.append(epg.make_programme(item))
    return etree.ElementTree(root)


def self_test(epg) -> None:
    """Pruebas sin red: prioridad, fallback múltiple, caché y Ecuavisa."""
    today = datetime.now(epg.TZ).date()
    original_scraper = epg.scrape_gatotv_range

    # 1. Todos los IDs directos vigentes: GatoTV jamás debe consultarse.
    try:
        def should_not_run(*_args, **_kwargs):
            raise AssertionError("GatoTV no debe consultarse con EPGShare vigente.")

        epg.scrape_gatotv_range = should_not_run
        parser = make_resilient_epgshare_parser(
            epg,
            lambda: _test_xml(epg, today, 1),
            Path("/ruta/inexistente.xml"),
            1,
        )
        result = parser()
        for config in DIRECT_CHANNELS:
            assert LAST_RESULTS[config.channel_id]["source"] == "epgshare"
            assert len(
                _current_programmes(result.getroot(), config.channel_id, today, 1, epg.TZ)
            ) == 6
    finally:
        epg.scrape_gatotv_range = original_scraper

    # 2. TC vigente, Gamavisión/RTS vacíos: los dos deben entrar por GatoTV.
    try:
        root = etree.Element("tv")
        for config in DIRECT_CHANNELS:
            root.append(_basic_channel(config))
        for config in (TC, ECUADOR_TV):
            for item in _test_programmes(epg, config, today, 1):
                root.append(epg.make_programme(item))

        def selective_gatotv(_base, channel_id, start_date, days):
            config = next(c for c in DIRECT_CHANNELS if c.channel_id == channel_id)
            if config not in (GAMAVISION, RTS):
                raise AssertionError(f"GatoTV inesperado para {config.name}")
            return _test_programmes(epg, config, start_date, min(days, 1)), 1

        epg.scrape_gatotv_range = selective_gatotv
        parser = make_resilient_epgshare_parser(
            epg,
            lambda: etree.ElementTree(copy.deepcopy(root)),
            Path("/ruta/inexistente.xml"),
            1,
        )
        result = parser()
        assert LAST_RESULTS[TC.channel_id]["source"] == "epgshare"
        assert LAST_RESULTS[GAMAVISION.channel_id]["source"] == "gatotv"
        assert LAST_RESULTS[RTS.channel_id]["source"] == "gatotv"
        assert LAST_RESULTS[ECUADOR_TV.channel_id]["source"] == "epgshare"
        assert len(
            _current_programmes(result.getroot(), GAMAVISION.channel_id, today, 1, epg.TZ)
        ) == 6
        assert len(
            _current_programmes(result.getroot(), RTS.channel_id, today, 1, epg.TZ)
        ) == 6
    finally:
        epg.scrape_gatotv_range = original_scraper

    # 3. GatoTV falla: los cuatro IDs directos se reproyectan desde caché.
    with TemporaryDirectory() as temp_dir:
        cache_path = Path(temp_dir) / "previous-ec.xml"
        source_monday = today - timedelta(days=today.weekday() + 7)
        cache_tree = _test_xml(epg, source_monday, 7)
        # Ecuavisa también se incluye para probar su capa posterior.
        cache_root = cache_tree.getroot()
        cache_root.append(_basic_channel(ECUAVISA))
        for item in _test_programmes(epg, ECUAVISA, source_monday, 7):
            cache_root.append(epg.make_programme(item))
        cache_path.write_bytes(
            etree.tostring(cache_tree, encoding="UTF-8", xml_declaration=True)
        )
        try:
            def fail_gatotv(*_args, **_kwargs):
                raise RuntimeError("fallo simulado")

            epg.scrape_gatotv_range = fail_gatotv
            empty = etree.Element("tv")
            for config in DIRECT_CHANNELS:
                empty.append(_basic_channel(config))
            parser = make_resilient_epgshare_parser(
                epg,
                lambda: etree.ElementTree(copy.deepcopy(empty)),
                cache_path,
                7,
            )
            result = parser()
            for config in DIRECT_CHANNELS:
                assert LAST_RESULTS[config.channel_id]["source"] == "epg-data-cache"
                current = _current_programmes(
                    result.getroot(), config.channel_id, today, 7, epg.TZ
                )
                assert len(current) == 42

            # 4. Ecuavisa normalizada pero sin emisiones actuales: caché.
            ecuavisa_root = etree.Element("tv")
            ecuavisa_root.append(_basic_channel(ECUAVISA))

            def fake_normalizer(_root):
                return 0

            resilient_normalizer = make_resilient_ecuavisa_normalizer(
                epg,
                fake_normalizer,
                cache_path,
                7,
            )
            resilient_normalizer(ecuavisa_root)
            assert LAST_RESULTS[ECUAVISA.channel_id]["source"] == "epg-data-cache"
            assert len(
                _current_programmes(
                    ecuavisa_root, ECUAVISA.channel_id, today, 7, epg.TZ
                )
            ) == 42
        finally:
            epg.scrape_gatotv_range = original_scraper

    print(
        "Prueba EPGShare resiliente correcta: TC/Gamavisión/RTS/Ecuador TV/"
        "Ecuavisa -> GatoTV -> epg-data, sin offsets manuales.",
        flush=True,
    )

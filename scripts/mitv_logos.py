#!/usr/bin/env python3
"""Descubre, valida y conserva logos de canales obtenidos desde mi.tv.

Los logos se publican siempre como PNG estable en ``public/logos/<tvg-id>.png``.
La fuente remota se redescubre en cada ejecución, pero un PNG ya restaurado desde
la rama ``epg-data`` actúa como caché persistente si mi.tv cambia de CDN o falla.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

import build_epg_base as epg

PUBLIC_LOGO_BASE = "https://mrgmaw.github.io/epg/logos"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MIN_DIMENSION = 32
MAX_DIMENSION = 1200
IMAGE_URL_RE = re.compile(
    r"(?:(?:https?:)?//[^\s\"'<>\\)]+?\.(?:png|jpe?g|webp|gif|avif)(?:\?[^\s\"'<>\\)]*)?)",
    re.I,
)
CSS_URL_RE = re.compile(r"url\((?:['\"])?([^)'\"]+)(?:['\"])?\)", re.I)
NEGATIVE_HINTS = {
    "search", "buscar", "close", "cerrar", "menu", "facebook", "twitter",
    "instagram", "avatar", "sprite", "favicon", "loading", "placeholder",
}


@dataclass(frozen=True)
class LogoTarget:
    country: str
    slug: str
    channel_id: str
    legacy_keys: tuple[str, ...] = ()

    @property
    def page_url(self) -> str:
        return f"https://mi.tv/{self.country}/canales/{self.slug}"


LOGO_TARGETS: tuple[LogoTarget, ...] = (
    LogoTarget("co", "cnn-en-espanol", "Canal.CNN.en.Español.ec", ("co_cnn-en-espanol",)),
    LogoTarget(
        "co",
        "tve",
        "Canal.TVE.Internacional.(Televisión.Española).ec",
        ("co_tve",),
    ),
    LogoTarget("co", "nuestra-tele-noticias-24hs", "NTN24.co", ("co_ntn24", "co_nuestra-tele-noticias-24hs")),
    LogoTarget("co", "rcn", "CanalRCN.co", ("co_rcn", "co_canal-rcn")),
    LogoTarget("co", "caracol", "CaracolTV.co", ("co_caracol",)),
    LogoTarget("co", "el-gourmet", "Canal.Elgourmet.ec", ("co_el-gourmet", "hn_el-gourmet")),
    LogoTarget("co", "history", "Canal.History.co", ("co_history",)),
    LogoTarget("co", "h2", "Canal.History.2.co", ("co_h2",)),
    LogoTarget("ar", "canal-7-capital", "TV.Publica.canal.7.ar", ("ar_canal-7-capital", "ar_tv-publica")),
    LogoTarget("ar", "telefe", "Telefe.ar", ("ar_telefe",)),
    LogoTarget("cl", "deutsche-welle-espanol", "Deutsche.Welle.cl", ("cl_deutsche-welle-espanol", "cl_deutsche-welle")),
    LogoTarget("ar", "hgtv", "hgtv.ar", ("ar_hgtv",)),
)


def local_logo_url(channel_id: str) -> str:
    return f"{PUBLIC_LOGO_BASE}/{channel_id}.png"


def _normalise_candidate(raw: str, page_url: str) -> str | None:
    value = raw.strip().strip("'\"")
    if not value or value.startswith("data:"):
        return None
    if value.startswith("//"):
        value = "https:" + value
    value = urljoin(page_url, value)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _srcset_urls(value: str) -> Iterable[str]:
    for item in value.split(","):
        candidate = item.strip().split()[0] if item.strip() else ""
        if candidate:
            yield candidate


def _score_candidate(url: str, context: str, target: LogoTarget) -> int:
    parsed = urlparse(url)
    haystack = f"{url} {context}".casefold()
    score = 0
    if "/channels/" in parsed.path.casefold():
        score += 100
    if "logo" in haystack:
        score += 45
    if "channel" in haystack or "canal" in haystack:
        score += 25
    if target.slug.casefold() in haystack:
        score += 35
    slug_compact = re.sub(r"[^a-z0-9]", "", target.slug.casefold())
    haystack_compact = re.sub(r"[^a-z0-9]", "", haystack)
    if slug_compact and slug_compact in haystack_compact:
        score += 15
    if "mitvstatic.com" in parsed.netloc.casefold() or "images.mi.tv" in parsed.netloc.casefold():
        score += 30
    if any(hint in haystack for hint in NEGATIVE_HINTS):
        score -= 120
    return score


def discover_logo_candidates(page: str, page_url: str, target: LogoTarget) -> list[str]:
    """Extrae URLs de imagen y las ordena por probabilidad de ser logo de canal."""

    soup = BeautifulSoup(page, "lxml")
    scored: dict[str, int] = {}

    def add(raw: str | None, context: str = "") -> None:
        if not raw:
            return
        url = _normalise_candidate(raw, page_url)
        if url is None:
            return
        score = _score_candidate(url, context, target)
        if score >= 20:
            scored[url] = max(scored.get(url, -999), score)

    for tag in soup.find_all(["img", "source", "meta", "link"]):
        context = " ".join(
            str(tag.get(attr, ""))
            for attr in ("id", "class", "alt", "title", "property", "name", "rel")
        )
        for attr in ("src", "data-src", "data-original", "content", "href"):
            add(tag.get(attr), context)
        for attr in ("srcset", "data-srcset"):
            value = tag.get(attr)
            if isinstance(value, str):
                for item in _srcset_urls(value):
                    add(item, context)

    for tag in soup.find_all(style=True):
        style = str(tag.get("style", ""))
        context = f"{tag.get('id', '')} {tag.get('class', '')} {style}"
        for raw in CSS_URL_RE.findall(style):
            add(raw, context)

    # Algunos sitios dejan la URL únicamente en JSON/JavaScript incrustado.
    for raw in IMAGE_URL_RE.findall(page):
        add(raw, "html-inline")

    return [url for url, _ in sorted(scored.items(), key=lambda item: (-item[1], item[0]))]


def legacy_candidates(target: LogoTarget) -> list[str]:
    """Patrones históricos conocidos de mi.tv; siempre se validan antes de usar."""

    result: list[str] = []
    for key in target.legacy_keys:
        for host in (
            "https://mitvstatic.com/channels",
            "https://images.mi.tv/channels",
            "http://images.mi.tv/channels",
        ):
            result.append(f"{host}/{key}_m.png")
            result.append(f"{host}/{key}.png")
    return result


def image_to_png(payload: bytes) -> tuple[bytes, int, int]:
    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("Imagen vacía o demasiado grande.")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            width, height = image.size
            if width < MIN_DIMENSION or height < MIN_DIMENSION:
                raise ValueError(f"Imagen demasiado pequeña: {width}x{height}.")
            if max(width, height) > MAX_DIMENSION:
                image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA", "LA", "P"}:
                image = image.convert("RGBA")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            final_width, final_height = image.size
            return output.getvalue(), final_width, final_height
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("El recurso no es una imagen válida.") from exc


def validate_cached_png(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    try:
        data, width, height = image_to_png(path.read_bytes())
    except ValueError:
        return None
    # Normaliza también las copias antiguas por si no eran PNG real.
    path.write_bytes(data)
    return width, height


def fetch_candidate_png(url: str, page_url: str) -> tuple[bytes, int, int]:
    response = epg.HTTP.get(
        url,
        headers={"Referer": page_url, "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5"},
        timeout=45,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").casefold()
    if content_type and "image/" not in content_type:
        raise ValueError(f"Content-Type no gráfico: {content_type}")
    return image_to_png(response.content)


def refresh_target(target: LogoTarget, output_dir: Path) -> dict[str, object]:
    output_path = output_dir / f"{target.channel_id}.png"
    cached = validate_cached_png(output_path)
    if cached is None and output_path.exists():
        output_path.unlink()
        epg.warn(f"Logo mi.tv {target.channel_id}: caché inválida descartada.")
    record: dict[str, object] = {
        "page_url": target.page_url,
        "local_url": local_logo_url(target.channel_id),
        "available": cached is not None,
        "source": "cache" if cached else "missing",
        "source_url": None,
    }
    if cached:
        record["width"], record["height"] = cached

    candidates: list[tuple[str, str]] = []
    try:
        page = epg.fetch_text(target.page_url, headers={"Referer": f"https://mi.tv/{target.country}/"})
        candidates.extend((url, "discovered") for url in discover_logo_candidates(page, target.page_url, target))
    except (requests.RequestException, RuntimeError) as exc:
        epg.warn(f"Logo mi.tv {target.channel_id}: no se pudo leer la página: {exc}")

    known = {url for url, _ in candidates}
    for url in legacy_candidates(target):
        if url not in known:
            candidates.append((url, "validated-pattern"))
            known.add(url)

    for url, source in candidates:
        try:
            png, width, height = fetch_candidate_png(url, target.page_url)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            epg.log(f"Logo mi.tv {target.channel_id}: candidato descartado {url}: {exc}")
            continue
        output_path.write_bytes(png)
        record.update(
            {
                "available": True,
                "source": source,
                "source_url": url,
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(png).hexdigest(),
            }
        )
        epg.log(
            f"Logo mi.tv {target.channel_id}: {source} -> {url} "
            f"({width}x{height}), publicado como {output_path.name}."
        )
        return record

    if output_path.is_file():
        payload = output_path.read_bytes()
        record["sha256"] = hashlib.sha256(payload).hexdigest()
        epg.warn(
            f"Logo mi.tv {target.channel_id}: no se encontró una fuente nueva; "
            "se conserva la copia cacheada."
        )
    else:
        epg.warn(f"Logo mi.tv {target.channel_id}: no se encontró logo utilizable.")
    return record


def build_manifest(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    channels: dict[str, dict[str, object]] = {}
    for target in LOGO_TARGETS:
        channels[target.channel_id] = refresh_target(target, output_dir)

    available = [channel_id for channel_id, item in channels.items() if item.get("available")]
    missing = [channel_id for channel_id, item in channels.items() if not item.get("available")]
    manifest: dict[str, object] = {
        "generated_at": datetime.now(epg.TZ).isoformat(),
        "public_base_url": PUBLIC_LOGO_BASE,
        "targets": len(LOGO_TARGETS),
        "available": len(available),
        "missing": missing,
        "channels": channels,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    epg.log(f"Logos mi.tv: disponibles {len(available)}/{len(LOGO_TARGETS)}.")
    return manifest


def load_logo_urls(manifest_path: Path | None) -> dict[str, str]:
    if manifest_path is None or not manifest_path.is_file():
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    channels = data.get("channels", {})
    if not isinstance(channels, dict):
        return {}
    result: dict[str, str] = {}
    for channel_id, item in channels.items():
        if isinstance(item, dict) and item.get("available") and isinstance(item.get("local_url"), str):
            result[str(channel_id)] = str(item["local_url"])
    return result


def self_test() -> None:
    target = LogoTarget("co", "history", "Canal.History.co", ("co_history",))
    sample = """
    <html><head><meta property="og:image" content="https://cdn.example.test/site/share.png"></head>
    <body>
      <img class="search-icon" src="https://cdn.example.test/search.png" alt="Buscar">
      <div class="channel-logo"><img src="https://assets.example.test/channels/co_history_m.webp" alt="History logo"></div>
    </body></html>
    """
    candidates = discover_logo_candidates(sample, target.page_url, target)
    assert candidates[0] == "https://assets.example.test/channels/co_history_m.webp"

    image = Image.new("RGBA", (160, 90), (20, 40, 60, 255))
    source = io.BytesIO()
    image.save(source, format="WEBP")
    png, width, height = image_to_png(source.getvalue())
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (width, height) == (160, 90)
    assert len(LOGO_TARGETS) == 12
    assert {item.channel_id for item in LOGO_TARGETS} >= {
        "Canal.History.co",
        "hgtv.ar",
        "NTN24.co",
        "Canal.TVE.Internacional.(Televisión.Española).ec",
    }
    print("Prueba logos mi.tv correcta: descubrimiento, filtrado y conversión PNG validados.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("public/logos"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    build_manifest(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

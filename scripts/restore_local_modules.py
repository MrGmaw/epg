#!/usr/bin/env python3
"""Restaura dependencias Python locales faltantes desde el historial Git.

``py_compile`` valida sintaxis pero no resuelve imports. Este helper analiza los
imports de los generadores, busca módulos ``scripts/<modulo>.py`` ausentes en el
historial completo del repositorio y restaura la versión histórica más reciente.
El análisis es recursivo para cubrir dependencias de dependencias.
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import deque
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def historical_blob(relative_path: str) -> tuple[str, str] | None:
    result = git("rev-list", "--all", "--", relative_path, check=False)
    if result.returncode != 0:
        return None
    for commit in result.stdout.splitlines():
        commit = commit.strip()
        if not commit:
            continue
        probe = git("cat-file", "-e", f"{commit}:{relative_path}", check=False)
        if probe.returncode != 0:
            continue
        blob = git("show", f"{commit}:{relative_path}")
        if blob.stdout:
            return commit, blob.stdout
    return None


def restore_module(module: str) -> Path | None:
    parts = module.split(".")
    candidates = [
        Path("scripts", *parts).with_suffix(".py"),
        Path("scripts", *parts, "__init__.py"),
    ]
    for relative in candidates:
        destination = REPO_ROOT / relative
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        found = historical_blob(relative.as_posix())
        if found is None:
            continue
        commit, content = found
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        print(f"Módulo local restaurado: {relative.as_posix()} desde {commit[:12]}")
        return destination
    return None


def imports_from(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise RuntimeError(f"No se pudo analizar {path}: {exc}") from exc

    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    result.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def resolve_initial(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "files",
        nargs="*",
        default=[],
        help="Generadores iniciales a analizar; por defecto todos los scripts .py presentes.",
    )
    args = parser.parse_args()

    if args.files:
        initial = [resolve_initial(value) for value in args.files]
    else:
        initial = sorted(SCRIPTS_DIR.glob("*.py"))

    queue: deque[Path] = deque(initial)
    seen_files: set[Path] = set()
    seen_modules: set[str] = set()
    restored: list[Path] = []

    while queue:
        path = queue.popleft().resolve()
        if path in seen_files:
            continue
        seen_files.add(path)

        for imported in sorted(imports_from(path)):
            # Para dependencias del repositorio basta con resolver su módulo superior;
            # imports externos/stdlib simplemente no tendrán blob bajo scripts/.
            top = imported.split(".", 1)[0]
            if top in seen_modules:
                continue
            seen_modules.add(top)

            local_py = SCRIPTS_DIR / f"{top}.py"
            local_pkg = SCRIPTS_DIR / top / "__init__.py"
            if local_py.is_file():
                queue.append(local_py)
                continue
            if local_pkg.is_file():
                queue.append(local_pkg)
                continue

            restored_path = restore_module(top)
            if restored_path is not None:
                restored.append(restored_path)
                queue.append(restored_path)

    print(
        "Dependencias locales verificadas: "
        f"{len(seen_files)} archivo(s) analizado(s), {len(restored)} restaurado(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

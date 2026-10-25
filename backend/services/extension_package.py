"""Zip de la extensión de Chrome, siempre de la versión desplegada.

El zip se arma en memoria a partir de los mismos ficheros que lleva la imagen
(``chrome-extension/`` copiado en el Dockerfile) y la versión sale de su
``manifest.json``: no hay paso de build que olvidar ni artefacto que se quede
atrás. Es determinista (fechas y permisos fijos), así que todos los workers
sirven exactamente los mismos bytes.
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[2] / "chrome-extension"

# Lo que Chrome necesita para "Cargar descomprimida". Los mismos ficheros que
# empaqueta build.sh en el .crx; ni tests, ni node_modules, ni dist/.
RUNTIME_FILES = ("manifest.json", "popup.html", "popup.css", "popup.js", "background.js", "icons")

# Carpeta raíz dentro del zip: al descomprimir queda una carpeta que se carga
# (o se sustituye) tal cual en chrome://extensions.
ZIP_ROOT = "the-agency"

_FIXED_DATE = (1980, 1, 1, 0, 0, 0)

# Novedades de cada versión, la más reciente primero. No va en el zip: es lo
# que enseña Ajustes junto al botón ("actualizada el…"). Al subir la versión del
# manifest hay que añadir aquí su entrada (lo vigila test_extension_download).
RELEASE_NOTES = "novedades.json"


class ExtensionPackageUnavailable(RuntimeError):
    """Faltan ficheros de la extensión en este despliegue."""


@dataclass(frozen=True)
class ExtensionPackage:
    version: str
    filename: str
    content: bytes


def read_version(root: Path | None = None) -> str:
    root = root or EXTENSION_DIR
    try:
        version = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError) as exc:
        raise ExtensionPackageUnavailable("manifest.json no disponible") from exc
    if not isinstance(version, str) or not version:
        raise ExtensionPackageUnavailable("manifest.json sin versión")
    return version


@dataclass(frozen=True)
class Release:
    version: str
    date: date
    changes: tuple[str, ...]


def read_release_notes(root: Path | None = None) -> list[Release]:
    """Entregas de ``novedades.json``, la más reciente primero. Vacío si falta el
    fichero; mal formado, error (lo caza el test antes de desplegar)."""
    path = (root or EXTENSION_DIR) / RELEASE_NOTES
    if not path.is_file():
        return []
    return [
        Release(version=str(item["version"]), date=date.fromisoformat(item["date"]),
                changes=tuple(str(change) for change in item["changes"]))
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]


def package_filename(version: str) -> str:
    return f"the-agency-extension-v{version}.zip"


def _runtime_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for name in RUNTIME_FILES:
        path = root / name
        if path.is_dir():
            paths.extend(p for p in path.rglob("*") if p.is_file() and p.name != ".DS_Store")
        elif path.is_file():
            paths.append(path)
        else:
            raise ExtensionPackageUnavailable(f"Falta {name} en {root}")
    return sorted(paths)


def _fingerprint(root: Path) -> tuple:
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in _runtime_paths(root))


@lru_cache(maxsize=4)
def _build(root: Path, _fingerprint: tuple) -> ExtensionPackage:
    version = read_version(root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _runtime_paths(root):
            info = zipfile.ZipInfo(f"{ZIP_ROOT}/{path.relative_to(root).as_posix()}", date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return ExtensionPackage(version=version, filename=package_filename(version), content=buffer.getvalue())


def build_package(root: Path | None = None) -> ExtensionPackage:
    """Zip de la versión actual. Se arma una vez y se rehace sólo si cambian los ficheros."""
    root = root or EXTENSION_DIR
    return _build(root, _fingerprint(root))

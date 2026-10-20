"""Descarga de la extensión: siempre la versión del código desplegado."""
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services import extension_package
from backend.services.extension_package import RUNTIME_FILES, ZIP_ROOT, build_package

REPO = Path(__file__).resolve().parents[2]
SOURCE_VERSION = json.loads((REPO / "chrome-extension" / "manifest.json").read_text())["version"]


def _zip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


async def test_served_zip_contains_manifest_with_source_version(member_client):
    res = await member_client.get("/api/extension/download")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert f'filename="the-agency-extension-v{SOURCE_VERSION}.zip"' in res.headers["content-disposition"]
    archive = _zip(res.content)
    manifest = json.loads(archive.read(f"{ZIP_ROOT}/manifest.json"))
    assert manifest["version"] == SOURCE_VERSION


async def test_served_zip_is_loadable_and_carries_only_runtime_files(member_client):
    names = set(_zip((await member_client.get("/api/extension/download")).content).namelist())

    for name in ("manifest.json", "popup.html", "popup.css", "popup.js", "background.js"):
        assert f"{ZIP_ROOT}/{name}" in names
    # Cada icono que pide el manifest viene dentro (si no, Chrome rechaza la carga).
    manifest = json.loads((REPO / "chrome-extension" / "manifest.json").read_text())
    for icon in manifest["icons"].values():
        assert f"{ZIP_ROOT}/{icon}" in names
    assert not any(re.search(r"/(tests|node_modules|dist)/|\.pem$|package(-lock)?\.json$", n) for n in names)


async def test_info_reports_the_version_that_would_be_downloaded(member_client):
    res = await member_client.get("/api/extension")

    assert res.status_code == 200
    assert res.json() == {
        "version": SOURCE_VERSION,
        "filename": f"the-agency-extension-v{SOURCE_VERSION}.zip",
        "download_url": "/api/extension/download",
    }


@pytest.mark.parametrize("path", ["/api/extension", "/api/extension/download"])
async def test_download_requires_login(path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anonymous:
        res = await anonymous.get(path)
    assert res.status_code == 401


def test_zip_is_deterministic_and_follows_manifest_changes(tmp_path):
    root = tmp_path / "chrome-extension"
    (root / "icons").mkdir(parents=True)
    for name in ("popup.html", "popup.css", "popup.js", "background.js"):
        (root / name).write_text(name)
    (root / "icons" / "icon16.png").write_bytes(b"png")
    (root / "manifest.json").write_text(json.dumps({"version": "9.0.0"}))

    first = build_package(root)
    extension_package._build.cache_clear()
    assert build_package(root).content == first.content
    assert first.filename == "the-agency-extension-v9.0.0.zip"

    (root / "manifest.json").write_text(json.dumps({"version": "9.0.10"}))
    bumped = build_package(root)
    assert json.loads(_zip(bumped.content).read(f"{ZIP_ROOT}/manifest.json"))["version"] == "9.0.10"
    assert bumped.filename == "the-agency-extension-v9.0.10.zip"


async def test_missing_runtime_file_is_a_clear_503(member_client, monkeypatch, tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "1.0.0"}))
    monkeypatch.setattr(extension_package, "EXTENSION_DIR", tmp_path)

    res = await member_client.get("/api/extension/download")

    assert res.status_code == 503


def test_docker_image_ships_every_runtime_file():
    """El zip se arma desde la imagen: el Dockerfile tiene que copiar lo que empaqueta."""
    dockerfile = (REPO / "Dockerfile").read_text().replace("\\\n", " ")
    copied = {
        source.rstrip("/")
        for line in dockerfile.splitlines() if line.startswith("COPY ") and "--from" not in line
        for source in line.split()[1:-1]
    }
    for name in RUNTIME_FILES:
        assert f"chrome-extension/{name}" in copied, name

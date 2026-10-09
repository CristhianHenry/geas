#!/usr/bin/env python3
"""
Arma la extensión para cada navegador a partir de la carpeta extension/:

    python build_extension.py firefox    -> dist/firefox/ y dist/geas-firefox-<versión>.zip

Chrome y Edge cargan extension/ tal cual ("Cargar descomprimida").
Firefox no admite el campo "key" ni un service worker: usa background.scripts y
necesita un ID propio, el mismo que se registra para el host nativo
(register_host.bat lo pone en com.geas.host.firefox.json).
"""
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "extension"
DIST = ROOT / "dist"

FIREFOX_ID = "{88b57c40-5350-4c01-861e-08f0a563420b}"
FIREFOX_MIN_VERSION = "128.0"  # ESR con scripting.executeScript(func) y MV3 completos


def firefox_manifest(manifest):
    manifest = dict(manifest)
    manifest.pop("key", None)
    if len(manifest["name"]) > 45:  # Firefox no admite más: el lema pasa a la descripción
        name, _, tagline = manifest["name"].partition(" — ")
        manifest["name"] = name
        manifest["description"] = f"{tagline}. {manifest['description']}" if tagline else manifest["description"]
    manifest["background"] = {"scripts": ["background.js"], "type": "module"}
    manifest["browser_specific_settings"] = {
        "gecko": {
            "id": FIREFOX_ID,
            "strict_min_version": FIREFOX_MIN_VERSION,
            # Firefox pide declarar qué datos salen de la extensión: van a Geas, en este mismo equipo
            "data_collection_permissions": {"required": ["none"]},
        }
    }
    return manifest


def build(target, transform):
    out = DIST / target
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(SOURCE, out)
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    manifest = transform(manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")

    archive = DIST / f"geas-{target}-{manifest['version']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(out).as_posix())
    print(f"{out}\n{archive}")


TARGETS = {"firefox": firefox_manifest}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        sys.exit(f"Uso: python build_extension.py {{{'|'.join(TARGETS)}}}")
    build(sys.argv[1], TARGETS[sys.argv[1]])

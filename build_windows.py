#!/usr/bin/env python3
"""
Arma Geas para Windows:

    python build_windows.py

  1. dist/Geas/        Geas.exe, geas-host.exe y sus bibliotecas (PyInstaller, geas.spec)
  2. dist/Geas-Setup-<versión>.exe   el instalador (Inno Setup 6, installer/geas.iss), si está instalado

El instalador registra el host nativo para Chrome, Edge y Firefox con los
manifiestos que se generan aquí.
"""
import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
sys.path.insert(0, str(ROOT))
from build_extension import FIREFOX_ID  # noqa: E402
from version import __version__  # noqa: E402

# Extensiones de Chrome/Edge que pueden hablar con Geas: la cargada sin empaquetar (ID fijo por la
# clave "key" de extension/manifest.json); al publicarla en la tienda se agrega aquí su ID.
CHROME_EXTENSION_IDS = ["jbiallikbligfngadffjbakjkiniiigk"]

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040A04B0', [
      StringStruct('CompanyName', 'Geas'),
      StringStruct('FileDescription', 'Geas Download Manager'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('ProductName', 'Geas Download Manager'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x040A, 1200])])
  ]
)
"""


def write_version_info():
    numbers = tuple(int(part) for part in __version__.split(".")) + (0,) * (4 - len(__version__.split(".")))
    BUILD.mkdir(exist_ok=True)
    (BUILD / "version_info.txt").write_text(VERSION_INFO.format(numbers=numbers, version=__version__),
                                            encoding="utf-8")


def write_host_manifests(folder):
    """Manifiestos del host nativo: la ruta es relativa a ellos (geas-host.exe en la misma carpeta)."""
    base = {"name": "com.geas.host", "description": "Geas Native Messaging Host",
            "path": "geas-host.exe", "type": "stdio"}
    chrome = {**base, "allowed_origins": [f"chrome-extension://{i}/" for i in CHROME_EXTENSION_IDS]}
    firefox = {**base, "allowed_extensions": [FIREFOX_ID]}
    (folder / "com.geas.host.json").write_text(json.dumps(chrome, indent=2), encoding="utf-8")
    (folder / "com.geas.host.firefox.json").write_text(json.dumps(firefox, indent=2), encoding="utf-8")


def find_iscc():
    candidates = [shutil.which("ISCC")]
    for base in (Path(r"C:\Program Files (x86)"), Path(r"C:\Program Files"),
                 Path.home() / "AppData" / "Local" / "Programs"):
        candidates.append(base / "Inno Setup 6" / "ISCC.exe")
    return next((str(c) for c in candidates if c and Path(c).exists()), None)


def duplicate_definitions():
    """
    Funciones o métodos definidos dos veces en el mismo archivo o clase: el segundo tapa al primero
    sin avisar (en la 1.0.2, un _run_ydl nuevo tapó al del análisis y no se encontraba ningún video).
    """
    found = []
    for path in sorted(ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scopes = [("", tree.body)] + [(f"{node.name}.", node.body) for node in ast.walk(tree)
                                      if isinstance(node, ast.ClassDef)]
        for prefix, body in scopes:
            seen = {}
            for node in body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if {getattr(d, "attr", getattr(d, "id", "")) for d in node.decorator_list} & {"setter", "deleter"}:
                    continue  # propiedades: repetir el nombre es lo normal
                if node.name in seen:
                    found.append(f"{path.name}: {prefix}{node.name} (líneas {seen[node.name]} y {node.lineno})")
                seen[node.name] = node.lineno
    return found


def main():
    duplicates = duplicate_definitions()
    if duplicates:
        sys.exit("No se arma Geas: hay funciones definidas dos veces\n  " + "\n  ".join(duplicates))
    write_version_info()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "geas.spec"],
                   cwd=ROOT, check=True)
    app_dir = DIST / "Geas"
    write_host_manifests(app_dir)
    shutil.copytree(ROOT / "licenses", app_dir / "licenses", dirs_exist_ok=True)
    # La extensión va con el programa: el asistente de bienvenida enseña a cargarla desde aquí
    shutil.copytree(ROOT / "extension", app_dir / "extension", dirs_exist_ok=True)
    print(f"\nPrograma listo en {app_dir}")

    iscc = find_iscc()
    if not iscc:
        print("No se encontró Inno Setup 6 (ISCC.exe): falta solo el instalador. "
              "Instálalo con:  winget install --id JRSoftware.InnoSetup -e")
        return
    subprocess.run([iscc, f"/DAppVersion={__version__}", str(ROOT / "installer" / "geas.iss")], check=True)
    print(f"Instalador listo: {DIST / f'Geas-Setup-{__version__}.exe'}")


if __name__ == "__main__":
    main()

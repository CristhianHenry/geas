# geas.spec - Empaquetado con PyInstaller (lo usa build_windows.py)
# Dos programas en la misma carpeta, con las bibliotecas compartidas en _internal:
#   Geas.exe       la aplicación (sin consola)
#   geas-host.exe  el host de Native Messaging que abren Chrome, Edge y Firefox (consola: habla por stdin/stdout)
# Carpeta y no un solo .exe: arranca más rápido y las bibliotecas de Qt quedan como
# archivos separados, como pide su licencia LGPL.
import os

from PyInstaller.depend import bindepend

DATAS = [
    ("style.qss", "."),
    ("style_dark.qss", "."),
    ("branding/*.svg", "branding"),
    ("branding/*.png", "branding"),
    ("branding/*.ico", "branding"),
]
EXCLUDES = ["tkinter", "PyQt5", "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtBluetooth"]

app = Analysis(["main.py"], datas=DATAS, excludes=EXCLUDES, noarchive=False)
host = Analysis(["native_messaging_host.py"], excludes=EXCLUDES + ["PySide6", "yt_dlp"], noarchive=False)


# --- Qt sin lo que Geas no usa (de ~600 MB a la mitad) ---------------------------------------
def _qt_path(dest):
    """'PySide6/plugins/x.dll' -> 'plugins/x.dll'; None si no es de PySide6."""
    dest = dest.replace("\\", "/")
    return dest[len("PySide6/"):] if dest.startswith("PySide6/") else None


def _unused_file(rel):
    if rel.startswith(("qml/", "plugins/qmltooling/")):
        return True  # módulos de QML: la interfaz es de widgets
    if rel.startswith("resources/") and (".debug." in rel or "devtools" in rel):
        return True  # versiones de depuración y herramientas de desarrollador del navegador
    if rel.startswith("translations/"):
        name = rel.rsplit("/", 1)[-1]
        if rel.startswith("translations/qtwebengine_locales/"):
            return name not in ("en-US.pak", "es.pak", "es-419.pak")
        return not name.endswith(("_es.qm", "_en.qm"))
    return False


def _is_root_dll(rel):
    return "/" not in rel and rel.lower().endswith(".dll")


def _needed_qt_dlls(entries):
    """
    DLLs de la carpeta de PySide6 que usan sus módulos de Python, sus plugins y
    QtWebEngineProcess.exe, siguiendo las dependencias de cada una.
    """
    root_dlls, pending = {}, []
    for dest, src, _ in entries:
        rel = _qt_path(dest)
        if rel is None or _unused_file(rel):
            continue
        if _is_root_dll(rel):
            root_dlls[rel.lower()] = src
        elif rel.lower().endswith((".pyd", ".exe", ".dll")):
            pending.append(src)
    needed = set()
    while pending:
        for imported in bindepend.get_imports(pending.pop()):
            name = os.path.basename(imported[0] if isinstance(imported, tuple) else imported).lower()
            if name in root_dlls and name not in needed:
                needed.add(name)
                pending.append(root_dlls[name])
    return needed


def _keep(entry, needed):
    rel = _qt_path(entry[0])
    return rel is None or not (_unused_file(rel) or (_is_root_dll(rel) and rel.lower() not in needed))


_needed = _needed_qt_dlls(app.binaries + app.datas)
app.binaries = [e for e in app.binaries if _keep(e, _needed)]
app.datas = [e for e in app.datas if _keep(e, _needed)]
# ---------------------------------------------------------------------------------------------

app_exe = EXE(
    PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="Geas", console=False,
    icon="branding/geas.ico", version="build/version_info.txt",
)
host_exe = EXE(
    PYZ(host.pure), host.scripts, [], exclude_binaries=True, name="geas-host", console=True,
    icon="branding/geas.ico", version="build/version_info.txt",
)
COLLECT(app_exe, app.binaries, app.datas, host_exe, host.binaries, host.datas, name="Geas")

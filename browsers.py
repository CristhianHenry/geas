# browsers.py - Qué navegadores hay en el equipo y cuál es el predeterminado
"""
Windows registra cada navegador instalado en Clients\\StartMenuInternet (con su
ejecutable) y guarda el predeterminado en UserChoice de https. Con eso el
asistente de Primeros pasos muestra los pasos del navegador que usa la persona.
"""
import os
import sys
from dataclasses import dataclass

STORE_URLS = {
    # Página de Geas en cada tienda: cuando exista, instalar la extensión es un clic.
    # Brave, Opera y Vivaldi instalan desde la Chrome Web Store.
    "chrome": "",
    "edge": "",
    "firefox": "",
}


@dataclass
class Browser:
    key: str              # chrome, edge, brave, opera, vivaldi, firefox, chromium
    name: str
    exe: str
    extensions_page: str  # se abre pasándola al ejecutable (no la abre el navegador predeterminado)
    developer_switch: str  # dónde está el «Modo de desarrollador»
    load_button: str       # cómo se llama el botón para cargar una carpeta
    default: bool = False

    @property
    def chromium(self):
        return self.key != "firefox"

    @property
    def store_url(self):
        return STORE_URLS.get("chrome" if self.key in ("brave", "opera", "vivaldi", "chromium") else self.key, "")


# (clave, nombre, ejecutables, página de extensiones, interruptor, botón)
_KNOWN = [
    ("chrome", "Google Chrome", ("chrome.exe",), "chrome://extensions/", "arriba a la derecha",
     "Cargar descomprimida"),
    ("edge", "Microsoft Edge", ("msedge.exe",), "edge://extensions/", "en el panel de la izquierda",
     "Cargar desempaquetada"),
    ("brave", "Brave", ("brave.exe",), "brave://extensions/", "arriba a la derecha", "Cargar descomprimida"),
    ("opera", "Opera", ("opera.exe", "launcher.exe"), "opera://extensions", "arriba a la derecha",
     "Cargar descomprimida"),
    ("vivaldi", "Vivaldi", ("vivaldi.exe",), "vivaldi://extensions/", "arriba a la derecha",
     "Cargar descomprimida"),
    ("chromium", "Chromium", ("chromium.exe",), "chrome://extensions/", "arriba a la derecha",
     "Cargar descomprimida"),
    ("firefox", "Firefox", ("firefox.exe",), "about:addons", "", ""),
]
_ORDER = [k[0] for k in _KNOWN]


def _identify(exe):
    """Navegador conocido por su ejecutable (Opera y Opera GX se abren con launcher.exe)."""
    base = os.path.basename(exe).lower()
    for key, name, exes, page, switch, button in _KNOWN:
        if base in exes and (base != "launcher.exe" or "opera" in exe.lower()):
            return Browser(key, name, exe, page, switch, button)
    return None


def _command_exe(command):
    """'"C:\\...\\chrome.exe" --single-argument %1' -> 'C:\\...\\chrome.exe'"""
    command = (command or "").strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    lower = command.lower()
    end = lower.find(".exe")
    return command[:end + 4] if end >= 0 else command.split(" ", 1)[0]


def _registered_exes():
    """Ejecutables de los navegadores registrados en Windows (StartMenuInternet y App Paths)."""
    import winreg
    found = []
    for root, base in ((winreg.HKEY_CURRENT_USER, r"SOFTWARE\Clients\StartMenuInternet"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet")):
        try:
            with winreg.OpenKey(root, base) as clients:
                for index in range(winreg.QueryInfoKey(clients)[0]):
                    name = winreg.EnumKey(clients, index)
                    try:
                        with winreg.OpenKey(clients, name + r"\shell\open\command") as key:
                            found.append(_command_exe(winreg.QueryValue(key, None)))
                    except OSError:
                        continue
        except OSError:
            continue
    for key, name, exes, *_ in _KNOWN:
        for exe in exes:
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe) as k:
                        found.append(winreg.QueryValue(k, None).strip('"'))
                except OSError:
                    continue
    return found


def default_exe():
    """Ejecutable del navegador predeterminado (el que abre los enlaces https), o ''."""
    if sys.platform != "win32":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\Shell\Associations"
                                                      r"\UrlAssociations\https\UserChoice") as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as key:
            return _command_exe(winreg.QueryValue(key, None))
    except OSError:
        return ""


def installed():
    """Navegadores conocidos que están en el equipo: el predeterminado primero, luego Chrome, Edge…"""
    if sys.platform != "win32":
        return []
    browsers = {}
    for exe in _registered_exes():
        browser = _identify(exe)
        if browser and browser.key not in browsers and os.path.isfile(exe):
            browsers[browser.key] = browser
    default = _identify(default_exe())
    if default and default.key in browsers:
        browsers[default.key].default = True
    return sorted(browsers.values(), key=lambda b: (not b.default, _ORDER.index(b.key)))

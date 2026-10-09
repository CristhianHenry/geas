# power_actions.py - Qué hacer cuando terminan todas las descargas (como "Al terminar" de IDM)
import ctypes
import subprocess
import sys

NOTHING, QUIT, SLEEP, SHUTDOWN = "nada", "cerrar", "suspender", "apagar"

# (acción, texto del menú, texto de la cuenta regresiva)
ACTIONS = [
    (NOTHING, "No hacer nada", ""),
    (QUIT, "Cerrar Geas", "Geas se cerrará"),
    (SLEEP, "Suspender el equipo", "El equipo se suspenderá"),
    (SHUTDOWN, "Apagar el equipo", "El equipo se apagará"),
]
LABELS = {action: label for action, label, _ in ACTIONS}
COUNTDOWN_TEXT = {action: text for action, _, text in ACTIONS}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def sleep_computer():
    """Suspende el equipo (no lo hiberna, aunque la hibernación esté activada)."""
    if sys.platform == "win32":
        # SetSuspendState(hibernar, forzar, sin eventos de activación)
        ctypes.windll.powrprof.SetSuspendState(False, False, False)
    else:
        subprocess.run(["systemctl", "suspend"], check=False)


def shutdown_computer():
    """
    Apaga el equipo. Windows avisa y espera 15 s: en ese tiempo se puede
    cancelar con "shutdown /a" y Geas alcanza a cerrarse guardando todo.
    """
    if sys.platform == "win32":
        subprocess.run(["shutdown", "/s", "/t", "15", "/c", "Geas terminó todas las descargas"],
                       check=False, creationflags=_NO_WINDOW)
    else:
        subprocess.run(["systemctl", "poweroff"], check=False)

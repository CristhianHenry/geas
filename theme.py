# theme.py - Tema claro (style.qss) y oscuro (la misma hoja con colores oscuros)
"""
El tema oscuro no tiene hoja propia: se toma style.qss y cada color se cambia
por su par de DARK_COLORS, así los dos temas nunca quedan distintos en diseño.
Lo que Qt dibuja por su cuenta (barras de desplazamiento, listas desplegables,
mensajes) toma los colores de la paleta, y la barra de título de Windows sigue
al esquema de colores de la aplicación.
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

import paths

LIGHT, DARK, SYSTEM = "claro", "oscuro", "sistema"
CHOICES = [(LIGHT, "Claro"), (DARK, "Oscuro"), (SYSTEM, "Igual que Windows")]

# Color del tema claro -> el mismo papel en el tema oscuro (al estilo del modo oscuro de Windows 11)
DARK_COLORS = {
    "#1b1b1b": "#e6e6e6",  # texto
    "#000000": "#ffffff",  # texto sobre la selección
    "#333333": "#d0d0d0", "#444444": "#bdbdbd", "#555555": "#b5b5b5", "#666666": "#a8a8a8",  # textos tenues
    "#9a9a9a": "#777777",  # deshabilitado
    "#f0f0f0": "#202020",  # fondo de ventanas
    "#f6f6f6": "#2b2b2b",  # menú y barra de estado
    "#ffffff": "#272727",  # listas, campos y pestañas
    "#f7f7f7": "#2f2f2f",  # campo de solo lectura
    "#f7f9fc": "#2c2f33",  # filas alternas
    "#fbfcfe": "#242424",  # árbol de categorías
    "#ececec": "#303030", "#e3e3e3": "#333333", "#e1e1e1": "#333333",  # pestañas, divisor y botones
    "#fdfdfd": "#2d2d2d", "#e8edf3": "#262a2f",  # degradado de la barra de herramientas
    "#dcdcdc": "#3a3a3a", "#e0e0e0": "#3c3c3c", "#d5d5d5": "#3d3d3d", "#d0d0d0": "#3d3d3d",  # bordes
    "#cfcfcf": "#3d3d3d", "#c9c9c9": "#3f3f3f", "#c9d2dc": "#3c434b", "#bcbcbc": "#4a4a4a",
    "#b9b9b9": "#4d4d4d", "#adadad": "#555555",
    "#cce8ff": "#1f4e79", "#99d1ff": "#2f6aa3",  # selección y su borde
    "#e5f3ff": "#2a3b4c", "#e5f1fb": "#3a4652", "#cce4f7": "#2c4a66",  # al pasar y al presionar
    "#0078d7": "#3794e6", "#005fb0": "#2a7ccc", "#1a88e0": "#4aa0ec", "#005499": "#5aaaf0",  # acento
    "#9cc6ea": "#2d4a66",  # botón principal deshabilitado
    "#6db3f2": "#4a90d9", "#2f7fd3": "#2566b0",  # progreso
    "#b5dafc": "#3b6ea5", "#66adf2": "#2f6bb0", "#8a95a1": "#6a737d",  # barra de la lista y tramos
    "#1f4e8c": "#7fb6f0",  # títulos
    "#a15c00": "#f0a040",  # aviso
    "#c42b1c": "#ff6b5b",  # error
}

_dark = False
_native_style = None  # estilo de Windows con el que arrancó Qt (el tema claro lo usa)


def is_dark():
    return _dark


def color(light_hex):
    """Un color pensado para el tema claro, convertido si el tema activo es el oscuro."""
    return QColor(DARK_COLORS.get(light_hex.lower(), light_hex) if _dark else light_hex)


def system_is_dark():
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def stylesheet(dark):
    with open(paths.resource("style.qss"), "r", encoding="utf-8") as f:
        qss = f.read()
    if dark:
        qss = re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: DARK_COLORS.get(m.group(0).lower(), m.group(0)), qss)
    return qss


def _dark_palette():
    palette = QPalette()
    for role, value in ((QPalette.Window, "#202020"), (QPalette.WindowText, "#e6e6e6"), (QPalette.Base, "#272727"),
                        (QPalette.AlternateBase, "#2c2f33"), (QPalette.Text, "#e6e6e6"), (QPalette.Button, "#333333"),
                        (QPalette.ButtonText, "#e6e6e6"), (QPalette.ToolTipBase, "#2b2b2b"),
                        (QPalette.ToolTipText, "#e6e6e6"), (QPalette.Highlight, "#1f4e79"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#8a8a8a"),
                        (QPalette.Link, "#7fb6f0"), (QPalette.BrightText, "#ff6b5b"), (QPalette.Light, "#3a3a3a"),
                        (QPalette.Midlight, "#333333"), (QPalette.Mid, "#2a2a2a"), (QPalette.Dark, "#1a1a1a"),
                        (QPalette.Shadow, "#000000")):
        palette.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#777777"))
    return palette


def apply(app, choice):
    """Aplica el tema elegido (claro, oscuro o el de Windows) a toda la aplicación."""
    global _dark, _native_style
    if _native_style is None:
        _native_style = app.style().name()
    hints = QGuiApplication.styleHints()
    # La barra de título de Windows sigue al esquema de la aplicación; "sistema" lo deja en manos de Windows
    hints.setColorScheme({LIGHT: Qt.ColorScheme.Light, DARK: Qt.ColorScheme.Dark}.get(choice, Qt.ColorScheme.Unknown))
    _dark = choice == DARK or (choice == SYSTEM and system_is_dark())
    # Fusion respeta la paleta oscura en todos los controles; el estilo nativo, no siempre
    app.setStyle("Fusion" if _dark else _native_style)
    if _dark:
        palette = _dark_palette()
    else:
        palette = app.style().standardPalette()
        # Selección azul clara (como el Explorador) también donde la hoja no llega, p. ej. el árbol
        palette.setColor(QPalette.Highlight, QColor("#cce8ff"))
        palette.setColor(QPalette.HighlightedText, QColor("#000000"))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet(_dark))  # en toda la aplicación: también en las ventanas sin padre

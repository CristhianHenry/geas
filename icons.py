# icons.py - Iconos de la interfaz (SVG dibujados en código; el de la app, desde branding/)
import os

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

import paths

_BLUE_GRADIENT = ('<linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
                  '<stop offset="0" stop-color="#4aa3f5"/><stop offset="1" stop-color="#1c64c2"/></linearGradient>')
_GLOBE = ('<defs><radialGradient id="g" cx="0.35" cy="0.3" r="0.8"><stop offset="0" stop-color="#7cc4ff"/>'
          '<stop offset="1" stop-color="#1f6fd1"/></radialGradient></defs>'
          '<circle cx="{c}" cy="{c}" r="{r}" fill="url(#g)" stroke="#16509a" stroke-width="1"/>'
          '<ellipse cx="{c}" cy="{c}" rx="{rx}" ry="{r}" fill="none" stroke="#ffffff" stroke-opacity="0.75" stroke-width="1.2"/>'
          '<path d="M{l} {c} H{rr} M{l2} {t} H{r2} M{l2} {b} H{r2}" stroke="#ffffff" stroke-opacity="0.75" '
          'stroke-width="1.2" fill="none"/>')
_TRASH = ('<defs><linearGradient id="t" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#9aa6b2"/>'
          '<stop offset="1" stop-color="#6b7785"/></linearGradient></defs>'
          '<rect x="5" y="6" width="19" height="3.5" rx="1.2" fill="#5d6874"/>'
          '<rect x="11" y="3" width="7" height="3.5" rx="1" fill="#5d6874"/>'
          '<path d="M7 10.5 H22 L20.6 28 Q20.5 29 19.5 29 H9.5 Q8.5 29 8.4 28 Z" fill="url(#t)"/>'
          '<path d="M11.5 13.5 V25.5 M14.5 13.5 V25.5 M17.5 13.5 V25.5" stroke="#ffffff" stroke-opacity="0.8" '
          'stroke-width="1.6" stroke-linecap="round"/>')
_CHECK_BADGE = ('<circle cx="24" cy="24" r="7" fill="#2fa84f" stroke="#1d7a37" stroke-width="1"/>'
                '<path d="M20.5 24 L23 26.5 L27.5 21.5" stroke="#fff" stroke-width="2.4" fill="none" '
                'stroke-linecap="round" stroke-linejoin="round"/>')
_PAGE = ('<path d="M7 3 H20 L26 9 V29 H7 Z" fill="#ffffff" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>'
         '<path d="M20 3 V9 H26" fill="#e3e8ee" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
_FOLDER = ('<defs><linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd86b"/>'
           '<stop offset="1" stop-color="#f0b429"/></linearGradient></defs>'
           '<path d="M3 8 Q3 6 5 6 H12 L15 9 H27 Q29 9 29 11 V25 Q29 27 27 27 H5 Q3 27 3 25 Z" fill="url(#f)" '
           'stroke="#c48a10" stroke-width="1"/><path d="M3 13 H29" stroke="#c48a10" stroke-opacity="0.5"/>')

_SVG = {
    "add": _GLOBE.format(c=14, r=11.5, rx=5, l=2.5, rr=25.5, l2=4.5, r2=23.5, t=8, b=20)
           + '<circle cx="24" cy="24" r="7" fill="#2fa84f" stroke="#1d7a37" stroke-width="1"/>'
             '<path d="M24 20 V28 M20 24 H28" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/>',
    "browser": _GLOBE.format(c=16, r=13, rx=5.5, l=3, rr=29, l2=5, r2=27, t=9, b=23),
    "resume": '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5fd17a"/>'
              '<stop offset="1" stop-color="#23943f"/></linearGradient></defs>'
              '<circle cx="16" cy="16" r="13" fill="url(#g)" stroke="#1b7a33" stroke-width="1"/>'
              '<path d="M12.5 9.5 L23 16 L12.5 22.5 Z" fill="#fff"/>',
    "pause": '<defs><linearGradient id="p" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffc35a"/>'
             '<stop offset="1" stop-color="#e8890c"/></linearGradient></defs>'
             '<circle cx="16" cy="16" r="13" fill="url(#p)" stroke="#b86a05" stroke-width="1"/>'
             '<rect x="11" y="9.5" width="3.6" height="13" rx="1" fill="#fff"/>'
             '<rect x="17.4" y="9.5" width="3.6" height="13" rx="1" fill="#fff"/>',
    "pause_all": '<defs><linearGradient id="p" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffc35a"/>'
                 '<stop offset="1" stop-color="#e8890c"/></linearGradient></defs>'
                 '<circle cx="11" cy="11" r="9" fill="url(#p)" stroke="#b86a05" stroke-width="1" opacity="0.8"/>'
                 '<circle cx="20" cy="20" r="10" fill="url(#p)" stroke="#b86a05" stroke-width="1"/>'
                 '<rect x="16" y="15" width="3" height="10" rx="1" fill="#fff"/>'
                 '<rect x="21" y="15" width="3" height="10" rx="1" fill="#fff"/>',
    "delete": _TRASH,
    "delete_done": _TRASH + _CHECK_BADGE,
    "options": '<g transform="translate(16 16)" fill="#6f7b88">'
               + "".join(f'<rect x="-3" y="-14.5" width="6" height="7" rx="1.5" transform="rotate({a})"/>'
                         for a in range(0, 360, 45))
               + '<circle r="10" fill="#7f8b98"/><circle r="10" fill="none" stroke="#5d6874" stroke-width="1"/>'
                 '<circle r="4.2" fill="#f4f6f8"/></g>',
    "scheduler": '<circle cx="16" cy="16" r="12.5" fill="#ffffff" stroke="#1f6fd1" stroke-width="3"/>'
                 '<path d="M16 8.5 V16 L21.5 19" stroke="#1b1b1b" stroke-width="2.4" fill="none" '
                 'stroke-linecap="round" stroke-linejoin="round"/><circle cx="16" cy="16" r="1.6" fill="#d0281b"/>',
    "smart": '<circle cx="13" cy="13" r="8.5" fill="#e6f2ff" stroke="#1f6fd1" stroke-width="3"/>'
             '<path d="M19.5 19.5 L27.5 27.5" stroke="#5d6874" stroke-width="4.5" stroke-linecap="round"/>',
    "log": _PAGE.format(stroke="#6b7785")
           + '<path d="M11 14 H22 M11 18 H22 M11 22 H18" stroke="#1f6fd1" stroke-width="1.8" stroke-linecap="round"/>',
    "folder": _FOLDER,
    "open": _PAGE.format(stroke="#6b7785") + '<path d="M12.5 13 L21 18 L12.5 23 Z" fill="#2fa84f"/>',
    "copy": '<rect x="4" y="4" width="16" height="20" rx="1.5" fill="#ffffff" stroke="#6b7785" stroke-width="1.5"/>'
            '<rect x="12" y="9" width="16" height="20" rx="1.5" fill="#ffffff" stroke="#1f6fd1" stroke-width="1.5"/>'
            '<path d="M16 15 H24 M16 19 H24 M16 23 H21" stroke="#1f6fd1" stroke-width="1.6" stroke-linecap="round"/>',
    "redownload": '<path d="M25 11 A10.5 10.5 0 1 0 26.5 18" fill="none" stroke="#1f6fd1" stroke-width="3" '
                  'stroke-linecap="round"/><path d="M26.5 4.5 V11.5 H19.5" fill="none" stroke="#1f6fd1" '
                  'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
    "progress": f'<defs>{_BLUE_GRADIENT}</defs><rect x="2" y="11" width="28" height="10" rx="2" fill="#ffffff" '
                'stroke="#6b7785"/><rect x="3.5" y="12.5" width="15" height="7" rx="1" fill="url(#g)"/>',
    # Categorías
    "all": _FOLDER + '<path d="M16 13 V22 M12 18.5 L16 22.5 L20 18.5" stroke="#1f6fd1" stroke-width="2.4" '
                     'fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "video": '<rect x="3" y="6" width="26" height="20" rx="2.5" fill="#3d4a5c"/>'
             '<rect x="8" y="9" width="16" height="14" rx="1" fill="#7aa7e8"/>'
             '<path d="M14 12.5 L20 16 L14 19.5 Z" fill="#fff"/><g fill="#ffffff">'
             + "".join(f'<rect x="{x}" y="{y}" width="2.4" height="2.4" rx="0.4"/>'
                       for x in (4.3, 25.3) for y in (8, 13, 18, 22.5))
             + '</g>',
    "music": '<path d="M12 23 V7 L26 4 V20" fill="none" stroke="#e8710a" stroke-width="2.6" stroke-linejoin="round"/>'
             '<ellipse cx="9" cy="23" rx="4.2" ry="3.4" fill="#e8710a"/>'
             '<ellipse cx="23" cy="20" rx="4.2" ry="3.4" fill="#e8710a"/>',
    "archive": '<rect x="4" y="5" width="24" height="23" rx="2" fill="#e8b04c" stroke="#a8761b"/>'
               '<rect x="4" y="5" width="24" height="6" rx="2" fill="#d1952d"/>'
               '<path d="M16 5 V28" stroke="#6b4a0e" stroke-width="2" stroke-dasharray="2 2"/>',
    "document": _PAGE.format(stroke="#1f6fd1")
                + '<path d="M11 14 H22 M11 18 H22 M11 22 H18" stroke="#1f6fd1" stroke-width="1.8" stroke-linecap="round"/>',
    "program": '<rect x="3" y="5" width="26" height="22" rx="2" fill="#ffffff" stroke="#1f6fd1" stroke-width="1.5"/>'
               '<rect x="3" y="5" width="26" height="6" rx="2" fill="#1f6fd1"/>'
               '<rect x="7" y="15" width="8" height="8" fill="#7aa7e8"/>'
               '<path d="M18 16 H25 M18 19 H25 M18 22 H23" stroke="#6b7785" stroke-width="1.6"/>',
    "other": _PAGE.format(stroke="#8a95a1"),
    "unfinished": '<circle cx="16" cy="16" r="13" fill="#f59e0b" stroke="#b45309" stroke-width="1"/>'
                  '<path d="M16 8 V20 M11 15.5 L16 20.5 L21 15.5" stroke="#fff" stroke-width="3" fill="none" '
                  'stroke-linecap="round" stroke-linejoin="round"/><rect x="10" y="23" width="12" height="2.4" '
                  'rx="1.2" fill="#fff"/>',
    "finished": '<circle cx="16" cy="16" r="13" fill="#2fa84f" stroke="#1d7a37" stroke-width="1"/>'
                '<path d="M10 16.5 L14.5 21 L22.5 11.5" stroke="#fff" stroke-width="3.2" fill="none" '
                'stroke-linecap="round" stroke-linejoin="round"/>',
}

_cache = {}
_BRANDING = paths.resource("branding")


def _render(renderer, sizes, result):
    for size in sizes:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)


def icon(name: str) -> QIcon:
    """Icono por nombre (requiere que exista la QApplication)."""
    if name not in _cache:
        result = QIcon()
        if name == "app":
            # Collar de Geas: hasta 32 px se usa el dibujo simplificado, sin cadenas
            _render(QSvgRenderer(os.path.join(_BRANDING, "geas-small.svg")), (16, 20, 24, 32), result)
            _render(QSvgRenderer(os.path.join(_BRANDING, "geas.svg")), (48, 64, 128, 256), result)
        else:
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">{_SVG[name]}</svg>'
            _render(QSvgRenderer(QByteArray(svg.encode("utf-8"))), (16, 20, 24, 32, 48), result)
        _cache[name] = result
    return _cache[name]


def names():
    return list(_SVG)

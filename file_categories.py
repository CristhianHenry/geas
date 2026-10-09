# file_categories.py - Categorías de la lista de descargas (como en IDM)
import os

# (nombre visible, icono, extensiones)
CATEGORIES = [
    ("Comprimidos", "archive", {"zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst", "iso", "img", "cab", "arj", "lzh", "ace"}),
    ("Documentos", "document", {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "epub", "odt", "ods", "rtf"}),
    ("Música", "music", {"mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac", "wma", "aif"}),
    ("Programas", "program", {"exe", "msi", "msix", "msu", "apk", "dmg", "pkg", "deb", "rpm", "jar", "bat", "appx"}),
    ("Video", "video", {"mp4", "m4v", "mkv", "webm", "mov", "avi", "flv", "wmv", "3gp", "ogv", "mpg", "mpeg", "ts", "rm", "rmvb"}),
]


def category_of(path):
    """(nombre de la categoría, icono) según la extensión; ('General', 'other') si no encaja."""
    ext = os.path.splitext(path or "")[1].lower().lstrip(".")
    for name, icon_name, extensions in CATEGORIES:
        if ext in extensions:
            return name, icon_name
    return "General", "other"

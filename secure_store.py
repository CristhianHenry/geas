# secure_store.py - Cookies y cabeceras guardadas para reanudar, cifradas para el usuario de Windows
"""
Para reanudar una descarga después de cerrar Geas hacen falta las cookies y
cabeceras del navegador con las que empezó. No se guardan en texto plano en el
registro de descargas: en Windows se cifran con DPAPI, así que solo el mismo
usuario de Windows en el mismo equipo puede leerlas (si alguien copia la
carpeta de Geas, se lleva datos ilegibles). En otros sistemas no se guardan.
"""
import base64
import ctypes
import json
import sys

# Conserva el nombre anterior de la app: cambiarlo dejaría ilegibles las sesiones ya guardadas
_ENTROPY = b"AppIDM reanudar v1"

if sys.platform == "win32":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for _function in (_crypt32.CryptProtectData, _crypt32.CryptUnprotectData):
        _function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                              ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        _function.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _UI_FORBIDDEN = 0x01  # nunca mostrar diálogos de Windows

    def _blob(data: bytes):
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _dpapi(function, data: bytes) -> bytes:
        data_in, _keep_in = _blob(data)
        entropy, _keep_entropy = _blob(_ENTROPY)
        data_out = _Blob()
        if not function(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
                        _UI_FORBIDDEN, ctypes.byref(data_out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(data_out.pbData, data_out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(data_out.pbData, ctypes.c_void_p))


def protect(value):
    """Cifra un valor JSON y lo devuelve como texto; None si no hay nada que guardar o no se puede."""
    if sys.platform != "win32" or not value:
        return None
    try:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        return base64.b64encode(_dpapi(_crypt32.CryptProtectData, raw)).decode("ascii")
    except Exception:
        return None


def unprotect(text):
    """Descifra lo guardado con protect(); None si no se puede (otro usuario o equipo, dato dañado)."""
    if sys.platform != "win32" or not isinstance(text, str) or not text:
        return None
    try:
        return json.loads(_dpapi(_crypt32.CryptUnprotectData, base64.b64decode(text)).decode("utf-8"))
    except Exception:
        return None

#setting.py
import json
import os

import paths

DEFAULT_CONFIG = {
    "default_download_folder": os.path.expanduser("~/Downloads"),
    "default_threads": 4,
    "category_folders": False,      # cada tipo de archivo en su subcarpeta (Video, Música...), como IDM
    "max_simultaneous_downloads": 3,  # las demás esperan en la cola
    "download_speed_limit_kbps": 0,  # 0 = sin límite
    "auto_retry_count": 3,
    "proxy_mode": "sistema",        # "sistema", "ninguno" o "manual"
    "proxy_url": "",                # cifrado (puede llevar usuario y contraseña)
    "site_logins": [],              # [{"site", "user", "password" (cifrada)}]
    "auto_start_downloads": True,
    "minimize_to_tray": False,
    "theme": "claro",               # "claro", "oscuro" o "sistema" (igual que Windows)
    "show_notifications": True,
    "show_progress_dialog": True,   # ventana de progreso al iniciar una descarga (como IDM)
    "clipboard_monitor": False,     # detectar enlaces copiados
    "convert_to_h264": True,        # convertir AV1/VP9/HEVC a H.264 al terminar (requiere ffmpeg)
    "subtitle_language": "",        # idioma de subtítulos elegido la última vez (se preselecciona)
    "check_ytdlp_updates": True,    # comprobar una vez al día si hay una versión nueva de yt-dlp
    "check_app_updates": True,      # Geas instalada: buscar una versión nueva una vez al día
    "remote_enabled": False,        # control desde el celular (escucha en la red solo si está activo)
    "remote_port": 8767,
    "remote_token": "",             # código secreto del celular, cifrado
    "app_last_check": "",           # fecha de la última búsqueda
    "ytdlp_last_check": "",         # fecha de la última comprobación
    "ytdlp_latest_seen": ""         # última versión publicada que se vio
}

BOOLEAN_KEYS = {key for key, value in DEFAULT_CONFIG.items() if isinstance(value, bool)}

CONFIG_PATH = paths.data("config.json")


class AppSettings:
    def __init__(self):
        if not os.path.exists(CONFIG_PATH):
            self._config = DEFAULT_CONFIG.copy()
            self._save()
        else:
            try:
                with open(CONFIG_PATH, "r", encoding='utf-8') as f:
                    self._config = json.load(f)
                
                # Asegurar claves nuevas
                for key, val in DEFAULT_CONFIG.items():
                    self._config.setdefault(key, val)
                
                # Validar ruta de descarga
                download_folder = self._config.get("default_download_folder")
                if download_folder:
                    # Expandir ~ al directorio home del usuario
                    expanded_folder = os.path.expanduser(download_folder)
                    if not os.path.exists(expanded_folder):
                        # Si la ruta no existe (ej: usuario diferente), usar default
                        print(f"Ruta configurada no válida: {download_folder}. Usando default.")
                        self._config["default_download_folder"] = DEFAULT_CONFIG["default_download_folder"]
                    else:
                        # Actualizar con ruta expandida
                        self._config["default_download_folder"] = expanded_folder
                
                self._save()
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"Error cargando configuración: {e}")
                # Si hay error, usar configuración por defecto
                self._config = DEFAULT_CONFIG.copy()
                self._save()

    def _save(self):
        """Guardar configuración en archivo JSON"""
        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error guardando configuración: {e}")

    def get(self, key, default=None):
        """
        Obtener configuración con valor por defecto opcional
        
        Args:
            key (str): Clave de configuración
            default: Valor por defecto si la clave no existe
            
        Returns:
            Valor de la configuración o default
        """
        if default is None:
            # Si no se proporciona default, usar el de DEFAULT_CONFIG
            return self._config.get(key, DEFAULT_CONFIG.get(key))
        else:
            # Si se proporciona default, usarlo
            return self._config.get(key, default)

    def set(self, key, value):
        """
        Establecer valor de configuración con validación

        Args:
            key (str): Clave de configuración
            value: Valor a establecer

        Raises:
            ValueError: Si el valor no es válido para la clave dada
        """
        # Validar el valor antes de guardarlo
        validated_value = self._validate_config_value(key, value)
        self._config[key] = validated_value
        self._save()

    def _validate_config_value(self, key, value):
        """
        Valida un valor de configuración según su clave

        Args:
            key (str): Clave de configuración
            value: Valor a validar

        Returns:
            Valor validado (puede ser convertido o corregido)

        Raises:
            ValueError: Si el valor no es válido
        """
        if key == "default_download_folder":
            # Expandir ~ y validar que sea una ruta válida
            expanded = os.path.expanduser(str(value))
            if not os.path.isabs(expanded) and not value.startswith("~"):
                raise ValueError(f"La ruta debe ser absoluta: {value}")
            # Intentar crear el directorio si no existe
            try:
                os.makedirs(expanded, exist_ok=True)
            except Exception as e:
                raise ValueError(f"No se puede crear el directorio: {e}")
            return expanded

        elif key == "default_threads":
            threads = int(value)
            if threads < 1 or threads > 16:
                raise ValueError("Los hilos deben estar entre 1 y 16")
            return threads

        elif key == "remote_port":
            port = int(value)
            if not 1024 <= port <= 65535:
                raise ValueError("El puerto debe estar entre 1024 y 65535")
            return port

        elif key == "theme":
            if value not in ("claro", "oscuro", "sistema"):
                raise ValueError(f"Tema desconocido: {value}")
            return value

        elif key == "proxy_mode":
            if value not in ("sistema", "ninguno", "manual"):
                raise ValueError(f"Modo de proxy desconocido: {value}")
            return value

        elif key == "max_simultaneous_downloads":
            count = int(value)
            if count < 1 or count > 10:
                raise ValueError("Las descargas a la vez deben estar entre 1 y 10")
            return count

        elif key == "download_speed_limit_kbps":
            speed = int(value)
            if speed < 0:
                raise ValueError("El límite de velocidad no puede ser negativo")
            return speed

        elif key == "auto_retry_count":
            retry = int(value)
            if retry < 0 or retry > 10:
                raise ValueError("Los reintentos deben estar entre 0 y 10")
            return retry

        elif key in BOOLEAN_KEYS:
            if not isinstance(value, bool):
                # Intentar convertir a booleano
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes', 'si', 'sí')
                return bool(value)
            return value

        else:
            # Clave desconocida, permitir cualquier valor
            return value

    def get_all(self):
        """Obtener toda la configuración"""
        return self._config.copy()

    def reset_to_default(self):
        """Resetear configuración a valores por defecto"""
        self._config = DEFAULT_CONFIG.copy()
        self._save()

    def has_key(self, key):
        """Verificar si existe una clave de configuración"""
        return key in self._config
    

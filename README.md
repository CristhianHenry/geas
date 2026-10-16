# Geas Download Manager — Grab Everything At Speed

![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.7+-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

**Geas** es un gestor de descargas multiplataforma inspirado en Internet Download Manager (IDM), con una interfaz gráfica moderna construida con PySide6 (Qt 6) y una extensión de Chrome integrada para detectar y descargar archivos multimedia automáticamente.

## Características

### Aplicación de Escritorio
- **Descarga Multi-Hilo**: Descarga archivos hasta 16x más rápido usando múltiples conexiones simultáneas
- **Segmentación dinámica (como IDM)**: Cuando una conexión termina su parte, divide la parte a la que más le falta y se queda con la mitad; ninguna conexión queda ociosa
- **Control de Velocidad**: Limita la velocidad de descarga para no saturar tu conexión
- **Pausa/Reanudación**: Pausa y reanuda descargas en cualquier momento
- **Reanudar después de cerrar Geas**: Las descargas a medias quedan como "Interrumpida (x %)" y continúan desde donde quedaron (archivos y videos). El archivo se descarga como `.part` y se renombra al terminar; si cambió en el servidor, se descarga de nuevo
- **Reintentos Automáticos**: Reintenta automáticamente descargas fallidas, siguiendo desde donde se cortaron
- **Actualizar yt-dlp**: Avisa en la barra de estado cuando hay una versión nueva y la instala desde Ayuda → Actualizar yt-dlp
- **Interfaz al estilo IDM**: Tema claro, barra de herramientas con iconos grandes, categorías (Video, Música, Comprimidos, Documentos, Programas, Sin terminar, Terminadas) y una sola lista que conserva las descargas terminadas
- **Ventana de progreso como IDM**: Velocidad, tiempo restante, conexiones con su barra segmentada, límite de velocidad en vivo y aviso de "Descarga completada" con Abrir / Abrir carpeta
- **Descargar más tarde**: Deja descargas en espera y las inicia con "Reanudar"
- **Conversión a H.264**: Los videos en AV1, VP9 o HEVC se convierten al terminar para que los abra el Reproductor de Windows (se puede desactivar en Opciones)
- **Navegador Integrado**: Navega la web directamente desde la aplicación
- **Programador de Descargas**: Programa descargas para ejecutarse en un momento específico
- **Cola de descargas**: Como mucho N descargas a la vez (Opciones → Conexión); las demás esperan "En cola" y empiezan solas
- **Al terminar las descargas**: Cerrar Geas, suspender o apagar el equipo, con 30 segundos para cancelar (menú Descargas)
- **Actualizar dirección de descarga**: Si el enlace venció, se pega uno nuevo (o se vuelve a hacer clic en el navegador) y la descarga sigue desde donde quedó
- **Proxy y usuarios por sitio**: Proxy de Windows, sin proxy o uno propio (HTTP o SOCKS), y usuario y contraseña por servidor, guardados cifrados
- **Carpeta por tipo**: Opcionalmente, cada tipo de archivo en su subcarpeta (Video, Música, Comprimidos, Documentos, Programas)
- **Subtítulos**: Elige el idioma en la ventana de calidad; se guardan junto al video o, con ffmpeg, incrustados
- **Listas de reproducción y canales**: Descarga una lista o un canal completo con una sola elección de calidad, numerados y en su carpeta
- **Tema oscuro**: Claro, oscuro o igual que Windows (Opciones → General)
- **Control desde el celular**: Tareas → Control desde el celular muestra un código QR; desde el navegador del celular se añaden enlaces y se ven, pausan o cancelan las descargas. Apagado por defecto y protegido con un código secreto

### Extensión de Chrome / Edge / Firefox
- **Captura de Descargas**: Las descargas del navegador (ZIP, EXE, PDF, MP4, ISO...) pasan a Geas, como en IDM. Si Geas no responde, la descarga vuelve al navegador
- **Sesión del Navegador**: Cada descarga lleva las cookies, el Referer y el User-Agent del navegador, así funcionan los sitios con inicio de sesión o enlaces protegidos
- **Detección Automática de Medios**: Detecta videos (MP4, WebM), listas HLS (M3U8) y DASH (MPD) en cualquier página; el icono muestra cuántos encontró
- **Botón sobre los Videos**: "Descargar video" sobre cada reproductor, incluidos los que están dentro de iframes o shadow DOM
- **Menú Contextual**: Descarga cualquier enlace, imagen, audio o video con clic derecho, o el video de la página completa
- **Descargar todos los enlaces**: De la página o de lo seleccionado; Geas los lista con casillas y filtros, y los pone en la cola
- **Filtrado Inteligente**: Ignora fragmentos (.ts, .m4s), peticiones parciales y archivos pequeños
- **Popup**: Muestra si Geas está conectada, los medios detectados en la pestaña y permite activar/desactivar la captura

### Descarga de Videos
- **Integración con yt-dlp**: Descarga videos de YouTube, Twitch y cientos de sitios más
- **Selección de Calidad**: Elige la calidad y formato del video antes de descargar
- **Extracción de Información**: Obtiene título, descripción y thumbnails automáticamente

## Requisitos del Sistema

- **Sistema Operativo**: Windows 10/11, Linux, macOS
- **Python**: 3.7 o superior
- **Navegador**: Google Chrome o Chromium (para la extensión)
- **FFmpeg**: Recomendado. Sin él, los videos HLS no se reempaquetan (se traban al adelantar) ni se convierten a H.264. En Windows: `winget install --id Gyan.FFmpeg.Essentials -e`

## Instalación

### Con el instalador (Windows 10/11)

Ejecuta `Geas-Setup-<versión>.exe`. Se instala para tu usuario (no pide permisos de administrador) en `%LOCALAPPDATA%\Programs\Geas`, registra la conexión con Chrome, Edge y Firefox, y guarda tus datos (opciones, historial, registro) en `%APPDATA%\Geas`. No hace falta instalar Python. Windows puede mostrar "Windows protegió tu PC" porque el instalador no está firmado: "Más información" → "Ejecutar de todas formas".

La primera vez se abre **Primeros pasos**: explica cómo cargar la extensión (viene en la carpeta `extension` de la instalación) y ofrece instalar ffmpeg.

Geas instalada actualiza yt-dlp desde **Ayuda → Actualizar yt-dlp** y, si `UPDATE_REPO` de `version.py` apunta al repositorio de GitHub, busca versiones nuevas de sí misma una vez al día.

**Generar el instalador:**

```bash
pip install pyinstaller
winget install --id JRSoftware.InnoSetup -e
python build_windows.py
```

Deja el programa en `dist/Geas/` y el instalador en `dist/Geas-Setup-<versión>.exe` (la versión sale de `version.py`).

### Desde el código fuente

### 1. Clonar el Repositorio

```bash
git clone https://github.com/CristhianHenry/geas.git
cd geas
```

### 2. Crear Entorno Virtual (Recomendado)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 3. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 4. Instalar FFmpeg (Opcional)

**Windows:**
- Descarga desde [ffmpeg.org](https://ffmpeg.org/download.html)
- Agrega FFmpeg a tu PATH

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

## Configuración de la Extensión de Chrome

### 1. Instalar la Extensión en Modo Desarrollador

1. Abre Chrome y navega a `chrome://extensions/` (en Edge: `edge://extensions/`)
2. Activa el "Modo de desarrollador" (esquina superior derecha)
3. Haz clic en "Cargar extensión sin empaquetar"
4. Selecciona la carpeta `extension` dentro del proyecto

La extensión siempre tiene el mismo ID (`jbiallikbligfngadffjbakjkiniiigk`), sin importar desde qué carpeta se cargue.

**Firefox (128 o posterior):** Firefox necesita su propia versión de la extensión:

```bash
python build_extension.py firefox
```

Luego abre `about:debugging#/runtime/this-firefox`, pulsa "Cargar complemento temporario…" y elige `dist/firefox/manifest.json`. Así queda cargada hasta cerrar Firefox; para dejarla instalada, Mozilla tiene que firmar `dist/geas-firefox-<versión>.zip` (se sube a addons.mozilla.org, aunque no se publique allí).

### 2. Configurar Native Messaging

**Windows:**
```bash
# Ejecutar desde el directorio del proyecto (registra Chrome, Edge y Firefox)
register_host.bat
```

No pide datos: usa el ID fijo de la extensión y el Python de `venv` (o el del PATH si no existe). Reinicia el navegador después de registrarlo.

**Linux/macOS:**
```bash
# Crear el directorio de manifiestos si no existe
mkdir -p ~/.config/google-chrome/NativeMessagingHosts/

# Copiar el manifiesto
cp com.geas.host.json ~/.config/google-chrome/NativeMessagingHosts/

# Actualizar la ruta en el archivo JSON a la ubicación actual
# Edita ~/.config/google-chrome/NativeMessagingHosts/com.geas.host.json
# y actualiza el campo "path" con la ruta absoluta a native_messaging_host.py
```

## Uso

### Iniciar la Aplicación

```bash
python main.py
```

### Agregar una Descarga

1. **Desde la Aplicación:**
   - Pulsa "Añadir URL" (Ctrl+N) o copia un enlace y pulsa Ctrl+V
   - Si es una página con video, se abre el diálogo de calidad; si es un archivo, el de información del archivo
   - Elige dónde guardar y pulsa "Iniciar descarga" (o "Descargar más tarde")
   - En la lista: doble clic abre el archivo terminado o la ventana de progreso; clic derecho muestra Abrir carpeta, Descargar de nuevo, Copiar URL y Eliminar

2. **Desde la Extensión de Chrome:**
   - Descarga un archivo como siempre: Geas lo captura y lo descarga con varias conexiones
   - En un video, pulsa "Descargar video" o el botón del popup "Descargar video de esta página"
   - Haz clic derecho en cualquier enlace → "Descargar con Geas"
   - Para videos, se abrirá un diálogo de selección de calidad. Geas prueba primero la página con yt-dlp y, si el sitio no está soportado, los streams (M3U8/MPD/MP4) que detectó la extensión
   - Si Geas está cerrada, se abre sola al llegar la primera descarga

3. **Desde el Navegador Integrado:**
   - Pulsa "Navegador" en la barra de herramientas
   - Navega a cualquier sitio web
   - Al detectar un video, Geas pregunta si quieres descargarlo

### Programar una Descarga

1. Pulsa "Programador" en la barra de herramientas
2. Ingresa la URL del archivo y dónde guardarlo
3. Selecciona la fecha y hora de inicio y pulsa "Programar"
4. La descarga se iniciará automáticamente en el momento programado y aparecerá en la lista

## Configuración

Todo se ajusta desde **Opciones** (barra de herramientas). Se guarda en `config.json`:

```json
{
  "default_download_folder": "~/Downloads",
  "default_threads": 4,
  "download_speed_limit_kbps": 0,
  "auto_retry_count": 3,
  "auto_start_downloads": true,
  "minimize_to_tray": false,
  "show_notifications": true,
  "show_progress_dialog": true,
  "clipboard_monitor": false,
  "convert_to_h264": true,
  "check_ytdlp_updates": true
}
```

### Opciones de Configuración

- **default_download_folder**: Carpeta por defecto para descargas
- **default_threads**: Número de hilos/conexiones simultáneas (1-16)
- **download_speed_limit_kbps**: Límite de velocidad en KB/s (0 = sin límite)
- **auto_retry_count**: Número de reintentos automáticos (0-10)
- **auto_start_downloads**: Iniciar sin preguntar las descargas capturadas del navegador (si es `false`, se muestra el diálogo para elegir nombre y carpeta)
- **minimize_to_tray**: Al cerrar la ventana, seguir en la bandeja del sistema
- **show_notifications**: Aviso en la bandeja al terminar una descarga
- **show_progress_dialog**: Abrir la ventana de progreso al iniciar cada descarga
- **clipboard_monitor**: Detectar enlaces de descarga copiados al portapapeles
- **convert_to_h264**: Convertir a H.264 los videos AV1/VP9/HEVC al terminar (requiere FFmpeg)
- **check_ytdlp_updates**: Comprobar una vez al día si hay una versión nueva de yt-dlp (`ytdlp_last_check` y `ytdlp_latest_seen` los usa Geas para eso)

La lista de descargas (incluidas las terminadas) se guarda en `download_history.json`, junto con el avance de las que no terminaron. Las cookies y cabeceras necesarias para reanudarlas se guardan cifradas con DPAPI de Windows (solo tu usuario de Windows puede leerlas) y se borran al terminar la descarga. El tema visual está en `style.qss`; el tema oscuro anterior quedó en `style_dark.qss`.

## Arquitectura del Proyecto

```
geas/
├── main.py                      # Punto de entrada de la aplicación
├── gui.py                       # Ventana principal (menús, barra, categorías y lista)
├── download_dialog.py           # Ventana de progreso / descarga completada
├── video_quality_dialog.py      # Elección de calidad de video
├── options_dialog.py            # Opciones
├── scheduler_dialog.py          # Programador
├── simple_dialogs.py            # Añadir URL, eliminar y registro
├── icons.py                     # Iconos (SVG en código)
├── video_converter.py           # Conversión a H.264 con FFmpeg
├── manager.py                   # Gestor de descargas (reanudar, cerrar guardando el avance)
├── enhanced_downloader.py       # Motor de descarga multi-hilo con segmentación dinámica
├── secure_store.py              # Cifrado DPAPI de las cookies guardadas para reanudar
├── ytdlp_updater.py             # Versión y actualización de yt-dlp
├── ytdlp_dialog.py              # Ventana "Actualizar yt-dlp"
├── media_handler.py             # Manejador de videos (yt-dlp)
├── browser_context.py           # Cookies/cabeceras del navegador para cada descarga
├── file_info_dialog.py          # Diálogo de descarga para archivos del navegador
├── api_server.py                # Servidor API Flask
├── settings.py                  # Gestión de configuración
├── history.py                   # Historial de descargas
├── scheduler.py                 # Programador de descargas
├── native_messaging_host.py     # Host de mensajería nativa
├── extension/                   # Extensión de Chrome
│   ├── manifest.json
│   ├── background.js
│   ├── content.js
│   ├── content.css
│   ├── settings.js
│   ├── popup.html
│   └── popup.js
├── icons/                       # Iconos de la aplicación
├── config.json                  # Archivo de configuración
├── requirements.txt             # Dependencias de Python
└── README.md                    # Este archivo
```

## API REST

El servidor API corre en `http://localhost:5000` y proporciona los siguientes endpoints:

Solo acepta peticiones locales del host de Native Messaging o de la extensión: una página web no puede ordenar descargas.

### POST /download
Entrega una descarga a la interfaz de Geas.

**Parámetros:**
```json
{
  "url": "https://example.com/file.zip",
  "kind": "file",
  "filename": "archivo.zip",
  "page_url": "https://example.com/descargas",
  "referer": "https://example.com/descargas",
  "user_agent": "Mozilla/5.0 ...",
  "cookies": [{"name": "session", "value": "...", "domain": ".example.com", "path": "/"}],
  "streams": [{"url": "https://cdn.example.com/master.m3u8", "kind": "hls", "headers": {"Referer": "https://example.com/"}}]
}
```

`kind`: `file` (descarga directa), `video` (buscar el video de la página), `stream` (analizar un M3U8/MPD con yt-dlp) o `auto` (Geas consulta la URL y decide).

### GET /check
Verifica que el servidor está corriendo.

**Respuesta:**
```json
{
  "status": "running",
  "version": "1.1"
}
```

### GET /status
Obtiene el estado del gestor de descargas.

**Respuesta:**
```json
{
  "status": "ok",
  "active_downloads": 2,
  "total_tasks": 5
}
```

## Solución de Problemas

### La extensión no se comunica con la aplicación

1. Abre el popup de la extensión: indica si el host nativo responde y si Geas está abierta
2. Verifica que ejecutaste `register_host.bat` (Windows) y reinicia el navegador
3. Si la extensión tiene otro ID (por ejemplo, la cargaste antes sin la clave fija), quítala de `chrome://extensions/` y vuelve a cargarla, o ejecuta `register_host.bat <ID>`
4. Revisa `native_host.log` en la carpeta del proyecto

### Las descargas fallan constantemente

1. Verifica tu conexión a internet
2. Aumenta el valor de `auto_retry_count` en la configuración
3. Reduce el número de hilos en configuración
4. Algunos servidores bloquean descargas multi-hilo; prueba con 1 hilo

### La aplicación no detecta videos

1. Asegúrate de tener `yt-dlp` instalado: `pip install yt-dlp`
2. Actualiza yt-dlp a la última versión: **Ayuda → Actualizar yt-dlp** (o `pip install -U yt-dlp`) y reinicia Geas
3. Algunos sitios requieren autenticación o no son soportados

### Error de permisos al descargar

1. Verifica que tienes permisos de escritura en la carpeta de descargas
2. Cambia la carpeta de descargas en la configuración
3. Ejecuta la aplicación con permisos de administrador (no recomendado)

## Desarrollo

### Ejecutar en Modo Debug

```bash
# El host nativo registra cada solicitud en native_host.log (sin cookies)

# Ejecutar con logging
python main.py 2>&1 | tee app.log
```

### Ejecutar Tests

```bash
python test_habetar.py
```

## Contribuir

Las contribuciones son bienvenidas! Por favor:

1. Haz fork del proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está licenciado bajo la Licencia MIT. Ver el archivo `LICENSE` para más detalles.

## Reconocimientos

- [PySide6](https://doc.qt.io/qtforpython-6/) - Framework GUI (Qt for Python, LGPL)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Descarga de videos
- [Flask](https://flask.palletsprojects.com/) - Framework web
- [requests](https://requests.readthedocs.io/) - Cliente HTTP

## Soporte

Si encuentras algún problema o tienes sugerencias, por favor abre un [issue](https://github.com/CristhianHenry/geas/issues).

---

Desarrollado con ❤️ por Henry

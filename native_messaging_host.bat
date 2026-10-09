@echo off
:: Lanzador del host de Native Messaging (lo ejecuta el navegador).
:: Usa el Python del entorno virtual del proyecto si existe; si no, el del PATH.
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0native_messaging_host.py" %*
) else (
    python "%~dp0native_messaging_host.py" %*
)

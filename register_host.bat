@echo off
setlocal

:: Registra el host de Native Messaging de Geas en Chrome, Edge y Firefox.
:: Uso: register_host.bat [ID_ADICIONAL_DE_EXTENSION]

set "HOST_NAME=com.geas.host"
set "HOST_DIR=%~dp0"
set "MANIFEST_PATH=%HOST_DIR%com.geas.host.json"
set "FIREFOX_MANIFEST_PATH=%HOST_DIR%com.geas.host.firefox.json"
:: ID fijo de la extension: lo determina la clave "key" de extension\manifest.json
set "EXTENSION_ID=jbiallikbligfngadffjbakjkiniiigk"
:: ID de la version para Firefox (FIREFOX_ID en build_extension.py)
set "FIREFOX_ID={88b57c40-5350-4c01-861e-08f0a563420b}"
set "EXTRA_ID=%~1"

echo ==========================================
echo      Geas Native Host Registration
echo ==========================================
echo.
echo Extension ID: %EXTENSION_ID%
if defined EXTRA_ID echo ID adicional: %EXTRA_ID%
echo Host Path: %HOST_DIR%
echo.

if exist "%HOST_DIR%venv\Scripts\python.exe" (
    echo Python: %HOST_DIR%venv\Scripts\python.exe
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ADVERTENCIA: no se encontro Python. Crea el entorno virtual "venv" o instala Python.
    ) else (
        echo Python: el del PATH
    )
)
echo.

:: Create the manifest file
(
echo {
echo   "name": "%HOST_NAME%",
echo   "description": "Geas Native Messaging Host",
echo   "path": "native_messaging_host.bat",
echo   "type": "stdio",
echo   "allowed_origins": [
if defined EXTRA_ID echo     "chrome-extension://%EXTRA_ID%/",
echo     "chrome-extension://%EXTENSION_ID%/"
echo   ]
echo }
) > "%MANIFEST_PATH%"

:: Add to Registry (HKCU) - Chrome
REG ADD "HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%MANIFEST_PATH%" /f

:: Add to Registry (HKCU) - Edge
REG ADD "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%MANIFEST_PATH%" /f

:: Firefox: su propio manifiesto, con el ID de la extension en vez del origen
(
echo {
echo   "name": "%HOST_NAME%",
echo   "description": "Geas Native Messaging Host",
echo   "path": "native_messaging_host.bat",
echo   "type": "stdio",
echo   "allowed_extensions": [ "%FIREFOX_ID%" ]
echo }
) > "%FIREFOX_MANIFEST_PATH%"
REG ADD "HKCU\Software\Mozilla\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%FIREFOX_MANIFEST_PATH%" /f

:: Quita el registro con el nombre anterior de la app (AppIDM)
REG DELETE "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.henry.appidm" /f >nul 2>&1
REG DELETE "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.henry.appidm" /f >nul 2>&1

echo.
echo ==========================================
echo Registration Complete!
echo Please restart Chrome/Edge/Firefox for changes to take effect.
echo ==========================================
pause

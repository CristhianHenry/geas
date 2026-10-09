@echo off
REM Script de instalación de Geas para Windows
REM Ejecuta el instalador de Python

echo ========================================
echo Geas - Instalador para Windows
echo ========================================
echo.

REM Verificar que Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado o no esta en el PATH
    echo Por favor instala Python 3.7+ desde https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM Ejecutar el instalador de Python
echo Ejecutando instalador...
echo.
python install.py

if errorlevel 1 (
    echo.
    echo La instalacion se completo con errores.
    echo Revisa los mensajes anteriores para mas detalles.
) else (
    echo.
    echo Instalacion completada exitosamente!
)

echo.
pause

#!/bin/bash
# Script de instalación de Geas para Linux/macOS

echo "========================================"
echo "Geas - Instalador para Linux/macOS"
echo "========================================"
echo ""

# Verificar que Python está instalado
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 no está instalado"
    echo "Por favor instala Python 3.7+ desde tu gestor de paquetes"
    exit 1
fi

# Mostrar versión de Python
echo "Python version:"
python3 --version
echo ""

# Ejecutar el instalador de Python
echo "Ejecutando instalador..."
echo ""
python3 install.py

if [ $? -eq 0 ]; then
    echo ""
    echo "Instalación completada exitosamente!"
else
    echo ""
    echo "La instalación se completó con errores."
    echo "Revisa los mensajes anteriores para más detalles."
fi

echo ""

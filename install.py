#!/usr/bin/env python3
"""
Script de instalación automatizada para Geas
Configura el entorno, instala dependencias y registra la extensión de Chrome.
"""

import os
import sys
import subprocess
import platform
import json
from pathlib import Path

# ID de la extensión de Chrome (fijado por la clave "key" de extension/manifest.json)
EXTENSION_ID = "jbiallikbligfngadffjbakjkiniiigk"
FIREFOX_ID = "{88b57c40-5350-4c01-861e-08f0a563420b}"  # el de build_extension.py


class GeasInstaller:
    def __init__(self):
        self.project_dir = Path(__file__).parent.absolute()
        self.platform = platform.system()
        self.errors = []
        self.warnings = []

    def print_header(self, text):
        """Imprime un encabezado formateado"""
        print("\n" + "=" * 60)
        print(f"  {text}")
        print("=" * 60 + "\n")

    def print_step(self, step_num, total, description):
        """Imprime el paso actual"""
        print(f"[{step_num}/{total}] {description}...")

    def print_success(self, message):
        """Imprime un mensaje de éxito"""
        print(f"✓ {message}")

    def print_error(self, message):
        """Imprime un mensaje de error"""
        print(f"✗ ERROR: {message}")
        self.errors.append(message)

    def print_warning(self, message):
        """Imprime una advertencia"""
        print(f"⚠ ADVERTENCIA: {message}")
        self.warnings.append(message)

    def check_python_version(self):
        """Verifica la versión de Python"""
        self.print_step(1, 6, "Verificando versión de Python")

        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 7):
            self.print_error(f"Python 3.7+ requerido, encontrado {version.major}.{version.minor}")
            return False

        self.print_success(f"Python {version.major}.{version.minor}.{version.micro} detectado")
        return True

    def install_dependencies(self):
        """Instala las dependencias de Python"""
        self.print_step(2, 6, "Instalando dependencias de Python")

        requirements_file = self.project_dir / "requirements.txt"
        if not requirements_file.exists():
            self.print_error("No se encontró requirements.txt")
            return False

        try:
            # Actualizar pip primero
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                check=True,
                capture_output=True
            )

            # Instalar dependencias
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
                check=True,
                capture_output=True
            )

            self.print_success("Dependencias instaladas correctamente")
            return True
        except subprocess.CalledProcessError as e:
            self.print_error(f"Error al instalar dependencias: {e}")
            return False

    def check_ffmpeg(self):
        """Verifica si FFmpeg está instalado"""
        self.print_step(3, 6, "Verificando FFmpeg (opcional)")

        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                check=True,
                capture_output=True
            )
            self.print_success("FFmpeg instalado y disponible")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.print_warning("FFmpeg no encontrado (requerido para procesar videos)")
            self.print_warning("Instala FFmpeg desde https://ffmpeg.org/download.html")
            return False

    def setup_native_messaging(self):
        """Configura Native Messaging para Chrome"""
        self.print_step(4, 6, "Configurando Native Messaging para Chrome")

        manifest_file = self.project_dir / "com.geas.host.json"
        if not manifest_file.exists():
            self.print_error("No se encontró com.geas.host.json")
            return False

        try:
            # Leer y actualizar el manifiesto
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            # El ID de la extensión es fijo (clave "key" en extension/manifest.json)
            origin = f"chrome-extension://{EXTENSION_ID}/"
            origins = manifest.setdefault("allowed_origins", [])
            if origin not in origins:
                origins.insert(0, origin)

            # Actualizar la ruta según el sistema operativo
            if self.platform == "Windows":
                host_script = self.project_dir / "native_messaging_host.bat"
                manifest["path"] = str(host_script)

                # Crear el archivo .bat si no existe
                if not host_script.exists():
                    bat_content = f'@echo off\r\n"{sys.executable}" "{self.project_dir / "native_messaging_host.py"}" %*\r\n'
                    with open(host_script, 'w', newline='') as f:
                        f.write(bat_content)

                # Registrar en el registro de Windows
                self._register_windows_native_host(manifest_file)

            else:  # Linux/macOS
                host_script = self.project_dir / "native_messaging_host.py"
                manifest["path"] = str(host_script)

                # Hacer ejecutable el script
                os.chmod(host_script, 0o755)

                # Crear directorio de manifiestos si no existe
                if self.platform == "Linux":
                    native_dir = Path.home() / ".config/google-chrome/NativeMessagingHosts"
                else:  # macOS
                    native_dir = Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts"

                native_dir.mkdir(parents=True, exist_ok=True)

                # Copiar el manifiesto
                import shutil
                shutil.copy(manifest_file, native_dir / "com.geas.host.json")

            # Guardar el manifiesto actualizado
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
            if self.platform == "Windows":
                self._register_firefox_host(manifest)

            self.print_success("Native Messaging configurado correctamente")
            return True

        except Exception as e:
            self.print_error(f"Error al configurar Native Messaging: {e}")
            return False

    def _register_windows_native_host(self, manifest_file):
        """Registra el host nativo en el registro de Windows"""
        try:
            import winreg

            # Chrome y Edge leen el host desde su propia clave
            key_paths = [
                r"Software\Google\Chrome\NativeMessagingHosts\com.geas.host",
                r"Software\Microsoft\Edge\NativeMessagingHosts\com.geas.host",
            ]

            # Crear las claves en HKEY_CURRENT_USER
            for key_path in key_paths:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_file))

            self.print_success("Host registrado en el registro de Windows (Chrome y Edge)")
        except ImportError:
            self.print_warning("winreg no disponible, registra manualmente ejecutando register_host.bat")
        except Exception as e:
            self.print_warning(f"Error al registrar en Windows: {e}")

    def _register_firefox_host(self, manifest):
        """Firefox: su propio manifiesto, con el ID de la extensión en vez del origen."""
        try:
            import winreg
            firefox = {key: value for key, value in manifest.items() if key != "allowed_origins"}
            firefox["allowed_extensions"] = [FIREFOX_ID]
            firefox_file = self.project_dir / "com.geas.host.firefox.json"
            with open(firefox_file, 'w', encoding='utf-8') as f:
                json.dump(firefox, f, indent=2)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Mozilla\NativeMessagingHosts\com.geas.host") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(firefox_file))
            self.print_success("Host registrado para Firefox")
        except Exception as e:
            self.print_warning(f"No se pudo registrar el host para Firefox: {e}")

    def create_desktop_shortcut(self):
        """Crea un acceso directo en el escritorio (solo Windows)"""
        self.print_step(5, 6, "Creando acceso directo (Windows)")

        if self.platform != "Windows":
            self.print_warning("Acceso directo solo disponible en Windows")
            return True

        try:
            import winshell
            from win32com.client import Dispatch

            desktop = winshell.desktop()
            shortcut_path = os.path.join(desktop, "Geas.lnk")

            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = sys.executable
            shortcut.Arguments = f'"{self.project_dir / "main.py"}"'
            shortcut.WorkingDirectory = str(self.project_dir)
            shortcut.IconLocation = sys.executable
            shortcut.save()

            self.print_success(f"Acceso directo creado en {shortcut_path}")
            return True
        except ImportError:
            self.print_warning("winshell no disponible, instala con: pip install winshell pywin32")
            return True
        except Exception as e:
            self.print_warning(f"Error al crear acceso directo: {e}")
            return True

    def verify_installation(self):
        """Verifica que la instalación fue exitosa"""
        self.print_step(6, 6, "Verificando instalación")

        # Verificar archivos principales
        required_files = [
            "main.py",
            "gui.py",
            "manager.py",
            "api_server.py",
            "config.json",
            "extension/manifest.json"
        ]

        all_present = True
        for file in required_files:
            file_path = self.project_dir / file
            if not file_path.exists():
                self.print_error(f"Archivo faltante: {file}")
                all_present = False

        if all_present:
            self.print_success("Todos los archivos necesarios están presentes")

        return all_present

    def print_summary(self):
        """Imprime un resumen de la instalación"""
        self.print_header("RESUMEN DE INSTALACIÓN")

        if not self.errors:
            print("✓ Instalación completada exitosamente!")
        else:
            print(f"✗ Instalación completada con {len(self.errors)} error(es):")
            for error in self.errors:
                print(f"  - {error}")

        if self.warnings:
            print(f"\n⚠ {len(self.warnings)} advertencia(s):")
            for warning in self.warnings:
                print(f"  - {warning}")

        print("\n" + "-" * 60)
        print("PRÓXIMOS PASOS:")
        print("-" * 60)
        print("1. Instala la extensión de Chrome:")
        print("   - Abre chrome://extensions/")
        print("   - Activa 'Modo de desarrollador'")
        print("   - Haz clic en 'Cargar extensión sin empaquetar'")
        print(f"   - Selecciona: {self.project_dir / 'extension'}")
        print("\n2. Inicia la aplicación:")
        print(f"   python {self.project_dir / 'main.py'}")
        print("\n3. Si instalaste FFmpeg después de este script, reinicia la terminal")
        print("\n4. Lee el README.md para más información")
        print("-" * 60 + "\n")

    def run(self):
        """Ejecuta el proceso de instalación"""
        self.print_header("INSTALADOR DE Geas - Gestor de Descargas")

        print("Este script configurará Geas en tu sistema.")
        print("Se instalarán las dependencias necesarias y se configurará la extensión.")

        # Ejecutar pasos de instalación
        steps = [
            self.check_python_version,
            self.install_dependencies,
            self.check_ffmpeg,
            self.setup_native_messaging,
            self.create_desktop_shortcut,
            self.verify_installation
        ]

        for step in steps:
            if not step():
                if self.errors:
                    print("\n⚠ Se encontraron errores durante la instalación.")
                    continue

        # Mostrar resumen
        self.print_summary()

        return len(self.errors) == 0


if __name__ == "__main__":
    installer = GeasInstaller()
    success = installer.run()
    sys.exit(0 if success else 1)

"""
Punto de entrada único de Discord EDR.

Arranca el panel de escritorio, que a su vez arranca el bot automáticamente
en segundo plano (ver desktop_app/bot_runner.py) si hay un DISCORD_TOKEN
configurado en .env.

Uso normal:
    python run_app.py

Este mismo archivo es el que se empaqueta con PyInstaller para generar un
.exe de un solo doble clic (ver docs/BUILD_EXE.md).
"""
from desktop_app.app import main

if __name__ == "__main__":
    main()
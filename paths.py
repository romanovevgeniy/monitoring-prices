"""Где лежат код и рабочие файлы.

Из исходников (Mac, папка проекта) всё в папке проекта.
В собранной программе (PyInstaller) код лежит внутри приложения, куда писать нельзя, поэтому профиль браузера,
links.xlsx по умолчанию и results/ — в %LOCALAPPDATA%\\Мониторинг цен (Windows)
или ~/Library/Application Support/Мониторинг цен (Mac).
"""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

# Код и ресурсы
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

# Рабочие файлы
if FROZEN and sys.platform == "darwin":
    DATA_DIR = Path.home() / "Library" / "Application Support" / "Мониторинг цен"
elif FROZEN:
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Мониторинг цен"
else:
    DATA_DIR = Path(__file__).parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

# MONITORING_PROFILE_DIR — другой профиль браузера (например, для проверки, пока идёт основной прогон)
PROFILE_DIR = Path(os.environ.get("MONITORING_PROFILE_DIR") or DATA_DIR / ".browser-profile")
RESULTS_DIR = DATA_DIR / "results"

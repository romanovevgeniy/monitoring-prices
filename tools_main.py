"""Единая точка входа скриптов для собранной программы (PyInstaller): `monitoring-tools <скрипт> [аргументы]`.

Mac-приложение (SwiftUI) и Windows-приложение (Qt) вызывают её вместо `python <скрипт>.py`,
когда скрипты встроены в программу.
"""
import runpy
import sys

TOOLS = {"run": "run", "fill_links": "fill_links", "nosimo": "nosimo", "make_links": "make_links_template"}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
        sys.exit(f"Использование: monitoring-tools {{{'|'.join(TOOLS)}}} [аргументы]")
    module = TOOLS[sys.argv[1]]
    sys.argv = [module] + sys.argv[2:]
    runpy.run_module(module, run_name="__main__")

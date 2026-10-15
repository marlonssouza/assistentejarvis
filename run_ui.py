"""Atalho para abrir a interface web do J.A.R.V.I.S.

Uso:
    .\\.venv\\Scripts\\python run_ui.py
"""

from jarvis.server import run

if __name__ == "__main__":
    run(open_browser=True)

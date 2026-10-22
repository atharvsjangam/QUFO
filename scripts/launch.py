"""Double-click launcher: start only QUFO, wait for readiness, open the browser."""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

def ready():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=2) as r:
            return json.load(r).get("app") == "QUFO"
    except Exception:
        return False

def alert(message):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "QUFO — Quick Info", 0x40)
    except Exception:
        print(message)

if not ready():
    runtime = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not runtime.exists():
        alert("QUFO needs its one-time setup. Open SETUP.cmd in the QUFO folder, then try again.")
        sys.exit(1)
    with (DATA / "server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(runtime), str(ROOT / "server.py")], cwd=ROOT,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    for _ in range(60):
        if ready():
            break
        if process.poll() is not None:
            alert("QUFO could not start. Details are in the project's data/server.log file.")
            sys.exit(1)
        time.sleep(1)
    else:
        alert("QUFO is taking longer than expected to start. Details are in data/server.log.")
        sys.exit(1)
webbrowser.open(URL)

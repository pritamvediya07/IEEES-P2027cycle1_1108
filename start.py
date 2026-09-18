#!/usr/bin/env python3
# scripts/start.py
# One-command startup for the NWDAF PALA project.
#
# Usage:  python scripts/start.py
#
# What it does:
#   1. Checks MongoDB is reachable
#   2. Checks Ollama is running with the right model
#   3. Starts the collector in a background thread
#   4. Runs the Streamlit UI (foreground)
#
# Stop with Ctrl-C (collector thread is a daemon and will stop automatically)

import sys
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def check_prereqs() -> bool:
    ok = True

    # MongoDB
    from config.db import ping
    if not ping():
        print("❌  MongoDB not reachable. Is mongod running?")
        print("    sudo systemctl start mongod")
        ok = False
    else:
        print("✅  MongoDB OK")

    # Ollama
    import requests
    from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(OLLAMA_MODEL in m for m in models):
            print(f"❌  Ollama model '{OLLAMA_MODEL}' not found.")
            print(f"    Run:  ollama pull {OLLAMA_MODEL}")
            ok = False
        else:
            print(f"✅  Ollama + {OLLAMA_MODEL} OK")
    except Exception:
        print(f"❌  Ollama not running at {OLLAMA_BASE_URL}")
        print("    Install:  curl -fsSL https://ollama.com/install.sh | sh")
        print(f"    Start:    ollama serve")
        print(f"    Pull:     ollama pull {OLLAMA_MODEL}")
        ok = False

    return ok


def main() -> None:
    print("\n" + "=" * 60)
    print("NWDAF PALA — Startup")
    print("=" * 60)

    if not check_prereqs():
        print("\n⚠️  Fix the issues above and re-run.")
        sys.exit(1)

    # Start collector
    print("\n[1/2] Starting NWDAF data collector...")
    from collector.collector import Collector
    collector = Collector()
    collector.start()
    print("      Collector running (writes to nwdaf_analytics DB every 5s)")

    # Wait for a few samples to accumulate
    print("      Waiting 10s for initial data collection...")
    time.sleep(10)

    # Launch Streamlit
    print("\n[2/2] Launching PALA Streamlit UI...")
    print("      Open http://localhost:8501 in your browser\n")

    try:
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run",
             os.path.join(ROOT, "agent", "streamlit_app.py"),
             "--server.port", "8501",
             "--server.address", "0.0.0.0"],
            check=True,
        )
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        collector.stop()
        print("Collector stopped. Goodbye.")


if __name__ == "__main__":
    main()

"""Run the whole site on this computer, no Docker: http://localhost:8080

    python run_local.py          # just this computer
    python run_local.py --lan    # also reachable from other devices on the network

Starts the backend (SQLite in backend/dev.db, code run by the LOCAL judge), the Next.js
frontend and a small proxy that puts both on one URL. Ctrl+C stops everything.

The local judge runs submitted code with no sandbox, so this is for trying the site out and
for rehearsals on a trusted network, not for a real event: see README for the Docker setup.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PY = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def wait_for(url: str, what: str, timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    sys.exit(f"{what} didn't start; see the messages above")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true", help="listen on the network, not just this computer")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--rebuild", action="store_true", help="rebuild the frontend first")
    args = ap.parse_args()

    if not PY.exists():
        sys.exit(f"No backend virtualenv at {PY.parent.parent}. Set it up first (README: 'Develop locally').")
    npm = shutil.which("npm")
    server_js = FRONTEND / ".next" / "standalone" / "server.js"
    if args.rebuild or not server_js.exists():
        if not npm:
            sys.exit("Node.js/npm is needed to build the frontend")
        if not (FRONTEND / "node_modules").exists():
            subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
        subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)
    # the standalone server needs the static files next to it
    for src, dst in ((".next/static", ".next/standalone/.next/static"), ("public", ".next/standalone/public")):
        shutil.rmtree(FRONTEND / dst, ignore_errors=True)
        shutil.copytree(FRONTEND / src, FRONTEND / dst)

    env = {**os.environ, "JUDGE_BACKEND": "local", "PYTHONUNBUFFERED": "1"}
    procs = [
        subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--port", "8000", "--log-level", "warning"], cwd=BACKEND, env=env),
        subprocess.Popen(["node", str(server_js)], cwd=FRONTEND, env={**env, "PORT": "3000", "HOSTNAME": "127.0.0.1"}),
        subprocess.Popen(
            [str(PY), str(BACKEND / "scripts" / "dev_proxy.py"), "--host", "0.0.0.0" if args.lan else "127.0.0.1", "--port", str(args.port)], cwd=BACKEND
        ),
    ]
    try:
        wait_for("http://127.0.0.1:8000/api/health", "The backend")
        wait_for(f"http://127.0.0.1:{args.port}/", "The site")
        print(f"\n  CompSoc is running:  http://localhost:{args.port}")
        if args.lan:
            print(f"  On other devices:    http://{lan_ip()}:{args.port}")
        print(f"  Admin login:         http://localhost:{args.port}/admin  (first time: admin / changeme)")
        print("  Ctrl+C to stop.\n", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("One of the servers stopped; shutting down.")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()

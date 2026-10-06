import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from scripts.demo import seed


def main():
    """Start the local SQLite demo with one command and stop children on Ctrl+C."""
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    children = []
    stop = False

    def request_stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    commands = [
        [
            "-m",
            "uvicorn",
            "demo_app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
            "--no-access-log",
        ],
        [
            "-m",
            "uvicorn",
            "releaseguard.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-access-log",
        ],
        ["-m", "releaseguard.worker"],
        [
            "-m",
            "streamlit",
            "run",
            "dashboard.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            "8501",
            "--browser.gatherUsageStats",
            "false",
        ],
    ]
    try:
        # Migrate before API/worker startup so they never race to create a fresh schema.
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        for command in commands:
            children.append(subprocess.Popen([sys.executable, *command]))
        with httpx.Client(
            base_url="http://127.0.0.1:8000",
            timeout=2,
            headers={"X-API-Key": os.getenv("API_KEY", "")},
        ) as client:
            for _ in range(60):
                if stop or any(child.poll() is not None for child in children):
                    raise RuntimeError("A service stopped during startup; inspect the output above")
                try:
                    if client.get("/health/ready").is_success:
                        seed(client)
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.5)
            else:
                raise TimeoutError("API did not become ready")
        print(
            "\nReleaseGuard: http://127.0.0.1:8501 | API docs: http://127.0.0.1:8000/docs",
            flush=True,
        )
        while not stop:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A service exited; inspect the output above")
            time.sleep(0.5)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()

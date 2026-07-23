from __future__ import annotations

import multiprocessing as mp
import os
import socket
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path
from threading import Thread


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 200
        except OSError:
            time.sleep(0.1)
    return False


def write_startup_error(message: str) -> None:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MortalSim" / "logs"
    root.mkdir(parents=True, exist_ok=True)
    (root / "launcher.log").write_text(message + "\n", encoding="utf-8")


def main() -> None:
    mp.freeze_support()
    try:
        import uvicorn
        from apps.api.main import app
        from mortal_app.service import require_cuda

        require_cuda()

        port = int(os.environ.get("MORTALSIM_PORT", "0")) or free_port()
        # GUI-mode PyInstaller builds expose no stderr; disable Uvicorn's
        # console formatter so startup does not fail before the API binds.
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False, log_config=None)
        server = uvicorn.Server(config)
        thread = Thread(target=server.run, name="mortalsim-api", daemon=True)
        thread.start()
        if not wait_for_health(port):
            raise RuntimeError(f"MortalSim API failed to start on port {port}")
        webbrowser.open(f"http://127.0.0.1:{port}/")
        try:
            while thread.is_alive():
                thread.join(timeout=0.5)
        except KeyboardInterrupt:
            server.should_exit = True
    except BaseException as exc:
        message = "MortalSim could not start. Check the log under %LOCALAPPDATA%\\MortalSim\\logs.\n" + str(exc)
        write_startup_error(message + "\n" + traceback.format_exc())
        try:
            from tkinter import Tk, messagebox

            root = Tk()
            root.withdraw()
            messagebox.showerror("MortalSim", message)
            root.destroy()
        except BaseException:
            pass
        raise


if __name__ == "__main__":
    main()

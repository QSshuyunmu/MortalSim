"""MortalSim 全套服务守护进程 (Guardian)。

职责：
1. 以 Win32 命名互斥体保证全局单例（防止多份守护进程互相踩踏）。
2. 监督 bot.py：进程缺失或心跳过期（假死）时以完全脱离父进程的方式重新拉起。
3. 监督 MortalSim 仿真后端 (127.0.0.1:50715)：端口无监听且无残留进程时重新拉起。
4. 将自身的启动/重启/异常事件写入 logs/daemon.log，并把 PID 落盘 data/daemon.pid，
   便于脚本精确停止（避免依赖 cmdline 过滤在 PowerShell 5.1 下失效）。

设计约束：本文件保持轻量单一职责，任何业务逻辑不得下沉至此。
"""
from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
PYTHON_EXE = sys.executable
MUTEX_NAME = "Global\\MortalSim_Bot_Daemon_Singleton_Mutex"

LOG_DIR = BOT_DIR / "logs"
DAEMON_LOG = LOG_DIR / "daemon.log"
PID_FILE = BOT_DIR / "data" / "daemon.pid"
HEARTBEAT_FILE = BOT_DIR / "data" / "bot.heartbeat"

HEARTBEAT_TIMEOUT = float(os.environ.get("MORTALSIM_BOT_HEARTBEAT_TIMEOUT", "90"))
CHECK_INTERVAL = float(os.environ.get("MORTALSIM_DAEMON_INTERVAL", "5"))
BOT_START_GRACE = float(os.environ.get("MORTALSIM_BOT_START_GRACE", "45"))

NAPCAT_ENABLED = os.environ.get("MORTALSIM_SUPERVISE_NAPCAT", "1") != "0"
ONEBOT_PORT = int(os.environ.get("MORTALSIM_ONEBOT_PORT", "5701"))
NAPCAT_SCRIPT = BOT_DIR / "scripts" / "start_napcat.ps1"
# QQ 进程活着但 OneBot 端口没起来 = 大概率正在等扫码登录，先宽限这么久再考虑重启
NAPCAT_LOGIN_GRACE = float(os.environ.get("MORTALSIM_NAPCAT_LOGIN_GRACE", "300"))
NAPCAT_CHECK_INTERVAL = float(os.environ.get("MORTALSIM_NAPCAT_INTERVAL", "20"))
NAPCAT_RELAUNCH_COOLDOWN = float(os.environ.get("MORTALSIM_NAPCAT_COOLDOWN", "180"))
NAPCAT_LONG_BACKOFF = float(os.environ.get("MORTALSIM_NAPCAT_LONG_BACKOFF", "900"))
NAPCAT_MAX_QUICK_RETRIES = int(os.environ.get("MORTALSIM_NAPCAT_MAX_RETRIES", "3"))
POWERSHELL_EXE = os.environ.get(
    "MORTALSIM_POWERSHELL",
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
)

BACKEND_ENABLED = os.environ.get("MORTALSIM_SUPERVISE_BACKEND", "1") != "0"
BACKEND_PORT = int(os.environ.get("MORTALSIM_PORT", "50715"))
BACKEND_DIR = Path(os.environ.get("MORTALSIM_DIR", r"D:\tenhoulib\MortalSim"))
BACKEND_DATA_DIR = os.environ.get(
    "MORTALSIM_DATA_DIR", r"D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new10\data"
)

DETACHED_FLAGS = (
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
)

_mutex_handle = None
_bot_spawned_at = 0.0


def log(message: str) -> None:
    """写入 logs/daemon.log（超过 5MB 轮转为 daemon.log.1）。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if DAEMON_LOG.exists() and DAEMON_LOG.stat().st_size > 5 * 1024 * 1024:
            rotated = DAEMON_LOG.with_suffix(".log.1")
            rotated.unlink(missing_ok=True)
            DAEMON_LOG.rename(rotated)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with DAEMON_LOG.open("a", encoding="utf-8", buffering=1) as handle:
            handle.write(f"{stamp} [Daemon] {message}\n")
    except Exception:
        pass
    print(f"[Daemon] {message}", flush=True)


def acquire_win32_mutex(name: str) -> bool:
    global _mutex_handle
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, True, name)
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            if _mutex_handle:
                kernel32.CloseHandle(_mutex_handle)
                _mutex_handle = None
            return False
        return True
    except Exception as exc:
        log(f"mutex check failed: {exc}; continuing")
        return True


def _iter_processes():
    import psutil

    return psutil.process_iter(["pid", "name", "cmdline", "create_time"])


def find_bot_processes() -> list[int]:
    """返回所有属于本项目的 bot.py 进程 PID（排除 daemon.py 与其它项目）。"""
    found: list[tuple[float, int]] = []
    for proc in _iter_processes():
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "MortalSim-Bot" not in cmd or "bot.py" not in cmd or "daemon.py" in cmd:
                continue
            found.append((proc.info.get("create_time") or 0.0, proc.info["pid"]))
        except Exception:
            continue
    found.sort()
    return [pid for _, pid in found]


def heartbeat_age() -> float:
    """返回心跳文件的年龄（秒）；文件不存在时返回无穷大。"""
    try:
        return max(0.0, time.time() - HEARTBEAT_FILE.stat().st_mtime)
    except OSError:
        return float("inf")


def bot_is_healthy() -> bool:
    """进程存在且心跳新鲜才算健康，避免假死进程长期占用单例。"""
    pids = find_bot_processes()
    if not pids:
        return False
    age = heartbeat_age()
    if age > HEARTBEAT_TIMEOUT:
        if time.time() - _bot_spawned_at < BOT_START_GRACE:
            return True  # 刚拉起，允许心跳尚未落盘
        log(f"bot.py heartbeat stale ({age:.0f}s > {HEARTBEAT_TIMEOUT:.0f}s); treating as hung: {pids}")
        for pid in pids:
            kill_pid(pid)
        return False
    return True


def kill_pid(pid: int) -> None:
    try:
        import psutil

        psutil.Process(pid).kill()
        log(f"killed stale process pid={pid}")
    except Exception as exc:
        log(f"failed to kill pid={pid}: {exc}")


def spawn_detached(args: list[str], cwd: Path, env: dict | None = None) -> int:
    """以完全脱离父进程的方式启动子进程（父进程退出/会话关闭不影响子进程）。"""
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        creationflags=DETACHED_FLAGS,
    )
    return proc.pid


def start_bot() -> None:
    global _bot_spawned_at
    script = BOT_DIR / "src" / "bot.py"
    pid = spawn_detached([PYTHON_EXE, "-u", str(script)], BOT_DIR)
    _bot_spawned_at = time.time()
    log(f"bot.py restarted (pid={pid})")


def port_open(port: int) -> bool:
    """本机 TCP 端口是否处于监听状态。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def backend_port_open() -> bool:
    return port_open(BACKEND_PORT)


def napcat_process_alive() -> bool:
    """QQ / NapCat 注入器是否还活着（活着说明是"未登录/等扫码"，而不是"进程崩了"）。"""
    for proc in _iter_processes():
        try:
            name = (proc.info.get("name") or "").lower()
            if name == "napcatwinbootmain.exe":
                return True
            if name == "qq.exe":
                cmd = " ".join(proc.info.get("cmdline") or [])
                if "--type=" not in cmd:  # 只认主进程，忽略 renderer/gpu/utility 子进程
                    return True
        except Exception:
            continue
    return False


def start_napcat() -> None:
    """走唯一入口脚本重启 NapCat（含免扫码登录配置注入）。"""
    if not NAPCAT_SCRIPT.exists():
        log(f"napcat supervisor script missing: {NAPCAT_SCRIPT}")
        return
    args = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(NAPCAT_SCRIPT),
        "-Force",
        "-Wait",
        "-TimeoutSec",
        "75",
    ]
    pid = spawn_detached(args, BOT_DIR)
    log(f"napcat relaunch requested (helper pid={pid}, log={LOG_DIR / 'napcat_supervisor.log'})")


def supervise_napcat(state: dict) -> None:
    """OneBot 端口监督：崩溃即拉起；等扫码期间只告警不打扰。"""
    now = time.time()

    if port_open(ONEBOT_PORT):
        if state.get("down_since"):
            log(f"napcat recovered: OneBot port {ONEBOT_PORT} is listening again")
        state.update(down_since=None, retries=0, last_log=0.0)
        return

    if now - state.get("last_check", 0.0) < NAPCAT_CHECK_INTERVAL:
        return
    state["last_check"] = now

    if not state.get("down_since"):
        state["down_since"] = now
    waited = now - state["down_since"]

    alive = napcat_process_alive()
    grace = NAPCAT_LOGIN_GRACE if alive else 0.0  # 进程都没了就没必要再等
    if waited < grace:
        if now - state.get("last_log", 0.0) >= 120.0:
            state["last_log"] = now
            log(
                f"napcat/QQ process alive but OneBot port {ONEBOT_PORT} is not listening "
                f"({waited:.0f}s) - assuming login/QR in progress, NOT restarting"
            )
        return

    cooldown = NAPCAT_RELAUNCH_COOLDOWN
    if state.get("retries", 0) >= NAPCAT_MAX_QUICK_RETRIES:
        cooldown = NAPCAT_LONG_BACKOFF  # 连续失败后进入长退避，避免无限重启刷屏
    if now - state.get("last_spawn", 0.0) < cooldown:
        return

    state["last_spawn"] = now
    state["retries"] = state.get("retries", 0) + 1
    state["down_since"] = now  # 新一轮尝试重新计时宽限
    reason = "process gone" if not alive else f"port down for {waited:.0f}s with QQ still alive"
    log(f"napcat restart #{state['retries']} ({reason})")
    start_napcat()


def backend_process_alive() -> bool:
    for proc in _iter_processes():
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "run_mortalsim" in cmd:
                return True
        except Exception:
            continue
    return False


def start_backend() -> None:
    env = os.environ.copy()
    env["MORTALSIM_DATA_DIR"] = BACKEND_DATA_DIR
    env["MORTALSIM_PORT"] = str(BACKEND_PORT)
    env["MORTALSIM_NO_BROWSER"] = "1"
    pid = spawn_detached([PYTHON_EXE, "run_mortalsim.py"], BACKEND_DIR, env)
    log(f"MortalSim backend restarted (pid={pid}, port={BACKEND_PORT})")


def write_pid_file() -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as exc:
        log(f"pid file write failed: {exc}")


def main() -> None:
    if not acquire_win32_mutex(MUTEX_NAME):
        log("another daemon instance is already active; exiting (this run does nothing).")
        sys.exit(0)

    write_pid_file()
    duties = ["bot.py"]
    duties.append(f"backend:{BACKEND_PORT}" if BACKEND_ENABLED else "backend:off")
    duties.append(f"napcat:{ONEBOT_PORT}" if NAPCAT_ENABLED else "napcat:off")
    log(f"guardian started (pid={os.getpid()}); supervising " + ", ".join(duties))

    last_backend_check = 0.0
    napcat_state: dict = {}
    while True:
        try:
            if not bot_is_healthy():
                start_bot()
        except Exception as exc:
            log(f"bot supervision error: {exc}")

        if BACKEND_ENABLED:
            now = time.time()
            if now - last_backend_check >= 15.0:
                last_backend_check = now
                try:
                    if not backend_port_open() and not backend_process_alive():
                        start_backend()
                except Exception as exc:
                    log(f"backend supervision error: {exc}")

        if NAPCAT_ENABLED:
            try:
                supervise_napcat(napcat_state)
            except Exception as exc:
                log(f"napcat supervision error: {exc}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()

"""QQ Bot 守护进程：使用 Windows 原生命名互斥体 (Win32 Mutex) 保证全局绝对单例。"""
import sys, time, subprocess, os, ctypes
from pathlib import Path

BOT_DIR = Path(r"D:\tenhoulib\MortalSim-Bot").resolve()
PYTHON_EXE = sys.executable
MUTEX_NAME = "Global\\MortalSim_Bot_Daemon_Singleton_Mutex"

_mutex_handle = None

def acquire_win32_mutex(name: str) -> bool:
    global _mutex_handle
    if os.name != 'nt':
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, True, name)
        last_error = kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            if _mutex_handle:
                kernel32.CloseHandle(_mutex_handle)
                _mutex_handle = None
            return False
        return True
    except Exception as e:
        print(f"[Daemon] Mutex error: {e}", flush=True)
        return True

def is_bot_running() -> bool:
    import psutil
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd_list = p.info.get('cmdline')
            if not cmd_list:
                continue
            cmd_str = " ".join(cmd_list)
            if "bot.py" in cmd_str and "daemon.py" not in cmd_str:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            continue
    return False

def start_bot():
    print("[Daemon] Starting bot.py in background...", flush=True)
    bot_script = BOT_DIR / "src" / "bot.py"
    log_file = BOT_DIR / "logs" / "bot.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    f = open(log_file, "a", encoding="utf-8", buffering=1)
    subprocess.Popen(
        [PYTHON_EXE, "-u", str(bot_script)],
        cwd=str(BOT_DIR),
        stdout=f,
        stderr=f,
    )

def main():
    if not acquire_win32_mutex(MUTEX_NAME):
        print("[Daemon] Another daemon instance is already active. Exiting immediately.", flush=True)
        sys.exit(0)

    print(f"[Daemon] Bot Guardian started (PID {os.getpid()}). Global Win32 Mutex acquired.", flush=True)
    while True:
        try:
            if not is_bot_running():
                print("[Daemon] bot.py is NOT running! Restarting...", flush=True)
                start_bot()
        except Exception as e:
            print(f"[Daemon] Error: {e}", flush=True)
        time.sleep(3.0)

if __name__ == "__main__":
    main()

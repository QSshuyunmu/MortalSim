"""QQ Bot 守护进程：确保 bot.py 始终在后台存活，若进程异常退出或被外部误杀则自动拉起。"""
import sys, time, subprocess, os
from pathlib import Path

BOT_DIR = Path(r"D:\tenhoulib\MortalSim-Bot").resolve()
PYTHON_EXE = sys.executable

def is_bot_running() -> bool:
    import psutil
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = p.info.get('cmdline') or []
            if any('bot.py' in str(arg) for arg in cmd) and not any('daemon.py' in str(arg) for arg in cmd):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def start_bot():
    print("[Daemon] Starting bot.py in background...", flush=True)
    subprocess.Popen(
        [PYTHON_EXE, str(BOT_DIR / "src" / "bot.py")],
        cwd=str(BOT_DIR),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )

def main():
    print("[Daemon] Bot Guardian started. Monitoring bot.py every 3 seconds...", flush=True)
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

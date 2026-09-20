"""Cloudflare Tunnel 进程管理器与公共 URL 发现服务。"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("tunnel_manager")

CLOUDFLARED_EXE = r"C:\Users\HP\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"
TUNNEL_LOG = Path(r"D:\tenhoulib\MortalSim-Bot\logs\tunnel.log")

_CURRENT_PUBLIC_BASE = ""
_LOCK = threading.Lock()


def get_public_base_url() -> str:
    """获取当前 Cloudflare Tunnel 分配的公共 HTTPS Base URL。"""
    global _CURRENT_PUBLIC_BASE
    with _LOCK:
        if _CURRENT_PUBLIC_BASE:
            return _CURRENT_PUBLIC_BASE
        # 尝试从日志中恢复
        if TUNNEL_LOG.exists():
            try:
                text = TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore")
                urls = re.findall(r'https://[a-zA-Z0-9_\-]+\.trycloudflare\.com', text)
                if urls:
                    _CURRENT_PUBLIC_BASE = urls[-1]
                    return _CURRENT_PUBLIC_BASE
            except Exception:
                pass
        return "http://127.0.0.1:50718"


def ensure_tunnel_running(port: int = 50718) -> None:
    """确保 cloudflared tunnel 在后台运行并监听指定端口。"""
    global _CURRENT_PUBLIC_BASE
    TUNNEL_LOG.parent.mkdir(parents=True, exist_ok=True)

    # 检查当前是否已有 cloudflared 正在运行
    try:
        import psutil
        for p in psutil.process_iter(['name', 'cmdline']):
            if p.info['name'] == 'cloudflared.exe':
                cmd = " ".join(p.info.get('cmdline') or [])
                if str(port) in cmd:
                    log.info("cloudflared tunnel 已经在运行中")
                    get_public_base_url()
                    return
    except Exception:
        pass

    def _run():
        global _CURRENT_PUBLIC_BASE
        log.info("正在启动 Cloudflare Tunnel...")
        cmd = [
            CLOUDFLARED_EXE,
            "tunnel",
            "--url", f"http://127.0.0.1:{port}",
            "--no-autoupdate"
        ]
        with open(TUNNEL_LOG, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            # 等待日志输出分配域名
            for _ in range(40):
                time.sleep(0.5)
                try:
                    text = TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore")
                    urls = re.findall(r'https://[a-zA-Z0-9_\-]+\.trycloudflare\.com', text)
                    if urls:
                        with _LOCK:
                            _CURRENT_PUBLIC_BASE = urls[-1]
                        log.info("Cloudflare Tunnel 成功创建公共 HTTPS 地址: %s", _CURRENT_PUBLIC_BASE)
                        break
                except Exception:
                    pass
            proc.wait()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

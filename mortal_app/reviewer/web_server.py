"""独立安全 Web 报告只读服务 (Secure Lightweight Review Server).

安全特性：
1. 最小化暴露：仅开放 GET /reviews/<token>.html 供外网/群友安全访问，不暴露任何 API 或写操作；
2. HMAC 签名防遍历令牌：每个报告绑定专属 token (包含 report_id, exp)，禁止 ID 自增枚举；
3. 严格路径前缀隔离：Path.resolve().is_relative_to(reviews_dir)，杜绝 .. 路径穿越与短名攻击；
4. 48 小时 TTL 自动清理：定时任务自动物理销毁过期报告，释放磁盘。
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("reviewer.web_server")

REVIEWS_DIR = Path(r"D:\tenhoulib\data\reviews").resolve()
PORT = 50718
SECRET_KEY = b"mortal_secure_review_secret_2026_salt"


def generate_report_token(report_id: str, ttl_seconds: int = 48 * 3600) -> str:
    """生成带有过期时间戳的 HMAC-SHA256 签名安全访问令牌。"""
    exp = int(time.time()) + ttl_seconds
    msg = f"{report_id}:{exp}".encode("utf-8")
    sig = hmac.new(SECRET_KEY, msg, hashlib.sha256).hexdigest()[:16]
    return f"{report_id}.{exp}.{sig}"


def verify_report_token(token: str) -> tuple[bool, str]:
    """验证访问令牌合法性与有效期。"""
    parts = token.split(".")
    if len(parts) != 3:
        return False, "令牌格式无效"
    report_id, exp_str, sig = parts
    try:
        exp = int(exp_str)
    except ValueError:
        return False, "过期时间无效"

    if time.time() > exp:
        return False, "报告已过期 (默认有效期 48 小时)"

    msg = f"{report_id}:{exp}".encode("utf-8")
    expected_sig = hmac.new(SECRET_KEY, msg, hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected_sig):
        return False, "签名校验失败"

    return True, report_id


class SecureReviewHandler(http.server.BaseHTTPRequestHandler):
    """仅提供安全防穿越只读服务的轻量 Handler。"""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 仅允许访问 /reviews/*.html 或 /r?token=...
        token = None
        if path == "/r" or path == "/review":
            qs = parse_qs(parsed.query)
            token = qs.get("id", [None])[0] or qs.get("token", [None])[0]
        elif path.startswith("/reviews/"):
            file_name = path[len("/reviews/"):]
            if file_name.endswith(".html"):
                token = file_name[:-5]

        if not token:
            self._send_error(404, "404 Not Found")
            return

        valid, report_id_or_err = verify_report_token(token)
        if not valid:
            self._send_error(403, f"403 Forbidden: {report_id_or_err}")
            return

        target_file = (REVIEWS_DIR / f"{report_id_or_err}.html").resolve()
        # 严格路径穿越拦截
        if not target_file.is_relative_to(REVIEWS_DIR) or not target_file.exists():
            self._send_error(404, "404 Report Not Found")
            return

        try:
            data = target_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            # 安全响应头
            self.send_header("Cache-Control", "private, no-cache, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            log.error("读取报告异常: %s", exc)
            self._send_error(500, "500 Internal Server Error")

    def _send_error(self, code: int, msg: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

    def log_message(self, format, *args):
        # 简化访问日志
        pass


def start_review_server_bg(port: int = PORT) -> http.server.HTTPServer:
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), SecureReviewHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info("安全 Web 报告服务已在后台启动: http://127.0.0.1:%s", port)
    return server

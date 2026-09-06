"""每日限额（SQLite，单进程）。"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date
from pathlib import Path

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_quota (
  user_id TEXT NOT NULL,
  date    TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  games   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS ocr_daily_quota (
  user_id TEXT NOT NULL,
  date    TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, date)
);
"""


class QuotaStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def _today(self) -> str:
        return date.today().isoformat()

    def usage(self, user_id: str, day: str | None = None) -> dict:
        day = day or self._today()
        with _lock:
            row = self._conn.execute(
                "SELECT requests, games FROM daily_quota WHERE user_id=? AND date=?",
                (user_id, day),
            ).fetchone()
        return {"requests": row[0] if row else 0, "games": row[1] if row else 0}

    def reserve(self, user_id: str, runs: int) -> None:
        """接受任务时预留额度。"""
        day = self._today()
        with _lock:
            self._conn.execute(
                """INSERT INTO daily_quota (user_id, date, requests, games) VALUES (?,?,1,?)
                   ON CONFLICT(user_id, date) DO UPDATE SET
                     requests = requests + 1, games = games + ?""",
                (user_id, day, runs, runs),
            )
            self._conn.commit()

    def release(self, user_id: str, runs: int) -> None:
        """任务失败/取消时释放预留额度（不减少到负数）。"""
        day = self._today()
        with _lock:
            self._conn.execute(
                """UPDATE daily_quota SET
                     requests = MAX(0, requests - 1),
                     games = MAX(0, games - ?)
                   WHERE user_id=? AND date=?""",
                (runs, user_id, day),
            )
            self._conn.commit()

    def check(self, user_id: str, runs: int, limits: dict) -> tuple[bool, str | None]:
        usage = self.usage(user_id)
        if usage["requests"] >= int(limits.get("max_requests_per_user_per_day", 5)):
            return False, f"今日模拟次数已达上限（{limits.get('max_requests_per_user_per_day', 5)} 次），请明天再试。"
        if usage["games"] + runs > int(limits.get("max_games_per_user_per_day", 2000)):
            return False, (
                f"今日模拟局数已达上限（{limits.get('max_games_per_user_per_day', 2000)} 局）；"
                f"当前已用 {usage['games']} 局，本次 {runs} 局会超额。"
            )
        return True, None

    # ---------- OCR 独立额度 ----------
    def ocr_usage(self, user_id: str, day: str | None = None) -> int:
        day = day or self._today()
        with _lock:
            row = self._conn.execute(
                "SELECT requests FROM ocr_daily_quota WHERE user_id=? AND date=?",
                (user_id, day),
            ).fetchone()
        return row[0] if row else 0

    def ocr_reserve(self, user_id: str) -> None:
        day = self._today()
        with _lock:
            self._conn.execute(
                """INSERT INTO ocr_daily_quota (user_id, date, requests) VALUES (?,?,1)
                   ON CONFLICT(user_id, date) DO UPDATE SET requests = requests + 1""",
                (user_id, day),
            )
            self._conn.commit()

    def ocr_release(self, user_id: str) -> None:
        day = self._today()
        with _lock:
            self._conn.execute(
                """UPDATE ocr_daily_quota SET requests = MAX(0, requests - 1)
                   WHERE user_id=? AND date=?""",
                (user_id, day),
            )
            self._conn.commit()

    def ocr_check(self, user_id: str, limit: int) -> tuple[bool, str | None]:
        used = self.ocr_usage(user_id)
        if used >= limit:
            return False, f"今日 OCR 次数已达上限（{limit} 次），请明天再试。"
        return True, None

    def reset_user(self, user_id: str, day: str | None = None) -> None:
        day = day or self._today()
        with _lock:
            self._conn.execute("DELETE FROM daily_quota WHERE user_id=? AND date=?", (user_id, day))
            self._conn.execute("DELETE FROM ocr_daily_quota WHERE user_id=? AND date=?", (user_id, day))
            self._conn.commit()

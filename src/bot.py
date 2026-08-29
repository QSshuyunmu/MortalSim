"""MortalSim QQ Bot 主程序（OneBot 11 正向 WebSocket + HTTP API）。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
import tomllib
from pathlib import Path

import httpx
import websocket

from mortal_client import MortalClient, MortalSimError
from parser import parse_sim_command
from quota import QuotaStore
from render_png import render_png

log = logging.getLogger("bot")


def load_config(path: str | Path = "config.toml") -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    with open(p, "rb") as f:
        return tomllib.load(f)


class Bot:
    def __init__(self, cfg: dict, config_path: str | Path = "config.toml"):
        self.config_path = Path(config_path)
        self._apply_config(cfg)
        self.quota = QuotaStore(self.quota_cfg["db_path"])
        self.mortal = MortalClient(self.mortal_cfg["api_base"])
        self.seen_messages: deque[tuple[float, tuple]] = deque(maxlen=500)
        self.tasks: asyncio.Queue = asyncio.Queue()
        self.active = 0  # 1 when a task is being executed, 0 otherwise
        self.active_item: dict | None = None
        self.current_run_id: str | None = None
        self.cancelled_user: str | None = None
        self.last_request: dict[str, float] = {}
        self._http: httpx.AsyncClient | None = None

    def _apply_config(self, cfg: dict) -> None:
        self.cfg = cfg
        self.bot_cfg = cfg["bot"]
        self.mortal_cfg = cfg["mortalsim"]
        self.quota_cfg = cfg["quota"]
        self.render_cfg = cfg["render"]
        self.bot_self_qq = str(cfg["bot"]["self_qq"])

    def reload_config(self) -> None:
        """重新读取 config.toml，使配置改动下一条消息生效。"""
        try:
            with open(self.config_path, "rb") as f:
                cfg = tomllib.load(f)
        except Exception as exc:
            log.warning("config reload failed: %s", exc)
            return
        self._apply_config(cfg)
        log.info("config reloaded")

    def trigger_restart(self, reason: str = "manual") -> None:
        """平滑重启 Bot 进程。"""
        log.info("触发重启（原因：%s）...", reason)
        try:
            _bot_lock_path().unlink(missing_ok=True)
        except Exception:
            pass
        bot_root = Path(__file__).resolve().parent.parent
        log_dir = bot_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            out_f = open(log_dir / "bot.log", "a", encoding="utf-8")
            err_f = open(log_dir / "bot.err", "a", encoding="utf-8")
        except Exception:
            out_f = subprocess.DEVNULL
            err_f = subprocess.DEVNULL

        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            cwd=str(bot_root),
            stdout=out_f,
            stderr=err_f,
            creationflags=flags,
            close_fds=True,
        )
        os._exit(0)

    async def _file_watcher(self) -> None:
        """监听 src/ 和 config.toml 变动，自动平滑重载。"""
        if not self.bot_cfg.get("auto_reload", True):
            return
        bot_root = Path(__file__).resolve().parent.parent
        src_dir = bot_root / "src"
        watched = [bot_root / "config.toml", *src_dir.glob("*.py")]
        mtimes = {p: p.stat().st_mtime for p in watched if p.exists()}

        while True:
            await asyncio.sleep(1.0)
            if not self.bot_cfg.get("auto_reload", True):
                continue
            current_files = [bot_root / "config.toml", *src_dir.glob("*.py")]
            for p in current_files:
                if not p.exists():
                    continue
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                if p not in mtimes:
                    mtimes[p] = mtime
                elif mtime > mtimes[p] + 0.1:
                    log.info("检测到文件变更：%s，正在自动重载 Bot...", p.name)
                    await asyncio.sleep(0.5)
                    self.trigger_restart(f"file_modified: {p.name}")
                    return

    # ---------- OneBot 网络 ----------
    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._http = httpx.AsyncClient(timeout=30)

        def on_message(_ws, raw: str):
            try:
                event = json.loads(raw)
            except Exception:
                return
            asyncio.run_coroutine_threadsafe(self.handle_event(event), loop)

        def on_error(_ws, error):
            log.error("OneBot WS error: %s", error)

        def ws_loop() -> None:
            while True:
                ws = websocket.WebSocketApp(
                    self.bot_cfg["onebot_ws_url"],
                    on_message=on_message,
                    on_error=on_error,
                )
                try:
                    ws.run_forever(ping_interval=20)
                except Exception:
                    pass
                # 确保旧连接完全关闭后再重连，避免两个连接并存导致重复事件
                try:
                    ws.close()
                except Exception:
                    pass
                log.warning("OneBot WS disconnected; reconnecting in 3s...")
                time.sleep(3)

        thread = threading.Thread(target=ws_loop, daemon=True)
        thread.start()
        log.info("Bot 已启动，等待 OneBot 事件...")
        try:
            active = await self.mortal.get_active_runs()
            if active:
                log.warning("检测到 MortalSim 已有 %d 个运行/排队任务，新模拟将等待其完成后再创建: %s", len(active), active)
        except Exception as exc:
            log.debug("启动时查询 MortalSim 活跃任务失败: %s", exc)
        asyncio.create_task(self.worker())
        asyncio.create_task(self._file_watcher())
        await asyncio.Future()

    async def _http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(trust_env=False, timeout=15.0)
        return self._http

    async def send_group_text(self, group_id: int, text: str) -> None:
        try:
            client = await self._http_client()
            resp = await client.post(
                f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                json={"group_id": group_id, "message": text},
            )
            if resp.status_code != 200 or (resp.json() or {}).get("status") == "failed":
                log.warning("发送群文字消息响应异常: HTTP %s, body: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.error("发送群文字消息失败 (group %s): %s", group_id, exc)

    async def send_group_image(self, group_id: int, image_path: str | Path) -> None:
        img_p = Path(image_path).resolve()
        file_uri = f"file:///{img_p.as_posix()}"
        client = await self._http_client()
        try:
            # 1. 优先使用本地 file:/// URI 发送（毫秒级直读，避免 base64 巨大负载）
            resp = await client.post(
                f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                json={
                    "group_id": group_id,
                    "message": [{"type": "image", "data": {"file": file_uri}}],
                },
            )
            if resp.status_code == 200 and (resp.json() or {}).get("status") != "failed":
                return
            log.warning("file:/// 方式发送图片未成功，尝试 base64 备用方式: %s", resp.text[:200])
        except Exception as exc:
            log.warning("file:/// 发送图片异常，尝试 base64 备用方式: %s", exc)

        try:
            # 2. 备用 base64 方式
            data = base64.b64encode(img_p.read_bytes()).decode()
            resp = await client.post(
                f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                json={
                    "group_id": group_id,
                    "message": [{"type": "image", "data": {"file": f"base64://{data}"}}],
                },
            )
            if resp.status_code != 200 or (resp.json() or {}).get("status") == "failed":
                log.error("base64 发送图片失败: HTTP %s, body: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.error("发送群图片失败 (group %s): %s", group_id, exc)

    async def send_group_result(self, group_id: int, user_id: str, text: str, image_path: str | Path) -> None:
        """模拟完成后：@派发用户 + 结果文字 + 图片，同一条消息发送。"""
        img_p = Path(image_path).resolve()
        file_uri = f"file:///{img_p.as_posix()}"
        message = [
            {"type": "at", "data": {"qq": str(user_id), "text": ""}},
            {"type": "text", "data": {"text": text}},
            {"type": "image", "data": {"file": file_uri}},
        ]
        try:
            client = await self._http_client()
            resp = await client.post(
                f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                json={"group_id": group_id, "message": message},
            )
            if resp.status_code != 200 or (resp.json() or {}).get("status") == "failed":
                log.warning("发送 @+图文 失败，退回分开发送: HTTP %s %s", resp.status_code, resp.text[:200])
                await self.send_group_text(group_id, text)
                await self.send_group_image(group_id, img_p)
        except Exception as exc:
            log.error("发送 @+图文 异常，退回分开发送: %s", exc)
            await self.send_group_text(group_id, text)
            await self.send_group_image(group_id, img_p)

    def _image_segment(self, segments: list) -> dict | None:
        for seg in segments:
            if seg.get("type") == "image":
                return seg.get("data") or {}
        return None

    def _image_url(self, segments: list) -> str | None:
        data = self._image_segment(segments)
        return str(data.get("url")) if data and data.get("url") else None

    async def get_onebot_image_path(self, file_id: str) -> str | None:
        """通过 OneBot get_image 获取 QQ 本地原图路径。"""
        client = await self._http_client()
        resp = await client.post(
            f"{self.bot_cfg['onebot_http_url']}/get_image",
            json={"file": file_id},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        local = (data.get("data") or {}).get("file")
        if local and Path(local).exists():
            return local
        return None


    def _is_duplicate(self, group_id: int, user_id: str, raw: str, message_id) -> bool:
        now = time.time()
        # 1) exact message_id dedup
        if message_id is not None:
            key_id = ("id", group_id, user_id, str(message_id))
            for ts, k in self.seen_messages:
                if k == key_id:
                    log.warning("duplicate OneBot event ignored (message_id): %s", key_id)
                    return True
            self.seen_messages.append((now, key_id))
        # 2) content dedup within 3s (NapCat may redeliver with a new message_id)
        key_content = ("content", group_id, user_id, raw)
        for ts, k in self.seen_messages:
            if k == key_content and now - ts < 3.0:
                log.warning("duplicate OneBot event ignored (content): %s", key_content)
                return True
        self.seen_messages.append((now, key_content))
        # prune old entries
        while self.seen_messages and now - self.seen_messages[0][0] > 10.0:
            self.seen_messages.popleft()
        return False

    def _is_admin(self, user_id: str) -> bool:
        admin_ids = {str(x) for x in self.bot_cfg.get("admin_qq", [])}
        return user_id == "2361035324" or user_id in admin_ids

    async def _cancel_user(self, user_id: str) -> int:
        """移除该用户在队列中的任务；若正在运行则调用 MortalSim 取消。返回移除/取消数。"""
        removed = 0
        q = self.tasks._queue
        pending = list(q)
        for item in pending:
            if item.get("user_id") == user_id:
                try:
                    q.remove(item)
                    removed += 1
                except ValueError:
                    pass
        if (
            self.active_item is not None
            and self.active_item.get("user_id") == user_id
            and self.current_run_id
        ):
            try:
                await self.mortal.cancel_run(self.current_run_id)
                self.cancelled_user = user_id
                removed += 1
            except Exception as exc:
                log.warning("取消运行中任务失败 (run=%s): %s", self.current_run_id, exc)
        return removed

    async def _enqueue_sim(self, group_id: int, user_id: str, request: dict) -> None:
        runs = int(request.get("runs") or self.mortal_cfg.get("default_runs", 500))
        if not self._is_admin(user_id):
            max_runs = int(self.mortal_cfg.get("max_runs", 2000))
            if runs > max_runs:
                await self.send_group_text(group_id, f"单次局数不能超过 {max_runs} 局（当前为 {runs} 局）。")
                return
            max_cands = int(self.mortal_cfg.get("max_candidates", 4))
            if len(request.get("discards", [])) > max_cands:
                await self.send_group_text(group_id, f"单次候选数量不能超过 {max_cands} 个（当前为 {len(request['discards'])} 个）。")
                return
        now = time.time()
        last = self.last_request.get(user_id, 0)
        cooldown = float(self.quota_cfg.get("cooldown_seconds", 60))
        if now - last < cooldown:
            await self.send_group_text(group_id, f"操作太频繁，请 {cooldown - (now - last):.0f} 秒后再试。")
            return
        self.last_request[user_id] = now
        if self.tasks.qsize() >= int(self.quota_cfg.get("max_global_queued", 5)):
            await self.send_group_text(group_id, "当前排队任务已满，请稍后再试。")
            return
        if self.quota_cfg.get("quota_enabled", False):
            ok, reason = self.quota.check(user_id, runs, self.quota_cfg)
            if not ok:
                await self.send_group_text(group_id, reason)
                return
        self.quota.reserve(user_id, runs)
        position = self.active + self.tasks.qsize() + 1
        await self.tasks.put({"user_id": user_id, "group_id": group_id, "request": request, "runs": runs})
        # 总是发送简短确认：进入模拟进程即告知用户已收到并在推演
        cand_count = len(request.get("discards", []))
        await self.send_group_text(
            group_id,
            f"🎲 已接收，正在推演 {runs} 局 × {cand_count} 个候选，请稍候...",
        )

    # ---------- 消息处理 ----------
    async def handle_event(self, event: dict) -> None:
        if event.get("post_type") != "message" or event.get("message_type") != "group":
            return
        group_id = int(event.get("group_id", 0))
        user_id = str(event.get("user_id", ""))
        message_id = event.get("message_id")
        raw = str(event.get("raw_message") or "")
        log.info("group msg msg_id=%s user=%s raw=%s", message_id, user_id, raw[:40])
        if self._is_duplicate(group_id, user_id, raw, message_id):
            return
        self.reload_config()
        group_id = int(event.get("group_id", 0))
        user_id = str(event.get("user_id", ""))
        raw = str(event.get("raw_message") or "")
        segments = event.get("message") or []
        mentioned = any(
            seg.get("type") == "at" and str(seg.get("data", {}).get("qq", "")) == self.bot_self_qq
            for seg in segments
        )
        if not mentioned:
            return
        whitelist = self.bot_cfg.get("group_whitelist") or []
        if whitelist and group_id not in [int(x) for x in whitelist]:
            return



        # 只取纯文本段，去掉 @ / 图片 / CQ 代码
        text_parts = []
        for seg in segments:
            if seg.get("type") == "text":
                text_parts.append(str(seg.get("data", {}).get("text", "")))
        text = " ".join("".join(text_parts).split())

        if not text or text.startswith(("/help", "帮助", "help")):
            await self.send_group_text(
                group_id,
                "🀄 【MortalSim 模拟器指令速查】\n"
                "格式：/sim 手牌 d宝牌 [c候选] [局况] [点数] [座次] [巡目] [局数]\n"
                "• 基础切牌：/sim 123456789m789s12p d8p E1-0 1000\n"
                "• 副露/见逃：/sim 77m4p4056799s112z d5s c=pon>4p,pass seat=东 x=2\n"
                "• 快捷选项：候选可省略自动提取；牌河可省略自动生成；点数写 P180,200,390,230 或 18k,20k,39k,23k\n"
                "• 控制指令：/state 查看状态 | /取消 撤回任务",
            )
            return

        if text.startswith(("/state", "状态", "state")):
            usage = self.quota.usage(user_id)
            await self.send_group_text(
                group_id,
                f"模拟队列：活跃 {self.active} / 排队 {self.tasks.qsize()}\n"
                f"今日模拟统计：共 {usage['requests']} 次，{usage['games']} 局（已取消每日上限）\n"
                f"单次限制：局数 <= 10000，候选 <= 4",
            )
            return

        if text.startswith("/sim"):
            request, error = parse_sim_command(text)
            if error:
                await self.send_group_text(group_id, error)
                return
            await self._enqueue_sim(group_id, user_id, request)
            return

        if text.startswith(("/取消", "取消")):
            removed = await self._cancel_user(user_id)
            if removed:
                await self.send_group_text(group_id, f"已取消你的 {removed} 个任务。")
            else:
                await self.send_group_text(group_id, "当前没有你的排队/运行任务。")
            return

        if text.startswith(("/stop", "/shutdown", "/exit", "停机", "停止")):
            if user_id == "2361035324" or user_id in [str(x) for x in self.bot_cfg.get("admin_qq", [])]:
                await self.send_group_text(group_id, "收到停机指令，Bot 进程已安全停止。")
                try:
                    _bot_lock_path().unlink(missing_ok=True)
                except Exception:
                    pass
                os._exit(0)
            else:
                await self.send_group_text(group_id, "你没有权限执行停机命令。")
            return

        if text.startswith(("/restart", "/reload", "重启")):
            if user_id == "2361035324" or user_id in [str(x) for x in self.bot_cfg.get("admin_qq", [])]:
                await self.send_group_text(group_id, "收到重启指令，正在重启 Bot 进程...")
                await asyncio.sleep(0.5)
                self.trigger_restart(f"admin_command from {user_id}")
            else:
                await self.send_group_text(group_id, "你没有权限执行重启命令。")
            return

        if text.startswith(("重置额度", "清零")):
            if user_id in [str(x) for x in self.bot_cfg.get("admin_qq", [])]:
                target = text.replace("重置额度", "").replace("清零", "").strip()
                if not target:
                    target = user_id
                self.quota.reset_user(target)
                await self.send_group_text(group_id, f"已重置 {target} 今日额度。")
            else:
                await self.send_group_text(group_id, "你没有权限执行该命令。")
            return

        # 默认引导回复（精简）
        await self.send_group_text(
            group_id,
            "/sim 手牌 d宝牌 c候选 [局-本场] [局数] [P点数]\n"
            "例：/sim 123456789m789s12p d8p c1p,2p E1-0 2000\n"
            "发送 /help 查看完整说明，/state 查看状态",
        )

    # ---------- 任务 Worker ----------
    async def worker(self) -> None:
        while True:
            item = await self.tasks.get()
            self.active = 1
            self.active_item = item
            self.current_run_id = None
            try:
                await self.execute(item)
            except Exception as exc:
                if self.cancelled_user == item.get("user_id"):
                    await self.send_group_text(item["group_id"], "已取消你的模拟任务。")
                else:
                    log.exception("task failed")
                    self.quota.release(item["user_id"], item["runs"])
                    await self.send_group_text(item["group_id"], f"任务失败：{exc}")
            finally:
                self.cancelled_user = None
                self.active_item = None
                self.current_run_id = None
                self.active = 0
                self.tasks.task_done()

    async def execute(self, item: dict) -> None:
        request = dict(item["request"])
        request["runs"] = item["runs"]
        request["batch_size"] = 1000
        request["model_id"] = self.mortal_cfg["model_id"]
        request["rayon_threads"] = int(self.mortal_cfg.get("rayon_threads", 20))
        request["engine"] = "lite"
        request["decision_contract"] = "stable_advantage_v2"
        if "scores" not in request:
            request["scores"] = {"self": 25000, "shimocha": 25000, "toimen": 25000}

        run_id = await self.mortal.create_run(request)
        self.current_run_id = run_id
        job = await self.mortal.wait_completed(run_id, float(self.mortal_cfg.get("timeout_seconds", 0)))
        result = job.get("result") or {}
        if not result.get("candidates"):
            raise MortalSimError("结果中没有候选数据")

        # 注入请求配置供 render_png 完整读取手牌、局况、宝牌
        result["config"] = job.get("request", {})

        def label(c):
            if not isinstance(c, dict):
                return "?"
            if c.get("first_kyushu") or c.get("candidate") == "kyushu:kk":
                return "kk"
            if c.get("first_tsumo") or c.get("candidate") == "tsumo":
                return "自摸"
            if c.get("first_ron") or c.get("candidate") == "ron":
                return "荣和"
            if c.get("first_pass") or c.get("candidate") == "pass":
                return "见逃"
            cand_name = str(c.get("candidate") or c.get("discard") or "?")
            if cand_name.startswith("chi:"):
                return f"吃 {cand_name[4:]}"
            if cand_name.startswith("pon"):
                return f"碰 {cand_name[3:]}" if len(cand_name) > 3 else "碰"
            if cand_name == "daiminkan":
                return "大明杠"
            base = c.get("discard") or cand_name
            if c.get("first_kan"):
                return base + "k"
            return base + ("r" if c.get("first_riichi") else "")

        candidates = result["candidates"]
        def _pt_value(c):
            v = (c.get("value") or {}).get("point", {}).get("value")
            return v if isinstance(v, (int, float)) else float("-inf")
        def _han_pt_value(c):
            v = ((c.get("hanchan") or {}).get("dan_pt_ev") or {}).get("houou_7", {}).get("value")
            return v if isinstance(v, (int, float)) else float("-inf")

        valid_candidates = [c for c in candidates if isinstance(c.get("value"), dict)]
        point_best = max(valid_candidates if valid_candidates else candidates, key=_pt_value)
        pt_best = max(valid_candidates if valid_candidates else candidates, key=_han_pt_value)
        recommended = pt_best if label(point_best) != label(pt_best) else point_best
        rec_tile = label(recommended)

        png_path = Path(self.render_cfg["output_dir"]) / f"{run_id}.png"
        import random
        selected_theme = random.choice(["obsidian", "emerald", "titanium"])
        render_png(
            result,
            asset_dir=self.render_cfg["tile_assets_dir"],
            font_path=self.render_cfg["font_path"],
            output_path=png_path,
            recommended_tile=rec_tile,
            theme=selected_theme,
        )
        x_turn = item.get("request", {}).get("x", 1)
        action_label = f"第 {x_turn} 打" if x_turn > 1 else "第一打"

        extra_info = []
        weighting = recommended.get("weighting") or {}
        if weighting.get("enabled"):
            ess = weighting.get("ess", 0)
            ratio = weighting.get("ess_ratio", 0)
            tau = weighting.get("tau", 1.0)
            extra_info.append(f"\n[牌河条件推理] tau={tau}，有效样本 ESS={ess:.0f} ({ratio:.1%})")
            if weighting.get("ess_warning"):
                extra_info.append("\n⚠️ 对手牌河拟合度较低，模拟方差较大")

        info_suffix = "".join(extra_info)

        await self.send_group_result(
            item["group_id"],
            item["user_id"],
            f"推荐{action_label}：{rec_tile}\n局收支最优：{label(point_best)}；预想pt最优：{label(pt_best)}。{info_suffix}",
            png_path,
        )


def _bot_lock_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "bot.lock"


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        return Path(f"/proc/{pid}").exists()
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    # ERROR_ACCESS_DENIED(5): process exists but is elevated -> treat as alive
    return ctypes.windll.kernel32.GetLastError() == 5


_bot_mutex_handle = None

_bot_mutex_handle = None

def _acquire_singleton() -> bool:
    """单实例锁：使用 Windows 原生命名互斥体 (Win32 Named Mutex) 保证全局绝对唯一实例。"""
    global _bot_mutex_handle
    if os.name != 'nt':
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        MUTEX_NAME = r"Global\MortalSim_Bot_Core_Singleton_Mutex"
        _bot_mutex_handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        last_error = kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            if _bot_mutex_handle:
                kernel32.CloseHandle(_bot_mutex_handle)
                _bot_mutex_handle = None
            log.error("another bot core instance is already running (Win32 Mutex Active); exiting.")
            return False
        return True
    except Exception as e:
        log.warning("Win32 Mutex check failed: %s; allowing startup.", e)
        return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not _acquire_singleton():
        return
    cfg = load_config()
    asyncio.run(Bot(cfg).run())


if __name__ == "__main__":
    main()

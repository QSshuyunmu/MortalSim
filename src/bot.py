"""MortalSim QQ Bot 主程序（OneBot 11 正向 WebSocket + HTTP API）。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# 确保真实 MortalSim 根目录在模块搜索路径的最前列，杜绝被历史遗留目录 shadowing
for _p_dir in [r"D:\tenhoulib\MortalSim", r"D:\tenhoulib\MortalSim\mortal_app", r"D:\tenhoulib"]:
    if _p_dir not in sys.path:
        sys.path.insert(0, _p_dir)

import threading
import time
import uuid
from collections import deque
from logging.handlers import RotatingFileHandler
import tomllib
from pathlib import Path

import httpx
import websocket

from mortal_client import MortalClient, MortalSimError
from parser import parse_sim_command
from quota import QuotaStore
from render_png import candidate_label, render_png

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
        # 队列落盘：进程重启（守护进程强杀/升级代码）时不丢用户任务
        self.data_dir = Path(__file__).resolve().parent.parent / "data"
        self.queue_file = self.data_dir / "queue.json"
        self.spool_dir = self.data_dir / "pending_results"
        self.pending: list[dict] = []
        # 独立 ReviewQueue 物理隔离：跑谱任务不阻塞即时 /sim
        self.review_tasks: asyncio.Queue = asyncio.Queue()
        self.review_active: int = 0

    def _apply_config(self, cfg: dict) -> None:
        self.cfg = cfg
        self.bot_cfg = cfg["bot"]
        self.mortal_cfg = cfg["mortalsim"]
        self.quota_cfg = cfg["quota"]
        self.render_cfg = cfg["render"]
        self.llm_cfg = cfg.get("llm", {})
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
        )
        sys.exit(0)

    def _is_admin(self, user_id: str) -> bool:
        admin_list = [str(x) for x in self.bot_cfg.get("admin_qq", [])]
        if user_id in admin_list:
            return True
        admins = self.bot_cfg.get("admin_qq") or []
        return str(user_id) in [str(x) for x in admins]

    def _is_duplicate(self, group_id: int, user_id: str, raw_msg: str, message_id: int | None = None) -> bool:
        now = time.time()
        while self.seen_messages and now - self.seen_messages[0][0] > 60.0:
            self.seen_messages.popleft()
        sig = (group_id, user_id, raw_msg, message_id)
        for _, existing in self.seen_messages:
            if existing == sig:
                return True
        self.seen_messages.append((now, sig))
        return False

    async def _http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(trust_env=False, timeout=30.0)
        return self._http

    async def send_group_file(self, group_id: int, file_path: str | Path, file_name: str | None = None) -> bool:
        """使用 OneBot 11 upload_group_file API 上传文件至 QQ 群（独立 120s 超时）。"""
        p_obj = Path(file_path).resolve()
        fname = file_name or p_obj.name
        try:
            client = await self._http_client()
            resp = await client.post(
                f"{self.bot_cfg['onebot_http_url']}/upload_group_file",
                json={
                    "group_id": group_id,
                    "file": str(p_obj),
                    "name": fname,
                },
                timeout=120.0,
            )
            if resp.status_code == 200 and (resp.json() or {}).get("status") == "ok":
                log.info("上传群文件成功: %s -> group %s", fname, group_id)
                return True
            log.warning("上传群文件响应异常: HTTP %s, body: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            log.error("上传群文件失败 (group %s): %s", group_id, exc)
            return False

    async def send_group_text(self, group_id: int, text: str) -> None:
        try:
            client = await self._http_client()
            resp = await client.post(
                f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                json={"group_id": group_id, "message": text},
            )
            if resp.status_code != 200 or (resp.json() or {}).get("status") == "failed":
                log.warning("发送群文字消息响应异常: HTTP %s, body: %s", resp.status_code, resp.text[:200])
                return False
            return True
        except Exception as exc:
            log.error("发送群文字消息失败 (group %s): %s", group_id, exc)
            return False

    async def send_group_image(self, group_id: int, image_path: str | Path) -> None:
        img_p = Path(image_path).resolve()
        client = await self._http_client()
        raw_path = str(img_p)
        file_uri = f"file:///{img_p.as_posix()}"
        
        # 1. 尝试绝对路径 (NapCat Windows 原生最快解析格式)
        for fmt in (raw_path, file_uri):
            try:
                resp = await client.post(
                    f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                    json={
                        "group_id": group_id,
                        "message": [{"type": "image", "data": {"file": fmt}}],
                    },
                    timeout=30.0,
                )
                if resp.status_code == 200 and (resp.json() or {}).get("status") != "failed":
                    return True
            except Exception as exc:
                log.warning("尝试路径发送图片异常 (%s): %s", fmt, exc)

        # 2. 备用 base64
        try:
            data = base64.b64encode(img_p.read_bytes()).decode()
            resp = await client.post(
                f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                json={
                    "group_id": group_id,
                    "message": [{"type": "image", "data": {"file": f"base64://{data}"}}],
                },
                timeout=60.0,
            )
            if resp.status_code == 200 and (resp.json() or {}).get("status") != "failed":
                return True
            log.error("base64 发送图片失败: HTTP %s, body: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.error("发送群图片失败 (group %s): %s", group_id, exc)
        return False

    async def _try_send_group_result(self, group_id: int, user_id: str, text: str, image_path: str | Path) -> bool:
        """单次投递尝试：合并发送，失败退化为分开发送。返回是否成功。"""
        img_p = Path(image_path)
        if not img_p.exists():
            return await self.send_group_text(group_id, text)
        raw_path = str(img_p.resolve())
        file_uri = f"file:///{img_p.resolve().as_posix()}"
        client = await self._http_client()

        for fmt in (raw_path, file_uri):
            message = [
                {"type": "at", "data": {"qq": str(user_id), "text": ""}},
                {"type": "text", "data": {"text": text}},
                {"type": "image", "data": {"file": fmt}},
            ]
            try:
                resp = await client.post(
                    f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                    json={"group_id": group_id, "message": message},
                    timeout=30.0,
                )
                if resp.status_code == 200 and (resp.json() or {}).get("status") != "failed":
                    return True
            except Exception as exc:
                log.warning("合并发送图文异常 (%s): %s", fmt, exc)

        # 若合并发送因协议超时拦截，退回分开发送
        ok_text = await self.send_group_text(group_id, text)
        ok_img = await self.send_group_image(group_id, img_p)
        return bool(ok_text and ok_img)

    def _spool_result(self, group_id: int, user_id: str, text: str, image_path: str | Path) -> None:
        """投递彻底失败时把结果落盘，等 NapCat 恢复后补发（绝不静默吞结果）。"""
        try:
            self.spool_dir.mkdir(parents=True, exist_ok=True)
            name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.json"
            (self.spool_dir / name).write_text(
                json.dumps(
                    {
                        "group_id": group_id,
                        "user_id": str(user_id),
                        "text": text,
                        "image_path": str(Path(image_path)),
                        "created_at": time.time(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            log.error("结果已转入补发队列: %s (group=%s)", name, group_id)
        except Exception as exc:
            log.error("结果落盘失败（本次结果丢失）: %s", exc)

    async def flush_spooled_results(self) -> None:
        """周期性补发积压结果（NapCat 重启、网络抖动恢复后自动补齐）。"""
        if not self.spool_dir.exists():
            return
        for f in sorted(self.spool_dir.glob("*.json")):
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                f.unlink(missing_ok=True)
                continue
            if time.time() - float(payload.get("created_at", 0)) < 15:
                continue  # 刚入队，先让主路径重试完
            try:
                ok = await self._try_send_group_result(
                    int(payload["group_id"]),
                    str(payload.get("user_id", "")),
                    payload.get("text", ""),
                    payload.get("image_path", ""),
                )
                if ok:
                    f.unlink(missing_ok=True)
                    log.info("补发积压结果成功: %s", f.name)
            except Exception as exc:
                log.warning("补发结果异常 (%s): %s", f.name, exc)

    async def send_group_result(self, group_id: int, user_id: str, text: str, image_path: str | Path) -> None:
        """模拟完成后：发送图文并茂的卡片消息。

        NapCat/OneBot 可能正在重启（守护进程会主动重启它），因此这里必须重试；
        重试仍失败则落盘到 data/pending_results 由后台补发 —— 结果绝不静默丢失。
        """
        for attempt, delay in enumerate((0.0, 3.0, 8.0, 20.0), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                if await self._try_send_group_result(group_id, user_id, text, image_path):
                    if attempt > 1:
                        log.info("结果第 %d 次尝试发送成功 (group=%s)", attempt, group_id)
                    return
            except Exception as exc:
                log.warning("发送结果异常（第 %d 次尝试, group=%s）: %s", attempt, group_id, exc)
        log.error("结果发送连续 %d 次失败，转入补发队列 (group=%s user=%s)", 4, group_id, user_id)
        self._spool_result(group_id, user_id, text, image_path)

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
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("file")
        return None

    # ---------- 队列管理 ----------
    def _save_pending(self) -> None:
        """原子写 data/queue.json（队列的持久化镜像）。"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.queue_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.pending, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.queue_file)
        except Exception as exc:
            log.warning("写入队列文件失败: %s", exc)

    def _load_pending(self) -> list[dict]:
        try:
            if not self.queue_file.exists():
                return []
            data = json.loads(self.queue_file.read_text(encoding="utf-8"))
            return [it for it in data if isinstance(it, dict) and it.get("request")]
        except Exception as exc:
            log.warning("读取队列文件失败（按空队列处理）: %s", exc)
            return []

    def _drop_pending(self, item: dict) -> None:
        before = len(self.pending)
        self.pending = [x for x in self.pending if x.get("id") != item.get("id")]
        if len(self.pending) != before:
            self._save_pending()

    async def _enqueue_item(self, item: dict) -> None:
        """入队 = 内存队列 + 落盘，两者保持一致。"""
        item.setdefault("id", uuid.uuid4().hex[:12])
        item.setdefault("submitted_at", time.time())
        self.pending.append(item)
        self._save_pending()
        await self.tasks.put(item)

    async def restore_pending(self) -> None:
        """启动时恢复重启前未完成的任务，并明确告知用户（不再静默清空队列）。"""
        items = self._load_pending()
        if not items:
            return
        log.warning("发现重启前未完成的任务 %d 个，重新入队", len(items))
        for item in items:
            self.pending.append(item)
            await self.tasks.put(item)
        self._save_pending()
        for idx, item in enumerate(items, start=1):
            try:
                await self.send_group_text(
                    item["group_id"],
                    f"机器人刚重启，你的任务（{item.get('runs')} 局）已自动重新排队，当前第 {idx} 位。",
                )
            except Exception:
                pass

    async def _cancel_user(self, user_id: str) -> int:
        removed = 0
        retained = []
        while not self.tasks.empty():
            try:
                item = self.tasks.get_nowait()
                self.tasks.task_done()
                if item.get("user_id") == user_id:
                    self.quota.release(user_id, item.get("runs", 0))
                    removed += 1
                else:
                    retained.append(item)
            except asyncio.QueueEmpty:
                break
        for item in retained:
            await self.tasks.put(item)
        if removed:
            self.pending = [x for x in self.pending if x.get("user_id") != user_id]
            self._save_pending()
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
        max_q = int(self.quota_cfg.get("max_queued_tasks", self.quota_cfg.get("max_global_queued", 8)))
        if self.tasks.qsize() >= max_q:
            await self.send_group_text(group_id, "当前排队任务已满，请稍后再试。")
            return
        if self.quota_cfg.get("quota_enabled", False):
            ok, reason = self.quota.check(user_id, runs, self.quota_cfg)
            if not ok:
                await self.send_group_text(group_id, reason)
                return
        self.quota.reserve(user_id, runs)
        await self._enqueue_item({"user_id": user_id, "group_id": group_id, "request": request, "runs": runs})

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
        # 1. 优先提取纯文本内容与指令
        text_parts = []
        for seg in segments:
            if seg.get("type") == "text":
                text_parts.append(str(seg.get("data", {}).get("text", "")))
        text = " ".join("".join(text_parts).split())

        # 2. 判断是否是确定性指令 (/sim, /help, /state, /review, /取消)
        is_direct_cmd = text.startswith(("/sim", "sim", "/help", "help", "帮助", "/state", "state", "状态", "/review", "review", "跑谱", "复盘", "/取消", "取消"))

        # 3. 判断是否 @ 了机器人
        mentioned = any(
            seg.get("type") == "at" and str(seg.get("data", {}).get("qq", "")) == self.bot_self_qq
            for seg in segments
        )

        # 只要是明确指令，或者 @ 了机器人，即放行处理；普通群员闲聊不插话
        if not (mentioned or is_direct_cmd):
            return

        whitelist = self.bot_cfg.get("group_whitelist") or []
        if whitelist and group_id not in [int(x) for x in whitelist]:
            return

        # 文本已在上文提取规整完毕

        if not text or text.startswith(("/help", "帮助", "help")):
            await self.send_group_text(
                group_id,
                "【Morta 推演中枢 快速指南】\n\n"
                "🀄 牌谱复盘：\n"
                "/review <链接> [tw/seat=0~3] [model=c/n/b/j]\n"
                "• 示例：/review http://tenhou.net/0/?log=...&tw=1 model=n\n"
                "• 模型：c(共识/默认), n(争一), b(避四), j(奇策)\n\n"
                "🎲 局况仿真：\n"
                "/sim <14张手牌> d<宝牌> [条件...]\n"
                "• 示例：/sim 123456789m789s12p d8p c1pr,2p S1-0 seat=南 1000\n\n"
                "📊 状态管理：\n"
                "• /state：查看当前 GPU 队列与状态\n"
                "• /取消：撤回排队中或运行中的任务",
            )
            return

        if text.startswith(("/state", "状态", "state")):
            usage = self.quota.usage(user_id)
            await self.send_group_text(
                group_id,
                f"推演队列：活跃 {self.active} / 排队 {self.tasks.qsize()}\n"
                f"跑谱队列：活跃 {self.review_active} / 排队 {self.review_tasks.qsize()}\n"
                f"今日模拟统计：共 {usage['requests']} 次，{usage['games']} 局（已取消每日上限）\n"
                f"单次限制：局数 <= 10000，候选 <= 4",
            )
            return

        if text.startswith(("/review", "跑谱", "复盘")):
            sub_text = re.sub(r"^/review\s*|^跑谱\s*|^复盘\s*", "", text).strip()
            if not sub_text:
                await self.send_group_text(group_id, "请提供天凤或雀魂牌谱链接，例如：\n/review https://tenhou.net/0/?log=...")
                return
            await self._enqueue_review(group_id, user_id, sub_text)
            return

        if text.startswith("/sim"):
            request, error = parse_sim_command(text)
            if error:
                # 若命令格式错误但启用了 LLM，尝试智能校正
                if self.llm_cfg.get("enabled", False) and len(text) > 8:
                    from nl_translator import route_user_intent
                    intent = await route_user_intent(text, self.llm_cfg)
                    if intent and intent.get("action") == "sim":
                        fixed = str(intent.get("command") or "").strip()
                        if fixed.startswith("/sim"):
                            fixed_req, fixed_err = parse_sim_command(fixed)
                            if not fixed_err:
                                await self.send_group_text(group_id, f"💡 格式校正：{fixed}\n正在排队演算……以上。")
                                await self._enqueue_sim(group_id, user_id, fixed_req)
                                return
                await self.send_group_text(group_id, error)
                return
            # 格式正确时，给用户即时反馈确认提示
            await self.send_group_text(group_id, f"💡 指令已确认：{text}\n正在排队演算……以上。")
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
            if user_id in [str(x) for x in self.bot_cfg.get("admin_qq", [])]:
                await self.send_group_text(group_id, "收到停机指令，Bot 进程已安全停止。")
                try:
                    _bot_lock_path().unlink(missing_ok=True)
                except Exception:
                    pass
                sys.exit(0)

        # 兜底自然语言智能识别：未命中固定指令但 @ 了机器人时，尝试识别麻将局面
        if self.llm_cfg.get("enabled", False):
            await self._handle_natural_language_sim(group_id, user_id, text)
            return

    async def _handle_natural_language_sim(self, group_id: int, user_id: str, text: str) -> None:
        """调用意图路由引擎，支持取消、推演、复盘、状态及冷萌问答。"""
        if not self.llm_cfg.get("enabled", False):
            return
        if len(text.strip()) < 2:
            return

        try:
            from nl_translator import route_user_intent
            intent = await route_user_intent(text, self.llm_cfg)
        except Exception as exc:
            log.warning("LLM 意图识别异常: %s", exc)
            return

        if not intent or not isinstance(intent, dict):
            return

        action = intent.get("action")
        reply = str(intent.get("reply") or "").strip()

        # 1. 任务取消 (由 Python 端严格基于消息发送者的 user_id 鉴权)
        if action == "cancel":
            removed = await self._cancel_user(user_id)
            if removed:
                msg = f"{reply}\n已终止你的 {removed} 个任务。" if reply else f"任务调度已中断。已终止你的 {removed} 个任务。"
            else:
                msg = "当前队列中无属于你的活跃任务。"
            await self.send_group_text(group_id, msg)
            return

        # 2. 查询排队状态
        if action == "state":
            usage = self.quota.usage(user_id)
            prefix = f"{reply}\n" if reply else ""
            state_msg = (
                f"{prefix}"
                f"• 仿真队列：活跃 {self.active} / 排队 {self.tasks.qsize()}\n"
                f"• 牌谱审查：活跃 {self.review_active} / 排队 {self.review_tasks.qsize()}\n"
                f"• 今日调用：{usage['requests']} 次 ({usage['games']} 局)"
            )
            await self.send_group_text(group_id, state_msg)
            return

        # 3. 牌谱检讨
        if action == "review":
            url = str(intent.get("url") or "").strip()
            if url:
                if reply:
                    await self.send_group_text(group_id, reply)
                await self._enqueue_review(group_id, user_id, url)
                return
            await self.send_group_text(group_id, "未检测到对局链接。……无法解析。请提供天凤或雀魂牌谱。")
            return

        # 4. 局面推演
        if action == "sim":
            cmd = str(intent.get("command") or "").strip()
            if cmd.startswith("/sim"):
                request, error = parse_sim_command(cmd)
                if error:
                    await self.send_group_text(group_id, f"局面参数存在异常。……无法构建。\n{cmd}\n错误：{error}")
                    return
                prefix = f"{reply}\n" if reply else ""
                await self.send_group_text(group_id, f"{prefix}💡 识别指令：{cmd}")
                await self._enqueue_sim(group_id, user_id, request)
                return
            if reply:
                await self.send_group_text(group_id, reply)
            return

        # 5. 战术规则问答 / 闲聊 / 质询
        if reply:
            await self.send_group_text(group_id, reply)
            return
    async def _enqueue_review(self, group_id: int, user_id: str, source_str: str) -> None:
        if self.review_tasks.qsize() >= 3:
            await self.send_group_text(group_id, "当前跑谱审查队列已满 (最多排队 3 场)，请稍候再试。")
            return
        await self.send_group_text(group_id, "已收到牌谱检讨任务，正在抓取对局并调度 Mortal 核心引擎进行深度推演...")
        await self.review_tasks.put({"group_id": group_id, "user_id": user_id, "source": source_str})

    async def review_worker(self) -> None:
        """独立的牌谱审查工作线程，完全物理隔离，不阻塞即时 /sim。"""
        while True:
            try:
                task = await self.review_tasks.get()
                self.review_active = 1
                group_id = task["group_id"]
                user_id = task["user_id"]
                source = task["source"]

                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._execute_review_sync, group_id, user_id, source)
                except Exception as exc:
                    log.exception("跑谱审查执行异常: %s", exc)
                    await self.send_group_text(group_id, f"牌谱审查失败：{exc}")
                finally:
                    self.review_active = 0
                    self.review_tasks.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.exception("review_worker 出现未捕获异常: %s", exc)
                await asyncio.sleep(1.0)

    @staticmethod
    def _analyze_review_attribution(review_result: dict, target_seat: int) -> str:
        """分析对局失分与恶手归因，生成莫塔风格的定性判词。"""
        rev = review_result.get("review", {})
        rating = rev.get("rating", 1.0) * 100
        fatal_losses = []
        big_mistakes = []
    
        for kyoku in rev.get("kyokus", []):
            b_name = ["东", "南", "西", "北"][kyoku.get("bakaze", 0)]
            k_num = kyoku.get("kyoku", 0) + 1
            h_num = kyoku.get("honba", 0)
            h_str = f"{h_num}本场" if h_num > 0 else ""
            kyoku_name = f"{b_name}{k_num}局{h_str}"
    
            end_status = kyoku.get("end_status", [])
            deal_in_event = next((ev for ev in end_status if ev.get("type") == "hora" and ev.get("target") == target_seat), None)
    
            entries = kyoku.get("entries", [])
            deal_in_is_consistent = True
    
            if deal_in_event:
                pts = abs(deal_in_event.get("deltas", [0, 0, 0, 0])[target_seat])
                if entries:
                    last_e = entries[-1]
                    if not last_e.get("is_equal", True):
                        deal_in_is_consistent = False
                if pts >= 7700:
                    fatal_losses.append({
                        "kyoku": kyoku_name,
                        "pts": pts,
                        "consistent": deal_in_is_consistent,
                    })
    
            for e in entries:
                if not e.get("is_equal", True):
                    details = e.get("details", [])
                    act = e.get("actual", {})
                    act_q = next((d.get("q_value") or d.get("prob", 0) for d in details if d.get("action") == act), 0)
                    exp_q = next((d.get("q_value") or d.get("prob", 0) for d in details if d.get("action") == e.get("expected")), 0)
                    if (exp_q - act_q) >= 3.0:
                        big_mistakes.append((kyoku_name, e.get("junme")))
    
        # 判定 A: 高评分 (>=82) 且重大失分均与推荐一致 -> 下限方差/不可抗力
        if rating >= 82.0 and fatal_losses and all(fl["consistent"] for fl in fatal_losses):
            loss_desc = "、".join([f"{fl['kyoku']}-{fl['pts']}点" for fl in fatal_losses[:2]])
            return f"判定：下限方差（不可抗力）。……失分非恶手导致。\n{loss_desc}均与 Mortal 推荐一致。"
    
        # 判定 B: 评分偏低或多次重大恶手 -> 技术问题
        if rating < 78.0 or len(big_mistakes) >= 3:
            return f"判定：技术偏差。……检出 {len(big_mistakes)} 处关键恶手。\n存在明显防守或造牌失误，建议复盘。"
    
        # 判定 C: 存在偏离推荐的放铳
        inconsistent_losses = [fl for fl in fatal_losses if not fl["consistent"]]
        if inconsistent_losses:
            loss_desc = inconsistent_losses[0]["kyoku"]
            return f"判定：攻防失准。……{loss_desc}存在偏离推荐的激进打法。"
    
        if rating >= 85.0:
            return "判定：发挥稳定。……无重大决策失误。"
        return "判定：局况平稳。……存在微弱期望损耗。"
    
    def _execute_review_sync(self, group_id: int, user_id: str, source_str: str) -> None:
        """同步执行审查、生成 HTML 并双通道交付。"""
        import sys, time
        from pathlib import Path
        for p_dir in [r"D:\tenhoulib\MortalSim", r"D:\tenhoulib"]:
            if p_dir in sys.path:
                sys.path.remove(p_dir)
            sys.path.insert(0, p_dir)

        # 深度防御：若 sys.modules 中缓存的 mortal_app 并非来自 MortalSim，强制清退重载
        if "mortal_app" in sys.modules:
            mod_file = getattr(sys.modules["mortal_app"], "__file__", "") or ""
            if "MortalSim" not in mod_file:
                for k in list(sys.modules.keys()):
                    if k == "mortal_app" or k.startswith("mortal_app."):
                        del sys.modules[k]

        from mortal_app.reviewer.fetcher import load_replay_to_mjai
        from mortal_app.reviewer.engine import run_multi_model_review
        from mortal_app.reviewer.web.packager import generate_standalone_review_html

        # 1. 解析 model 参数
        model_name = "distill_consensus_v3"
        official_tag_name = "Consensus"
        clean_source = source_str
        import re

        m_match = re.search(r'model=([a-zA-Z0-9_\-]+)', source_str, re.IGNORECASE)
        if m_match:
            user_model = m_match.group(1).lower()
            clean_source = re.sub(r'model=[a-zA-Z0-9_\-]+', '', clean_source, flags=re.IGNORECASE).strip()
            from mortal_app.manifest_manager import resolve_model_path
            tag, pth, _ = resolve_model_path(user_model)
            if pth:
                model_name = pth.stem
                official_tag_name = tag

        # 2. 解析显式指定的 seat 参数 (例如 seat=2)
        explicit_seat = None
        s_match = re.search(r'seat=([0-3])', source_str, re.IGNORECASE)
        if s_match:
            explicit_seat = int(s_match.group(1))
            clean_source = re.sub(r'seat=[0-3]', '', clean_source, flags=re.IGNORECASE).strip()

        # 3. 提取链接中的 tw 参数 (例如 tw=1) 作为默认视角
        tw_match = re.search(r'[?&]tw=([0-3])', clean_source, re.IGNORECASE)
        tw_seat = int(tw_match.group(1)) if tw_match else None

        events, err, meta = load_replay_to_mjai(clean_source)
        if err or not events:
            self._post_group_msg_sync(group_id, f"牌谱获取失败：{err or '无法识别的牌谱链接'}")
            return

        # 最终决定目标视角：显式 seat > 链接 tw > 默认 0
        if explicit_seat is not None:
            target_seat = explicit_seat
        elif tw_seat is not None:
            target_seat = tw_seat
        else:
            target_seat = meta.get("target_seat", 0)

        seat_names = ["东", "南", "西", "北"]
        seat_zh = seat_names[target_seat] if target_seat in (0, 1, 2, 3) else f"{target_seat}号位"

        # 通过 GpuLease 互斥保护推断
        from mortal_app.gpu_lease import guarded_gpu_context
        with guarded_gpu_context(model_name, timeout=40.0):
            review_result = run_multi_model_review(events, target_seat=target_seat, model_id=model_name)

        paipu_id = meta.get("id") or "replay"
        ts = int(time.time())
        from mortal_app.reviewer.web_server import REVIEWS_DIR
        out_dir = REVIEWS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        html_file = out_dir / f"review_{paipu_id}_{ts}.html"

        generate_standalone_review_html(review_result, html_file)

        rev = review_result.get("review", {})
        total_rev = rev.get("total_reviewed", 0)
        total_match = rev.get("total_matches", 0)
        rating_pct = round(rev.get("rating", 1.0) * 100, 1)
        match_pct = round(total_match / total_rev * 100, 1) if total_rev else 100.0

        from mortal_app.reviewer.web_server import generate_report_token
        from tunnel_manager import get_public_base_url
        report_token = generate_report_token(f"review_{paipu_id}_{ts}")
        base_url = get_public_base_url()
        web_link = f"{base_url}/reviews/{report_token}.html"

        attribution_verdict = self._analyze_review_attribution(review_result, target_seat)

        summary_msg = (
            f"【Mortal 牌谱检讨】\n"
            f"视角：{seat_zh}家 ({target_seat}号位) | 共 {total_rev} 巡\n"
            f"模型：{official_tag_name} | 评分：{rating_pct} | 吻合度：{match_pct}%\n"
            f"{attribution_verdict}\n"
            f"🌐 在线复盘：{web_link}"
        )
        self._post_group_msg_sync(group_id, summary_msg)

    def _post_group_msg_sync(self, group_id: int, text: str) -> None:
        try:
            import requests
            requests.post(
                f"{self.bot_cfg['onebot_http_url']}/send_group_msg",
                json={"group_id": group_id, "message": text},
                timeout=15.0,
            )
        except Exception as exc:
            log.warning("同步发送群消息异常: %s", exc)

    def _upload_group_file_sync(self, group_id: int, file_path: Path, file_name: str) -> bool:
        try:
            import requests
            resp = requests.post(
                f"{self.bot_cfg['onebot_http_url']}/upload_group_file",
                json={
                    "group_id": group_id,
                    "file": str(file_path.resolve()),
                    "name": file_name,
                },
                timeout=120.0,
            )
            if resp.status_code == 200 and (resp.json() or {}).get("status") == "ok":
                log.info("同步上传群文件成功: %s -> group %s", file_name, group_id)
                return True
            log.warning("同步上传群文件返回状态异常: %s", resp.text[:200])
            return False
        except Exception as exc:
            log.warning("同步上传群文件异常: %s", exc)
            return False

    # ---------- 任务 Worker ----------
    async def worker(self) -> None:
        while True:
            try:
                item = await self.tasks.get()
                self._drop_pending(item)
                self.active = 1
                self.active_item = item
                self.current_run_id = None
                try:
                    await self.execute(item)
                except Exception as exc:
                    if self.cancelled_user == item.get("user_id"):
                        try:
                            await self.send_group_text(item["group_id"], "已取消你的模拟任务。")
                        except Exception:
                            pass
                    else:
                        log.exception("task failed")
                        try:
                            self.quota.release(item["user_id"], item["runs"])
                        except Exception:
                            pass
                        try:
                            await self.send_group_text(item["group_id"], f"任务失败：{exc}")
                        except Exception:
                            pass
                finally:
                    self.cancelled_user = None
                    self.active_item = None
                    self.current_run_id = None
                    self.active = 0
                    try:
                        self.tasks.task_done()
                    except Exception:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.exception("unexpected error in worker loop: %s", exc)
                await asyncio.sleep(1.0)

    def _eval_model_qp(self, request: dict) -> dict[str, dict[str, float]]:
        """对当前局面跑一次选中模型的前向推断，取各候选动作的 Q 与归一化 P。

        仅在 parser 未推断过（用户显式给了 c= 候选）时才需要调用；无 c= 时
        parser 已把同一局面的推断结果放进 request["_model_qp"]，直接复用。

        失败时静默返回 {} —— 报表会显示 "—"，不影响主推演结果。
        """
        try:
            from model_eval import eval_model_qp
            scores = request.get("scores") or {}
            return eval_model_qp(
                hand_str=request.get("hand", ""),
                dora_indicator=request.get("dora", ""),
                round_str=str(request.get("round", "E1")),
                honba=int(request.get("honba") or 0),
                kyotaku=int(request.get("kyotaku") or 0),
                target_seat=int(request.get("target_seat") or 0),
                scores=scores,
                model_id=request.get("model_id", "distill_41b_infer"),
            )
        except Exception as exc:
            log.warning("模型 Q/P 推断失败，报表对应列将留空: %s", exc)
            return {}

    async def execute(self, item: dict) -> None:
        request = dict(item["request"])
        # 无 c= 候选时 parser 已经为“生成候选”跑过一次模型推断，那份 Q/P 直接复用；
        # 只有显式给了 c= 候选（parser 没推断过）时才在这里补推断。
        precomputed_qp = request.pop("_model_qp", None)
        request["runs"] = item["runs"]
        request["batch_size"] = 1000
        # 模型映射: parser 内部用不透明别名，此处映射回后端真实模型 ID (用户侧绝不显示模型名)
        # 模型映射: parser 内部用不透明别名，此处映射回后端真实模型 ID (用户侧绝不显示模型名)
        # 保持上游行为：非已知别名一律回落到配置默认模型，不透传未知模型 ID。
        internal_model = request.get("model_id", self.mortal_cfg.get("model_id", "model_balanced"))
        request["model_id"] = {
            "model_balanced": "distill_41b_infer",
            "model_aggressive": "distill_nova",
        }.get(internal_model, self.mortal_cfg.get("model_id", "distill_41b_infer"))
        request["rayon_threads"] = int(self.mortal_cfg.get("rayon_threads", 20))
        request["engine"] = "python"
        request["decision_contract"] = "legacy_amp_v1"
        if "scores" not in request:
            request["scores"] = {"self": 25000, "shimocha": 25000, "toimen": 25000}

        run_id = await self.mortal.create_run(request)
        self.current_run_id = run_id
        job = await self.mortal.wait_completed(run_id, timeout_seconds=0)
        result = job.get("result") or {}
        if not result.get("candidates"):
            raise MortalSimError("结果中没有候选数据")

        # 注入请求配置供 render_png 完整读取手牌、局况、宝牌
        result["config"] = job.get("request", {})
        # 手牌铺排间距渲染偏好：仅在 [render] 显式配置时下发，未配置则不改上游默认间距。
        if "hand_tile_gap" in self.render_cfg:
            result["config"].setdefault("hand_tile_gap", int(self.render_cfg["hand_tile_gap"]))
        if "hand_tsumo_gap" in self.render_cfg:
            result["config"].setdefault("hand_tsumo_gap", int(self.render_cfg["hand_tsumo_gap"]))

        # QQ 文本与图片使用相同的动作标签，避免立直/和牌等推荐高亮失配。
        label = candidate_label

        candidates = result["candidates"]
        def _pt_value(c):
            v = (c.get("value") or {}).get("point", {}).get("value")
            return v if isinstance(v, (int, float)) else float("-inf")
        def _han_pt_value(c):
            v = ((c.get("hanchan") or {}).get("dan_pt_ev") or {}).get("houou_7", {}).get("value")
            return v if isinstance(v, (int, float)) else float("-inf")

        def _mleague_value(c):
            v = ((c.get("hanchan") or {}).get("mleague_pt_ev") or {}).get("value")
            return v if isinstance(v, (int, float)) else float("-inf")

        valid_candidates = [c for c in candidates if isinstance(c.get("value"), dict)]
        point_best = max(valid_candidates if valid_candidates else candidates, key=_pt_value)
        pt_best = max(valid_candidates if valid_candidates else candidates, key=_han_pt_value)
        ml_best = max(valid_candidates if valid_candidates else candidates, key=_mleague_value)

        # 默认高亮天凤最优（作为主卡片第一高亮）
        recommended = pt_best
        rec_tile = label(recommended)

        # 复用选中模型的 Q/P 结果；报表仅展示归一P，Q 留作内部候选排序。
        model_qp = precomputed_qp if precomputed_qp is not None else self._eval_model_qp(request)

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
            model_qp=model_qp,
        )
        x_turn = item.get("request", {}).get("x", 1)
        action_label = f"第 {x_turn} 打" if x_turn > 1 else "第一打"

        # 决策语义徽章
        dec_badge = (result.get("decision_state") or {}).get("badge") or "🌟 明确优选"
        cum_runs = result.get("cumulative_total_runs") or result.get("total_runs") or item["runs"]

        extra_info = []
        if cum_runs > item["runs"]:
            extra_info.append(f"\n[历史沉淀加速] 累积样本 {cum_runs} 局")

        weighting = recommended.get("weighting") or {}
        if weighting.get("enabled"):
            ess = weighting.get("ess", 0)
            ratio = weighting.get("ess_ratio", 0)
            tau = weighting.get("tau", 1.0)
            extra_info.append(f"\n[牌河条件推理] tau={tau}，有效样本 ESS={ess:.0f} ({ratio:.1%})")
            if weighting.get("ess_warning"):
                extra_info.append("\n⚠️ 对手牌河拟合度较低，模拟方差较大")

        info_suffix = "".join(extra_info)

        # 双规决策并列裁定：
        lbl_pt = label(pt_best)
        lbl_ml = label(ml_best)
        if lbl_pt == lbl_ml:
            rec_summary = f"推荐{action_label}：{lbl_pt}（全规则一致最优）"
        else:
            rec_summary = f"推荐{action_label}：{lbl_pt}（天凤避四）/ {lbl_ml}（M规争一）"

        await self.send_group_result(
            item["group_id"],
            item["user_id"],
            f"【{dec_badge}】{rec_summary}\n局收支最优：{label(point_best)}；天凤最优：{lbl_pt}；M规最优：{lbl_ml}。{info_suffix}",
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
    return ctypes.windll.kernel32.GetLastError() == 5


_bot_mutex_handle = None

def _acquire_singleton() -> bool:
    """双重单实例锁：Win32 命名互斥体 + 文件独占锁，确保全局唯一实例。"""
    global _bot_mutex_handle
    # 1. 检查并清理孤儿残留进程
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if proc.info['pid'] != current_pid and proc.info['name'] == 'python.exe':
                cmd = " ".join(proc.info.get('cmdline') or [])
                if 'bot.py' in cmd and 'daemon.py' not in cmd:
                    log.warning("检测到残留的 bot 进程 (PID: %s)，正在强制终止以保证全局单例唯一性...", proc.info['pid'])
                    try:
                        proc.kill()
                    except Exception:
                        pass
    except Exception as exc:
        log.warning("清理残留 bot 进程失败: %s", exc)

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
            log.error("检测到已有激活的 Bot 互斥体，当前实例退出。")
            return False
        return True
    except Exception as e:
        log.warning("Win32 Mutex 异常: %s; 允许启动。", e)
        return True


def _setup_logging() -> None:
    """控制台 + logs/bot.log 双写。

    守护进程以 DEVNULL 方式拉起本进程，若只配 basicConfig（仅 stderr），
    线上出问题时将完全不可观测——历史上"队列静默清空"就是这么被埋掉的。
    """
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    file_handler = RotatingFileHandler(
        log_dir / "bot.log", maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def main() -> None:
    _setup_logging()
    if not _acquire_singleton():
        return
    cfg = load_config()

    # 优先绑定当前线程的事件循环，确保 Bot 内部的 asyncio.Queue 归属正确
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = Bot(cfg)

    # 启动后台任务处理 Worker 协程，附带崩溃自动拉起
    worker_task = loop.create_task(bot.worker())
    review_worker_task = loop.create_task(bot.review_worker())

    def _on_review_worker_done(t):
        if not t.cancelled() and t.exception():
            log.error("review_worker crashed: %s; restarting", t.exception())
            loop.create_task(bot.review_worker()).add_done_callback(_on_review_worker_done)
    review_worker_task.add_done_callback(_on_review_worker_done)

    def _on_worker_done(t):
        if not t.cancelled() and t.exception():
            log.error("worker crashed with exception: %s; restarting worker", t.exception())
            loop.create_task(bot.worker()).add_done_callback(_on_worker_done)

    worker_task.add_done_callback(_on_worker_done)

    # 恢复重启前未完成的任务（并告知用户），彻底消除"队列被静默清空"
    loop.create_task(bot.restore_pending())

    async def _flush_spooled_loop() -> None:
        while True:
            await asyncio.sleep(30.0)
            try:
                await bot.flush_spooled_results()
            except Exception as exc:
                log.warning("补发循环异常: %s", exc)

    loop.create_task(_flush_spooled_loop())

    # 启动 Cloudflare Tunnel 外网公共直链服务
    from tunnel_manager import ensure_tunnel_running
    ensure_tunnel_running(50718)

    # 启动 OneBot WebSocket 客户端监听
    def run_ws():
        def on_message(ws, msg_str):
            try:
                data = json.loads(msg_str)
                asyncio.run_coroutine_threadsafe(bot.handle_event(data), loop)
            except Exception as e:
                log.error("WS on_message error: %s", e)

        def on_error(ws, error):
            log.error("OneBot WS error: %s", error)

        def on_close(ws, close_status_code, close_msg):
            log.warning("OneBot WS disconnected; reconnecting in 3s...")

        def on_open(ws):
            log.info("Websocket connected")

        ws_url = bot.bot_cfg["onebot_ws_url"]
        while True:
            try:
                ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                ws.run_forever()
            except Exception as exc:
                log.error("WebSocket run_forever exc: %s", exc)
            time.sleep(3.0)

    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    async def _heartbeat_loop() -> None:
        """向 data/bot.heartbeat 写入存活心跳，供守护进程判定 Bot 是否假死。"""
        hb = Path(__file__).resolve().parent.parent / "data" / "bot.heartbeat"
        while True:
            try:
                hb.parent.mkdir(parents=True, exist_ok=True)
                hb.write_text(f"{int(time.time())} pid={os.getpid()}\n", encoding="utf-8")
            except Exception as exc:
                log.warning("heartbeat write failed: %s", exc)
            await asyncio.sleep(10.0)

    loop.create_task(_heartbeat_loop())

    log.info("Bot 已启动，等待 OneBot 事件...")
    try:
        loop.run_forever()
    finally:
        loop.close()


if __name__ == "__main__":
    main()

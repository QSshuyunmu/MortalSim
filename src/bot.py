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
        )
        sys.exit(0)

    def _is_admin(self, user_id: str) -> bool:
        if user_id == "2361035324":
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
                    return
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
                return
            log.error("base64 发送图片失败: HTTP %s, body: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.error("发送群图片失败 (group %s): %s", group_id, exc)

    async def send_group_result(self, group_id: int, user_id: str, text: str, image_path: str | Path) -> None:
        """模拟完成后：发送图文并茂的卡片消息。"""
        img_p = Path(image_path).resolve()
        raw_path = str(img_p)
        file_uri = f"file:///{img_p.as_posix()}"
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
                    return
            except Exception as exc:
                log.warning("合并发送图文异常 (%s): %s", fmt, exc)

        # 若合并发送因协议超时拦截，退回分开发送
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
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("file")
        return None

    # ---------- 队列管理 ----------
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
        await self.tasks.put({"user_id": user_id, "group_id": group_id, "request": request, "runs": runs})

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
                "🀄【MortalSim 雀力推演速查】\n"
                "基础格式：/sim 手牌 d宝牌 [c候选] [局-本场] [座次] [巡目] [点数] [局数]\n\n"
                "• 极简切牌（最常用）：\n"
                "  /sim 123456789m789s12p d8p\n"
                "  💡 省略 c 候选时：自动调用 AI 选取权重前 3 切牌推演；省略局况默认东1，默认 500 局。\n\n"
                "• 自选候选与宣告立直：\n"
                "  /sim 123456789m789s12p d8p c1pr,2p E1-0 1000\n"
                "  💡 候选支持加 r（立直），例：c1pr,2p 或 c=8m,3p\n\n"
                "• 终盘与点数压制（支持多巡与牌河）：\n"
                "  /sim 34567889m233789p d1m S4-0 seat=南 x=7 P180,200,390,230 1000\n"
                "  💡 点数写 P180,200,390,230 或 18k,20k,39k,23k；牌河可省略自动生成\n\n"
                "• 副露与见逃裁定：\n"
                "  /sim 77m4p4056799s112z d5s c=pon>4p,pass seat=东 x=2\n"
                "  💡 支持吃碰/大明杠/荣和/见逃：c=chi:45m>6p / c=ron,pass\n\n"
                "• 指标体系：卡片提供 天凤凤七 (避四) 与 M-League (争一) 双规 EV 对照\n"
                "• 控制指令：/state 查看排队 | /取消 撤回任务",
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
                sys.exit(0)

    # ---------- 任务 Worker ----------
    async def worker(self) -> None:
        while True:
            try:
                item = await self.tasks.get()
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

    async def execute(self, item: dict) -> None:
        request = dict(item["request"])
        request["runs"] = item["runs"]
        request["batch_size"] = 1000
        # 模型映射: parser 内部用不透明别名，此处映射回后端真实模型 ID (用户侧绝不显示模型名)
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

    # 优先绑定当前线程的事件循环，确保 Bot 内部的 asyncio.Queue 归属正确
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = Bot(cfg)

    # 启动后台任务处理 Worker 协程，附带崩溃自动拉起
    worker_task = loop.create_task(bot.worker())

    def _on_worker_done(t):
        if not t.cancelled() and t.exception():
            log.error("worker crashed with exception: %s; restarting worker", t.exception())
            loop.create_task(bot.worker()).add_done_callback(_on_worker_done)

    worker_task.add_done_callback(_on_worker_done)

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

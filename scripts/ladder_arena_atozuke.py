#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atozuke 四卓分层天梯运行器（ONNX 优先 + PyTorch 回退，全 CPU）。

以 Colab cell6_v3.py 为骨架移植：
  * 引擎：复刻 pool_arena.make_engine 的双通路 —— <onnx-dir>/<name>.onnx 存在且 >1MB
    走原生 MortalOnnxEngine（Rust 侧编码观测，绕开 Python/GIL 往返，实测 1.64x）；
    否则回退 PyTorch MortalEngine（cpu / no-amp，含 PolicyNetHead 维度自适应）。
  * 天梯：复用 ladder_engine.py（30 席 Avatar、四卓升降、天凤位），load_engines=False
    跳过其内置 cuda 加载，引擎整体替换为上方双通路产物。
  * 落盘：本地 SQLite（WAL）+ ladder_state.json 断点快照 + backup 目录滚动备份；
    每次快照后自动调用 export_ladder_for_workbench 生成合作仓库 UI 数据三件套。
  * 运行纪律：心跳报活、中断即存档（第一次停止等待在跑桌入库）、seed 自动续接、
    LADDER_STOP 停机文件、绝不覆盖既有数据。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:  # Windows GBK 控制台防御（daemon 重定向日志同样受益）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="Atozuke Tenhou 4-tier ranked ladder (CPU)")
    ap.add_argument("--root", default="C:/arena", help="数据根目录")
    ap.add_argument("--models-dir", default=None, help="*.pth 目录（默认 <root>/models/tsypx）")
    ap.add_argument("--onnx-dir", default=None, help="*.onnx 目录（默认 <root>/models/onnx）")
    ap.add_argument("--mortal-dir", default=None, help="mortal 包目录（默认 <root>/mortal）")
    ap.add_argument("--engine-dir", default=str(HERE), help="ladder_engine.py 所在目录")
    ap.add_argument("--config", default=None, help="models_config.json（默认 <engine-dir>/models_config.json）")
    ap.add_argument("--data-root", default=None, help="workbench UI 数据根（默认 <root>/ladder_ui_data）")
    ap.add_argument("--season-id", default="atozuke-ladder-v1")
    ap.add_argument("--total-seeds", type=int, default=2000)
    ap.add_argument("--batch-seeds", type=int, default=16)
    ap.add_argument("--tables-per-room", type=int, default=2)
    ap.add_argument("--heartbeat", type=int, default=60, help="心跳秒数，0=关闭")
    ap.add_argument("--seed-base", type=int, default=300000)
    ap.add_argument("--fresh", action="store_true", help="忽略段位快照，按配置初始值起跑")
    ap.add_argument("--no-onnx", action="store_true", help="禁用 ONNX 通路（强制 PyTorch）")
    ap.add_argument("--smoke", action="store_true", help="冒烟：极小规模跑通全链路")
    ap.add_argument("--log-dir", default=None,
                    help="mjai 牌谱落盘目录（默认 <root>/ladder_logs）")
    ap.add_argument("--no-dump-logs", action="store_true",
                    help="关闭牌谱落盘（默认开启；落盘后可对全量语料统一重算统计）")
    ap.add_argument("--log-sample-every", type=int, default=1,
                    help="牌谱采样率：1=全量落盘，N=每 N 局落一局（磁盘紧张时用）")
    a = ap.parse_args()

    if a.smoke:
        a.total_seeds, a.batch_seeds, a.tables_per_room, a.heartbeat = 2, 2, 1, 0

    root = Path(a.root)
    models_dir = Path(a.models_dir) if a.models_dir else root / "models" / "tsypx"
    onnx_dir = Path(a.onnx_dir) if a.onnx_dir else root / "models" / "onnx"
    mortal_dir = Path(a.mortal_dir) if a.mortal_dir else root / "mortal"
    engine_dir = Path(a.engine_dir)
    config_path = Path(a.config) if a.config else engine_dir / "models_config.json"
    data_root = Path(a.data_root) if a.data_root else root / "ladder_ui_data"
    local_db = root / "ladder_results.db"
    state_path = root / "ladder_state.json"
    backup_dir = root / "backup_ladder"
    log_dir = Path(a.log_dir) if a.log_dir else root / "ladder_logs"
    dump_logs = not a.no_dump_logs
    log_sample_every = max(1, a.log_sample_every)
    stop_file = root / "LADDER_STOP"

    # ---- 环境引导（复刻 pool_arena.py 生产配置）----
    if "ORT_DYLIB_PATH" not in os.environ:
        ort = root / "onnxruntime.dll"
        if ort.is_file():
            os.environ["ORT_DYLIB_PATH"] = str(ort)
    os.environ.setdefault("RAYON_NUM_THREADS", "2")
    for p in (str(root), str(mortal_dir), str(root / "pyd_native"), str(engine_dir)):
        if p and Path(p).is_dir() and p not in sys.path:
            sys.path.insert(0, p)

    import torch  # noqa: E402
    import libriichi  # noqa: E402
    from ladder_engine import TenhouRankedLadderArena, PolicyNetHead  # noqa: E402
    from model import Brain, DQN  # noqa: E402
    from engine import MortalEngine  # noqa: E402

    sys.path.insert(0, str(engine_dir))
    import export_ladder_for_workbench as xport  # noqa: E402

    has_onnx_engine = hasattr(libriichi.arena, "MortalOnnxEngine")
    use_onnx = (not a.no_onnx) and has_onnx_engine
    onnx_intra = int(os.environ.get("ARENA_ONNX_THREADS", "2"))
    torch_threads = int(os.environ.get("LADDER_TORCH_THREADS", "3"))
    torch.set_num_threads(torch_threads)

    # pth / onnx 的候选文件名（本地与远端历史命名不同，谁存在用谁）
    PTH_ALIASES = {"ext_mortal": ["2024v4bestmini", "ext_mortal"],
                   "distill_41b_infer": ["distill_41b_infer", "distill_41b"]}
    ONNX_ALIASES = {"distill_41b_infer": ["41b_infer", "distill_41b_infer"],
                    "ext_mortal": ["ext_mortal", "2024v4bestmini"]}

    onnx_broken = set()

    def _first_file(directory: Path, mid: str, aliases: dict, ext: str):
        for name in aliases.get(mid, [mid]) + [mid]:
            cand = directory / (name + ext)
            if cand.is_file():
                return cand
        return None

    def build_engine(mid: str):
        """ONNX 优先；缺 onnx 或 ONNX 构建失败时回退 PyTorch（policy_net 头走维度自适应）。

        ONNX 构建三级降级：带 name 关键字 → name 位置传参 → 抛回 fallback。
        （远端 pyd_native 为带 name 的新版；旧版 pyd 无 name 参数。）
        """
        onnx_path = _first_file(onnx_dir, mid, ONNX_ALIASES, ".onnx")
        if (use_onnx and mid not in onnx_broken
                and onnx_path is not None and onnx_path.stat().st_size > 1_000_000):
            for call in (
                lambda: libriichi.arena.MortalOnnxEngine(str(onnx_path), 0, False,
                                                         onnx_intra, name=mid),
                lambda: libriichi.arena.MortalOnnxEngine(str(onnx_path), 0, False,
                                                         onnx_intra, mid),
            ):
                try:
                    return call()
                except TypeError as e:
                    last_err = e
                except Exception as e:
                    onnx_broken.add(mid)
                    print(f"   [warn] {mid} ONNX 引擎构建失败，回退 PyTorch: "
                          f"{type(e).__name__}: {str(e)[:100]}")
                    break
            else:
                onnx_broken.add(mid)
                print(f"   [warn] {mid} ONNX 引擎签名不兼容（{last_err}），回退 PyTorch")
        pth = _first_file(models_dir, mid, PTH_ALIASES, ".pth")
        if pth is None:
            raise FileNotFoundError(
                f"模型缺失且无可用 ONNX: {mid} (pth 目录 {models_dir}, onnx 目录 {onnx_dir})")
        torch.set_num_threads(torch_threads)
        st = torch.load(str(pth), map_location="cpu", weights_only=False)
        cfg = st.get("config", {}) or {}
        ver = cfg.get("control", {}).get("version", 4)
        ch = cfg.get("resnet", {}).get("conv_channels", 192)
        blk = cfg.get("resnet", {}).get("num_blocks", 40)
        brain = Brain(version=ver, conv_channels=ch, num_blocks=blk).eval()
        brain.load_state_dict(st.get("mortal") or st.get("brain"))
        if "policy_net" in st or "policy" in st:
            dqn = PolicyNetHead(st.get("policy_net") or st.get("policy"))
        else:
            dqn = DQN(version=ver)
            dqn.load_state_dict(st["current_dqn"])
        return MortalEngine(brain, dqn, is_oracle=False, version=ver,
                            device=torch.device("cpu"), enable_amp=False, name=mid)

    # ---- 安全初始化：绝不覆盖既有数据 ----
    def row_count(path: Path) -> int:
        if not path.is_file():
            return -1
        try:
            con = sqlite3.connect(str(path), timeout=30)
            try:
                return con.execute("SELECT COUNT(*) FROM ladder_games").fetchone()[0]
            finally:
                con.close()
        except Exception:
            return -1

    root.mkdir(parents=True, exist_ok=True)

    # ---- 单实例锁 ----
    # 计划任务 + 手动 /Run 会拉起多个 guardian，它们的"是否已有运行器"检查有竞态：
    # 若运行器恰好挂掉、两个 guardian 同时在醒来窗口检查，就会并发拉起两个运行器，
    # 用相同 seed 重复对局并重复结算，污染数据库。锁放在运行器自身最可靠——
    # 进程退出（含崩溃）时由操作系统释放，不会留下需要人工清理的僵尸锁。
    import msvcrt
    _lock_path = root / "ladder_runner.lock"
    _lock_fh = open(_lock_path, "w")
    try:
        msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print(f"[fatal] 已有天梯运行器在运行（{_lock_path} 被占用），本实例退出。"
              "若确认无运行器，删除该文件后重试。")
        return 1
    print(f"[init] 已获取单实例锁 {_lock_path}")

    print(f"[init] DB {local_db} 现有 {row_count(local_db)} 行")
    print(f"[init] 牌谱落盘: {'开启 -> ' + str(log_dir) if dump_logs else '关闭'}"
          + (f"（采样 1/{log_sample_every}）" if dump_logs and log_sample_every > 1 else ""))
    print(f"[init] 引擎通路: {'ONNX优先' if use_onnx else 'PyTorch'} "
          f"(onnx_dir={onnx_dir}, intra={onnx_intra}, torch_threads={torch_threads})")

    arena = TenhouRankedLadderArena(
        config_path=str(config_path),
        models_dir=str(models_dir),
        db_path=str(local_db),
        device="cpu",
        load_engines=False,           # 引擎由下方双通路构建
    )

    # 旧库迁移：补簿记列（新库建表已含；ALTER 失败=列已存在，忽略）
    with sqlite3.connect(str(local_db), timeout=30) as c:
        for ddl in ("ALTER TABLE ladder_games ADD COLUMN pt_before INTEGER",
                    "ALTER TABLE ladder_games ADD COLUMN pt_after INTEGER",
                    "ALTER TABLE ladder_games ADD COLUMN dan_before INTEGER",
                    "ALTER TABLE ladder_games ADD COLUMN dan_after INTEGER",
                    "ALTER TABLE ladder_games ADD COLUMN rating_before REAL",
                    "ALTER TABLE ladder_games ADD COLUMN rating_after REAL",
                    "ALTER TABLE ladder_games ADD COLUMN table_avg_r REAL"):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.commit()

    # 双通路构建引擎
    print(f"[init] 构建 {len(arena.physical_models)} 款物理引擎 ...")
    t_eng = time.time()
    for mid in arena.physical_models:
        eng = build_engine(mid)
        kind = type(eng).__module__.split(".")[-1] + "." + type(eng).__name__
        arena.model_engines[mid] = eng
        print(f"   [ok] {mid:<26} -> {kind}")
    print(f"[init] 引擎构建完成（{time.time()-t_eng:.1f}s）")

    # ---- 逐局统计累加器（和/铳/副露/立直），跨重启持久化于 player_stats 表 ----
    stats_acc = {}

    def load_stats():
        try:
            with sqlite3.connect(str(local_db), timeout=30) as c:
                c.execute("CREATE TABLE IF NOT EXISTS player_stats ("
                          "avatar_id TEXT PRIMARY KEY, games INT, rounds INT, agari INT, "
                          "houjuu INT, fuuro INT, fuuro_num INT, riichi INT)")
                for aid, g, rd, ag, hj, fu, fn_, rc in c.execute(
                        "SELECT avatar_id, games, rounds, agari, houjuu, fuuro, "
                        "fuuro_num, riichi FROM player_stats"):
                    stats_acc[aid] = {"games": g, "rounds": rd, "agari": ag,
                                      "houjuu": hj, "fuuro": fu, "fuuro_num": fn_,
                                      "riichi": rc}
                print(f"[init] 已加载 {len(stats_acc)} 席历史统计")
        except Exception:
            pass

    def flush_stats():
        try:
            with sqlite3.connect(str(local_db), timeout=30) as c:
                c.execute("CREATE TABLE IF NOT EXISTS player_stats ("
                          "avatar_id TEXT PRIMARY KEY, games INT, rounds INT, agari INT, "
                          "houjuu INT, fuuro INT, fuuro_num INT, riichi INT)")
                c.executemany(
                    "INSERT OR REPLACE INTO player_stats VALUES (?,?,?,?,?,?,?,?)",
                    [(aid, v["games"], v["rounds"], v["agari"], v["houjuu"],
                      v["fuuro"], v["fuuro_num"], v["riichi"])
                     for aid, v in stats_acc.items()])
                c.commit()
            return True
        except Exception as e:
            print(f"   [warn] 统计落盘失败: {type(e).__name__}: {str(e)[:90]}")
            return False

    load_stats()

    # ---- 断点续跑 ----
    _STATE_FIELDS = ("dan", "pt", "rating", "games", "r1", "r2", "r3", "r4",
                     "fly_count", "total_score", "peak_dan", "peak_rating",
                     "is_tenhou", "reset_count")

    def save_state() -> bool:
        data = {"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "players": {aid: {f: getattr(p, f) for f in _STATE_FIELDS if hasattr(p, f)}
                            for aid, p in arena.players.items()}}
        tmp = str(state_path) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, state_path)
            return True
        except Exception as e:
            print(f"   [warn] 状态快照失败: {type(e).__name__}: {str(e)[:90]}")
            return False

    def load_state() -> bool:
        if not state_path.is_file():
            return False
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"   [warn] 状态快照读取失败，按配置初始值起跑: {type(e).__name__}")
            return False
        n = 0
        for aid, fields in data.get("players", {}).items():
            p = arena.players.get(aid)
            if p is None:
                continue
            for k, v in fields.items():
                if hasattr(p, k):
                    setattr(p, k, v)
            n += 1
        print(f"[resume] 已恢复 {n} 席账号状态（快照于 {data.get('saved_at')}）")
        return n > 0

    def backup_db() -> bool:
        """滚动本地备份（保留最近 5 份）。"""
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            dst = backup_dir / "ladder_results_latest.db"
            con_src = sqlite3.connect(str(local_db), timeout=30)
            con_dst = sqlite3.connect(str(dst), timeout=60)
            try:
                con_src.backup(con_dst)
            finally:
                con_src.close()
                con_dst.close()
            olds = sorted(backup_dir.glob("ladder_results_b*.db"))
            while len(olds) >= 5:
                olds.pop(0).unlink(missing_ok=True)
            return True
        except Exception as e:
            print(f"   [warn] 备份失败（数据完好）: {type(e).__name__}: {str(e)[:90]}")
            return False

    def export_ui() -> bool:
        """只刷新 UI 三件套（每批一次）。

        成本 O(库行数)：实测 0.18s/万行，30 万行约 5.3s。推理跑在 Rust 工作线程里
        且已释放 GIL，导出期间对局照常推进；本函数只推迟「下一批的提交时机」，
        占 55 分钟批墙钟 <0.2%，对吞吐无可测影响。
        """
        try:
            info = xport.export_all(db_path=local_db, state_path=state_path,
                                    config_path=config_path, data_root=data_root,
                                    season_id=a.season_id)
            print(f"   [ui] 三件套已刷新（{info['accounts']}席/{info['games']}局，"
                  f"ledger {info['ledger_rows']}行）", flush=True)
            return True
        except Exception as e:
            print(f"   [warn] UI 数据导出失败（不影响天梯）: {type(e).__name__}: {str(e)[:120]}")
            return False

    def snapshot_all() -> bool:
        """全库备份 + 断点状态快照（每 5 批一次）。

        备份是整库复制，成本随库规模线性增长（30 万行约 1.2s），且与崩溃恢复
        相关，因此不与 UI 导出同频——UI 要新鲜，备份不必。
        """
        ok_db = backup_db()
        ok_st = save_state()
        if ok_db and ok_st:
            print("   [snapshot] 库与断点状态已备份", flush=True)
        return ok_db and ok_st

    def replay_from_db() -> bool:
        """无状态快照时，从 DB 簿记列回放各账号真实段位/PT/R 与战绩计数。

        DB 是事实源：每局都有 dan/pt/rating 的 before/after。重启后据此恢复，
        段位进度不再因进程重启而归零。
        """
        try:
            with sqlite3.connect(str(local_db), timeout=30) as c:
                cols = {r[1] for r in c.execute("PRAGMA table_info(ladder_games)")}
                if "dan_after" not in cols:
                    return False
                rows = c.execute("""
                    SELECT avatar_id, dan_after, pt_after, rating_after
                    FROM ladder_games g
                    WHERE match_id IN (SELECT MAX(match_id) FROM ladder_games
                                       GROUP BY avatar_id)
                      AND dan_after IS NOT NULL
                """).fetchall()
                if not rows:
                    return False
                n = 0
                for aid, dan, pt, r in rows:
                    p = arena.players.get(aid)
                    if p is None:
                        continue
                    p.dan, p.pt, p.rating = int(dan), int(pt), float(r)
                    p.is_tenhou = p.dan >= 11
                    if p.is_tenhou:
                        p.pt = 4000
                    p.peak_dan = max(p.peak_dan, p.dan)
                    p.peak_rating = max(p.peak_rating, p.rating)
                    n += 1
                for aid, games, r1, r2, r3, r4, fly, score in c.execute("""
                    SELECT avatar_id, COUNT(*), SUM(rank=1), SUM(rank=2), SUM(rank=3),
                           SUM(rank=4), SUM(score<0), SUM(score)
                    FROM ladder_games GROUP BY avatar_id
                """):
                    p = arena.players.get(aid)
                    if p is None:
                        continue
                    p.games, p.r1, p.r2, p.r3, p.r4 = games, r1 or 0, r2 or 0, r3 or 0, r4 or 0
                    p.fly_count, p.total_score = fly or 0, score or 0
                print(f"[replay] 已从 DB 回放 {n} 席账号状态（段位/PT/R + 战绩计数）")
                return n > 0
        except Exception as e:
            print(f"   [warn] DB 回放失败: {type(e).__name__}: {str(e)[:100]}")
            return False

    resumed = (not a.fresh) and load_state()
    if not resumed:
        resumed = replay_from_db()
        if resumed:
            save_state()
    if not resumed:
        print("[init] 段位榜按配置初始值起跑")

    # ---- seed 自动续接 ----
    with sqlite3.connect(str(local_db), timeout=30) as c:
        mx = c.execute("SELECT COALESCE(MAX(seed_idx)+1, 0) FROM ladder_games "
                       "WHERE seed_idx >= ?", (a.seed_base,)).fetchone()[0]
    seed_cursor = max(a.seed_base, int(mx or 0))
    print(f"[init] seed 从 {seed_cursor} 起跑（自动避开已入库区间）")

    # ---- 组桌与对局 ----
    fourp = libriichi.arena.FourPlayer(disable_progress_bar=True)
    ROOM_CN = {"houou": "凤凰", "tokujou": "特上", "joukyuu": "上级", "ippan": "一般"}

    def pick_tables(pool, n_tables):
        """只用【本卓合格池】内的账号组桌；池不足以组成 n_tables 张桌时按池大小缩减。

        绝不允许跨卓补人：那样会让低段位账号进高段位桌，并按高段位 PT 结算
        （实测出现过 4 段打凤凰桌、3 段打特上桌，扭曲了阶梯本身）。
        池内凑不满 4 人时宁可少开桌——账号空闲一轮，但阶梯保持干净。
        """
        pool = list(pool)
        random.shuffle(pool)
        n_tables = min(n_tables, len(pool) // 4)
        used_across, used_avatars, tables = set(), set(), []
        for _ in range(n_tables):
            picked, picked_models = [], set()
            for strict in (True, False):
                for aid in pool:
                    if aid in picked or aid in used_avatars:
                        continue
                    mid = arena.players[aid].model_id
                    if mid in picked_models or (strict and mid in used_across):
                        continue
                    picked.append(aid)
                    picked_models.add(mid)
                    if len(picked) == 4:
                        break
                if len(picked) == 4:
                    break
            if len(picked) < 4:
                # 放宽"同桌模型互不相同"，仍只在池内取
                for aid in pool:
                    if len(picked) == 4:
                        break
                    if aid in picked or aid in used_avatars:
                        continue
                    picked.append(aid)
            if len(picked) < 4:
                break          # 池内已无可用账号：停止组桌，绝不外借
            tables.append(picked)
            used_avatars |= set(picked)
            used_across |= {arena.players[x].model_id for x in picked}
        return tables

    def run_one(table_avatars, room, seed_start, batch_seeds):
        # 每批为本桌新建独占引擎实例：同模型共享时 Mutex<Session> 会串行化
        # 多桌推理，独占会话后各桌推理完全并行（构建 ~5s/批，相对批周期可忽略）。
        engines = [build_engine(arena.players[x].model_id) for x in table_avatars]
        avg_r = sum(arena.players[x].rating for x in table_avatars) / 4.0
        # 必须用 with_logs 变体：settle 需要末位的 mjai 日志串做逐局统计与牌谱落盘
        rows = fourp.py_vs_py_detailed_with_logs(*engines, (seed_start, 0), batch_seeds)
        if rows and len(rows[0]) != 6:
            raise RuntimeError(
                f"py_vs_py_detailed_with_logs 返回 {len(rows[0])} 元组，期望 6 "
                f"（疑似 pyd 版本不匹配：请确认部署的是带 with_logs 的构建）")
        return room, table_avatars, avg_r, rows

    import gzip

    def dump_game_log(log_str: str, seed: int, key: int, split: int,
                      table_avatars: list, n_hanchan_seen: int) -> bool:
        """落盘一局 mjai 牌谱（gzip jsonl）。

        关键：把 start_game.names 改写为 avatar_id。引擎的 name 传的是 model_id，
        同模型的多个 avatar 同桌时日志内名字会撞车，导致 Stat.from_dir 按名字
        统计时无法区分。改写后整份语料可按 avatar 统一重算任意指标。
        座位映射与结算一致：seat s 的模型来自 table[(s - split) % 4]。
        """
        if not dump_logs:
            return False
        if log_sample_every > 1 and (n_hanchan_seen % log_sample_every) != 0:
            return False
        try:
            day = time.strftime("%Y%m%d")
            d = log_dir / day
            d.mkdir(parents=True, exist_ok=True)
            lines = log_str.split(chr(10))
            if lines and lines[0].startswith("{"):
                import json as _json
                head = _json.loads(lines[0])
                if head.get("type") == "start_game":
                    head["names"] = [table_avatars[(s - split) % 4] for s in range(4)]
                    lines[0] = _json.dumps(head, ensure_ascii=False)
            with gzip.open(d / f"{seed}_{key}_{split}.json.gz", "wt",
                           encoding="utf-8", compresslevel=1) as f:
                f.write(chr(10).join(lines))
            return True
        except Exception as e:
            print(f"   [warn] 牌谱落盘失败: {type(e).__name__}: {str(e)[:90]}", flush=True)
            return False

    def settle(fut, submitted_at):
        """结算一桌：先写库（含簿记列），提交成功后更新内存榜。只在主线程调用。"""
        nonlocal done_hanchans, done_tables
        room, table, avg_r, rows = fut.result()
        params, effects = [], []
        for seed, _k, split, ranks, scores, log_str in rows:
            for seat in range(4):
                aid = table[(seat - int(split)) % 4]
                p = arena.players[aid]
                rk = int(ranks[seat]) + 1
                sc = int(scores[seat])
                pt_b, dan_b, r_b = p.pt, p.dan, p.rating
                p.apply_game_result(rk, sc, avg_r, room)
                params.append((room, int(seed), int(split), seat, aid, p.model_id, rk, sc,
                               int(pt_b), int(p.pt), int(dan_b), int(p.dan),
                               float(r_b), float(p.rating), float(avg_r)))
        with sqlite3.connect(str(local_db), timeout=30) as c:
            c.executemany(
                "INSERT INTO ladder_games (room, seed_idx, split, seat, avatar_id, model_id, "
                "rank, score, pt_before, pt_after, dan_before, dan_after, "
                "rating_before, rating_after, table_avg_r) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                params)
        # 逐局 mjai 统计：和/铳/副露/立直（per-round 口径，与 libriichi.stat 一致）
        for row in rows:
            _seed, _k, split, _ranks, _scores, log_str = row
            for seat in range(4):
                aid = table[(seat - int(split)) % 4]
                try:
                    st = libriichi.stat.Stat.from_log(log_str, seat)
                    acc = stats_acc.setdefault(aid, {"games": 0, "rounds": 0,
                                                     "agari": 0, "houjuu": 0,
                                                     "fuuro": 0, "fuuro_num": 0,
                                                     "riichi": 0})
                    acc["games"] += 1
                    acc["rounds"] += st.round
                    acc["agari"] += st.agari
                    acc["houjuu"] += st.houjuu
                    acc["fuuro"] += st.fuuro
                    acc["fuuro_num"] += st.fuuro_num
                    acc["riichi"] += st.riichi
                except Exception:
                    continue

        # 牌谱落盘（全量，供后续统一重算统计）
        if dump_logs:
            n_logged = 0
            for i, row in enumerate(rows):
                seed, key, split, _ranks, _scores, log_str = row
                # 采样计数用全局半庄序（单调），保证 1/N 均匀覆盖
                if dump_game_log(log_str, int(seed), int(key), int(split),
                                 table, done_hanchans + i + 1):
                    n_logged += 1
            if n_logged:
                print(f"   [log] 本桌落盘 {n_logged} 局牌谱 -> {log_dir}", flush=True)

        done_hanchans += len(rows)
        done_tables += 1
        print(f"[桌完] {ROOM_CN.get(room, room)} | "
              f"{' '.join(arena.players[x].display_name for x in table)} | "
              f"本桌 {len(rows)} 半庄 {time.time()-submitted_at:.1f}s | "
              f"累计 {done_hanchans} 半庄 {done_hanchans/(time.time()-t0)*60:.0f} 半庄/分", flush=True)

    workers = max(4, a.tables_per_room * 3 + 2)
    t0 = time.time()
    done_hanchans = 0
    done_tables = 0
    in_flight = 0
    batch_no = 0

    print()
    print(f"=== 启动：BATCH_SEEDS={a.batch_seeds}（每桌 {a.batch_seeds*4} 副牌）  "
          f"{a.tables_per_room}桌/卓别 × {workers} 线程  "
          f"单批上限 ≈ {a.tables_per_room*3*a.batch_seeds*4} 半庄 ===")
    print("=== 首批 [桌完] 视 CPU 而定；此间以 [心跳] 为准 ===")
    print()

    stop_hb = threading.Event()

    def heartbeat():
        while not stop_hb.wait(a.heartbeat):
            el = (time.time() - t0) / 60
            print(f"[心跳] {el:.1f} 分钟 | 已完成 {done_tables} 桌 / {done_hanchans} 半庄 | "
                  f"在跑 {in_flight} 桌", flush=True)

    if a.heartbeat > 0:
        threading.Thread(target=heartbeat, daemon=True).start()

    pool_ex = ThreadPoolExecutor(max_workers=workers)
    hard_abandon = False
    try:
        for _batch_i in range(0, a.total_seeds, a.batch_seeds):
            batch_no += 1
            if stop_file.is_file():
                print(f"[stop] 检测到停机文件 {stop_file}，本批结束后优雅退出")
                stop_file.unlink(missing_ok=True)
                break

            room_pools = {"houou": [], "tokujou": [], "joukyuu": [], "ippan": []}
            for aid, p in arena.players.items():
                room_pools[p.get_room()].append(aid)
            active_rooms = [r for r in ("houou", "tokujou", "joukyuu")
                            if len(room_pools[r]) >= 4]

            futures = {}
            for room in active_rooms:
                # 只用本卓合格池（active_rooms 已保证 >=4 席）。
                # 历史上这里有一段"池不足就跨卓借人"的逻辑，语义正是我们不要的：
                # 会让低段位账号进高段位桌并按高段位 PT 结算。已移除。
                avail = list(room_pools[room])
                for table in pick_tables(avail, a.tables_per_room):
                    futures[pool_ex.submit(run_one, table, room, seed_cursor,
                                           a.batch_seeds)] = time.time()
                    seed_cursor += a.batch_seeds

            if not futures:
                print(f"[warn] Batch {batch_no} 无可开桌（活跃池不足 4 席），跳过")
                continue

            in_flight = len(futures)
            processed = set()
            try:
                for fut in as_completed(futures):
                    settle(fut, futures[fut])
                    processed.add(fut)
                    in_flight -= 1
            except KeyboardInterrupt:
                remaining = [f for f in futures if f not in processed]
                print(f"\n[中断] 停止接受新批次。等待在跑的 {len(remaining)} 桌完成并入库...", flush=True)
                for fut in remaining:
                    try:
                        settle(fut, futures[fut])
                    except KeyboardInterrupt:
                        hard_abandon = True
                        print("[中断] 再次中断：放弃剩余在跑结果。")
                        break
                if not hard_abandon:
                    print("[中断] 在跑结果已全部入库。")
                break

            print(f"--- Batch {batch_no} 完 | 池: 凤{len(room_pools['houou'])} "
                  f"特{len(room_pools['tokujou'])} 上{len(room_pools['joukyuu'])} ---", flush=True)
            # UI 三件套每批刷新（约 55 分钟一次；实测占批墙钟 <0.2%）
            flush_stats()
            export_ui()
            # 全库备份 + 断点状态每 5 批一次（成本随库规模增长，不需要同频）
            if batch_no == 1 or batch_no % 5 == 0:
                snapshot_all()
            if batch_no % 10 == 0:
                arena.print_standings()
    finally:
        stop_hb.set()
        if hard_abandon:
            pool_ex.shutdown(wait=False, cancel_futures=True)
            print("\n[中断] 被放弃的桌仍在后台静默运行，结果不会入库。建议重启进程清场。")
        else:
            print("\n[收尾] 确认所有桌已结束...")
            pool_ex.shutdown(wait=True)
            flush_stats()
            export_ui()
            if snapshot_all():
                print("[收尾] 库/状态/UI 三件套均已存档，下次启动自动续跑。")
    el = time.time() - t0
    print(f"=== 本次入库 {done_hanchans} 半庄 / {done_tables} 桌，"
          f"用时 {el/60:.1f} 分钟，平均 {done_hanchans/el*60:.0f} 半庄/分 ===")
    arena.print_standings()
    return 0


if __name__ == "__main__":
    sys.exit(main())

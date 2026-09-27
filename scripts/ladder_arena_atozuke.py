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
    print(f"[init] DB {local_db} 现有 {row_count(local_db)} 行")
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

    def snapshot_all() -> bool:
        ok_db = backup_db()
        ok_st = save_state()
        try:
            info = xport.export_all(db_path=local_db, state_path=state_path,
                                    config_path=config_path, data_root=data_root,
                                    season_id=a.season_id)
            print(f"   [snapshot] 库/状态已备份；UI 三件套已刷新 "
                  f"({info['accounts']}席/{info['games']}局, ledger {info['ledger_rows']}行)")
            return ok_db and ok_st
        except Exception as e:
            print(f"   [warn] UI 数据导出失败（不影响天梯）: {type(e).__name__}: {str(e)[:120]}")
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
        # 席位公平性优先：同一 avatar 同批只上一张桌（跨桌按 avatar 去重），
        # 未上过桌的优先补位，池耗尽才复用。同桌模型互不相同保证对手多样性。
        pool = list(pool)
        random.shuffle(pool)
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
                for aid in pool:
                    if len(picked) == 4:
                        break
                    if aid in picked or aid in used_avatars:
                        continue
                    picked.append(aid)
            all_aids = list(arena.players.keys())
            while len(picked) < 4:
                c = random.choice(all_aids)
                if c not in picked:
                    picked.append(c)
            tables.append(picked)
            used_avatars |= set(picked)
            used_across |= {arena.players[x].model_id for x in picked}
        return tables

    def run_one(table_avatars, room, seed_start, batch_seeds):
        # 每批为本桌新建独占引擎实例：同模型共享时 Mutex<Session> 会串行化
        # 多桌推理，独占会话后各桌推理完全并行（构建 ~5s/批，相对批周期可忽略）。
        engines = [build_engine(arena.players[x].model_id) for x in table_avatars]
        avg_r = sum(arena.players[x].rating for x in table_avatars) / 4.0
        rows = fourp.py_vs_py_detailed(*engines, (seed_start, 0), batch_seeds)
        return room, table_avatars, avg_r, rows

    def settle(fut, submitted_at):
        """结算一桌：先写库（含簿记列），提交成功后更新内存榜。只在主线程调用。"""
        nonlocal done_hanchans, done_tables
        room, table, avg_r, rows = fut.result()
        params, effects = [], []
        for seed, _k, split, ranks, scores in rows:
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
                avail = list(room_pools[room])
                if len(avail) < 4:
                    for other in ("tokujou", "houou", "joukyuu"):
                        if other != room:
                            avail += room_pools[other]
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
            if batch_no == 1 or batch_no % 5 == 0:
                if snapshot_all():
                    pass
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
            if snapshot_all():
                print("[收尾] 库/状态/UI 三件套均已存档，下次启动自动续跑。")
    el = time.time() - t0
    print(f"=== 本次入库 {done_hanchans} 半庄 / {done_tables} 桌，"
          f"用时 {el/60:.1f} 分钟，平均 {done_hanchans/el*60:.0f} 半庄/分 ===")
    arena.print_standings()
    return 0


if __name__ == "__main__":
    sys.exit(main())

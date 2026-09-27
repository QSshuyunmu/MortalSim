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
    from ladder_engine import (TenhouRankedLadderArena, PolicyNetHead,  # noqa: E402
                           PlayerState, DAN_NAMES)
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

    # ---- --fresh：先归档再重开，绝不原地清空 ----
    # 历史教训：--fresh 原本只跳过状态快照却不清库，于是拿配置初值往旧库里续写，
    # 把已累积的段位/PT/R 整段抹平（审计在库中查到 34 处这样的状态链断裂）。
    if a.fresh and (local_db.is_file() or state_path.is_file()):
        arch = root / "archive" / (time.strftime("%Y%m%d_%H%M%S") + "_fresh")
        arch.mkdir(parents=True, exist_ok=True)
        moved = []
        for p in (local_db, state_path, Path(str(local_db) + "-wal"),
                  Path(str(local_db) + "-shm")):
            if p.is_file():
                p.replace(arch / p.name)
                moved.append(p.name)
        print(f"[fresh] 已归档 {len(moved)} 个旧文件 -> {arch}")

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
        # 赛季名册：记录本赛季出现过的每一个账号（含回收后新加的世代账号）。
        # 账号被回收后数据留库、但不参与组桌，因此必须有张表记住"谁在场、谁离场"，
        # 否则重启后这些世代账号会凭空消失。
        c.execute("CREATE TABLE IF NOT EXISTS ladder_roster ("
                  "avatar_id TEXT PRIMARY KEY, model_id TEXT NOT NULL,"
                  "display_name TEXT, role TEXT, role_desc TEXT,"
                  "init_dan INT, init_pt INT, init_rating REAL,"
                  "gen INT DEFAULT 1, parent_id TEXT,"
                  "spawned_seed INT, spawned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                  "retired_seed INT, retired_at TIMESTAMP)")
        c.commit()

    # ---- 名册：把配置里的初始账号登记入库（幂等）----
    def roster_register(aid, model_id, display_name, role, role_desc,
                        init_dan, init_pt, init_rating, gen=1, parent_id=None,
                        spawned_seed=None):
        with sqlite3.connect(str(local_db), timeout=30) as c:
            c.execute("INSERT OR IGNORE INTO ladder_roster "
                      "(avatar_id, model_id, display_name, role, role_desc, "
                      "init_dan, init_pt, init_rating, gen, parent_id, spawned_seed) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, model_id, display_name, role, role_desc,
                       int(init_dan), int(init_pt), float(init_rating),
                       int(gen), parent_id, spawned_seed))

    # 世代账号形如 `抽象-1#2`；根账号是 # 之前的部分，用于判断同一血脉
    def _root_id(aid: str) -> str:
        return aid.split("#", 1)[0]

    cfg_avatars = json.loads(config_path.read_text(encoding="utf-8")).get("avatars", [])
    cfg_ids = {x["avatar_id"] for x in cfg_avatars}
    for _a in cfg_avatars:
        roster_register(_a["avatar_id"], _a["model_id"],
                        _a.get("display_name", _a["avatar_id"]),
                        _a.get("role", ""), _a.get("role_desc", ""),
                        _a.get("init_dan", 1), _a.get("init_pt", 200 * _a.get("init_dan", 1)),
                        _a.get("init_rating", 1500.0))

    with sqlite3.connect(str(local_db), timeout=30) as c:
        _roster = c.execute(
            "SELECT avatar_id, model_id, display_name, role, role_desc, "
            "init_dan, init_pt, init_rating, retired_seed FROM ladder_roster").fetchall()
    _added = 0
    _retired_ids = set()
    for _aid, _mid, _dn, _role, _rd, _idan, _ipt, _iR, _rseed in _roster:
        if _rseed is not None:
            _retired_ids.add(_aid)
            continue
        if _aid in cfg_ids or _aid in arena.players:
            continue
        if _mid not in arena.physical_models:
            print(f"   [warn] 名册里的 {_aid} 用了未知模型 {_mid}，跳过")
            continue
        arena.players[_aid] = PlayerState(
            avatar_id=_aid, model_id=_mid, display_name=_dn or _aid,
            role=_role or "tokujou_native", role_desc=_rd or "",
            dan=int(_idan), pt=int(_ipt), rating=float(_iR))
        _added += 1
    _n_retired = len(_retired_ids)
    print(f"[init] 名册 {len(_roster)} 席（配置 {len(cfg_avatars)} + 装回世代 {_added}）"
          + (f"，其中已回收离场 {_n_retired} 席" if _n_retired else ""))

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
                     "is_tenhou", "reset_count", "retired")

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

    def recycle_stuck(at_seed: int) -> list:
        """回收掉进上级卓的账号，换同模型新账号从四段水面重新入场。

        上级卓的合格池（dan<=3 或 R<1800）永远凑不满 4 人——池里只可能装着
        "刚从特上掉下来"的账号，而它们掉下去就再也开不了桌，等于永久冻结
        （实测已冻 368 个半庄位）。真实天凤靠庞大人口自然消化这一层，
        30 席规模下做不到，所以改成回收：

          旧账号：停止出场，段位/PT/R/战绩全部原样留库（不虚构、不篡改）
          新账号：同模型，从四段水面（四段 / 800pt / R1800）重新入场，席位不空

        这样阶梯不会因为"最底层开不了桌"而丢席，历史也不会被污染——
        旧账号的战绩仍是它真实打出来的，新账号另起一条干净曲线。
        """
        out = []
        for aid, p in list(arena.players.items()):
            if p.retired or p.is_tenhou or p.get_room() != "joukyuu":
                continue
            root = _root_id(aid)
            kin = {x for x in arena.players if _root_id(x) == root}
            new_id = next((f"{root}#{g}" for g in range(2, 500)
                           if f"{root}#{g}" not in kin), None)
            if new_id is None:
                print(f"   [warn] {aid} 血脉世代号已用尽，本批不补席", flush=True)
                continue
            gen = int(new_id.rsplit("#", 1)[1])
            old = (int(p.dan), int(p.pt), float(p.rating), int(p.games))
            p.retired = True
            with sqlite3.connect(str(local_db), timeout=30) as c:
                c.execute("UPDATE ladder_roster SET retired_seed=?, "
                          "retired_at=CURRENT_TIMESTAMP WHERE avatar_id=?",
                          (int(at_seed), aid))
            arena.players[new_id] = PlayerState(
                avatar_id=new_id, model_id=p.model_id, display_name=new_id,
                role=p.role, role_desc=p.role_desc,
                dan=4, pt=800, rating=1800.0,
                floor_dan=p.floor_dan, floor_rating=p.floor_rating)
            roster_register(new_id, p.model_id, new_id, p.role, p.role_desc,
                            4, 800, 1800.0, gen=gen, parent_id=aid,
                            spawned_seed=int(at_seed))
            last_seed[new_id] = -1          # 新席优先上桌
            out.append((aid, old, new_id, p.model_id, gen))
        return out

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

    # 回收标记以名册为准，且在状态恢复之后才施加：状态快照可能早于名册里的
    # 回收记录（进程正好在"写名册"与"写快照"之间崩掉），若先标记就会被
    # load_state 用旧值覆盖回来，让已回收的账号复活。
    for _aid in _retired_ids:
        _p = arena.players.get(_aid)
        if _p is not None and not _p.retired:
            _p.retired = True
    if _retired_ids:
        _revived = [a for a in _retired_ids if not arena.players.get(a, None)]
        print(f"[init] 已按名册标记回收离场 {len(_retired_ids)} 席"
              + (f"（其中 {len(_revived)} 席已不在配置里）" if _revived else ""))
    if not resumed:
        # 安全阀：库中已有历史却恢复不出状态 => 拒绝起跑。
        # seed 游标无论如何都从 DB 续接，所以"恢复失败还照跑"的后果是：
        # 拿配置初值往同一个库续写，把该账号已累积的段位/PT/R 整段抹平。
        # 审计在历史库中查到 34 处这种断裂（涉及 20 席，seed 300032~300576）。
        with sqlite3.connect(str(local_db), timeout=30) as c:
            n_hist = c.execute("SELECT COUNT(*) FROM ladder_games WHERE seed_idx >= ?",
                               (a.seed_base,)).fetchone()[0]
        if n_hist:
            print(f"[fatal] 库中已有 {n_hist} 行历史，但状态快照与 DB 回放都恢复失败。")
            print(f"        继续起跑会用配置初值覆盖已累积的段位/PT/R，故中止。")
            print(f"        处理：修好 {state_path} 后重启；确实要重开请显式加 --fresh（会先归档）。")
            return 1
        print("[init] 段位榜按配置初始值起跑（库中无历史）")

    # ---- seed 自动续接 ----
    with sqlite3.connect(str(local_db), timeout=30) as c:
        mx = c.execute("SELECT COALESCE(MAX(seed_idx)+1, 0) FROM ladder_games "
                       "WHERE seed_idx >= ?", (a.seed_base,)).fetchone()[0]
        # 轮转年龄的基准：每席最后一次上桌的 seed（从 DB 取，重启后不丢）
        last_seed = dict(c.execute(
            "SELECT avatar_id, MAX(seed_idx) FROM ladder_games WHERE seed_idx >= ? "
            "GROUP BY avatar_id", (a.seed_base,)).fetchall())
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

        取人按【轮转年龄】排序而非随机，并且【不做跨桌模型去重】。这两件事
        是同一个问题的两面：跨桌要求"模型互不相同"等于把桌位按模型配额化——
        池内只有 11 款模型而每轮要 12 个座位，于是只有一个分身的模型永远必选，
        分身多的模型互相抢剩下的名额。实测（特上池 21 席开 3 桌）：
          旧：分身数↔上桌率 相关 -0.95，单分身 100%、5 分身 49%，极差 66.7pp
          新：全员 56~62%，极差 13.0pp（理论公平值 = 12 座 / 21 席 = 57%）
        上桌率被分身数左右会直接污染模型间的强弱对比，故必须解耦。
        同桌仍要求模型互不相同（picked_models），保证对手多样性。
        """
        pool = sorted(pool, key=lambda aid: (last_seed.get(aid, -1), random.random()))
        n_tables = min(n_tables, len(pool) // 4)
        used_avatars, tables = set(), []
        for _ in range(n_tables):
            picked, picked_models = [], set()
            for aid in pool:
                if aid in picked or aid in used_avatars:
                    continue
                mid = arena.players[aid].model_id
                if mid in picked_models:
                    continue
                picked.append(aid)
                picked_models.add(mid)
                if len(picked) == 4:
                    break
            if len(picked) < 4:
                # 池内不足 4 款模型时放宽"同桌模型互不相同"，仍只在池内取
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
        # 轮转年龄：本桌四席刚刚上过桌，下一批让位给更久没打的席位
        _latest = max(int(r[0]) for r in rows)
        for aid in table:
            last_seed[aid] = _latest
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

            # 上级卓回收：掉进去的账号开不了桌，当场换同模型新账号从四段水面续位
            recy = recycle_stuck(seed_cursor)
            if recy:
                for _aid, _old, _nid, _mid, _gen in recy:
                    print(f"[回收] {_aid}（{_mid}）{DAN_NAMES.get(_old[0], str(_old[0]) + '段')}"
                          f"/{_old[1]}pt/R{_old[2]:.0f}/{_old[3]}半庄 停止出场，"
                          f"换第{_gen}代新席 {_nid} 从四段水面入场", flush=True)
                save_state()

            room_pools = {"houou": [], "tokujou": [], "joukyuu": [], "ippan": []}
            for aid, p in arena.players.items():
                if p.retired:
                    continue
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
            # 状态快照必须与 DB 同频：否则非正常终止（掉电/强杀）时，重启会用
            # 最陈旧的一份快照覆盖内存态，把最多 4 批（64 局）的段位/PT/R 回滚掉。
            # 快照只是 30 席的 JSON，成本可忽略。
            if not save_state():
                print("   [warn] 状态快照失败，重启可能回滚本批", flush=True)
            # 全库备份成本随库规模增长，保持每 5 批一次
            if batch_no == 1 or batch_no % 5 == 0:
                backup_db()
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

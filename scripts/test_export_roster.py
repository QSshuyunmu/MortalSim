# -*- coding: utf-8 -*-
"""合成库验证：世代账号 + 回收标记能否正确进入 UI 三件套。

用一张 mini 库复刻真实 schema，塞进"一代账号已回收、二代账号在场"的情形，
跑真实的 export_all，检查输出。
"""
import json, sqlite3, sys, shutil, tempfile
from pathlib import Path

sys.path.insert(0, "D:/tenhoulib/.diag")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import export_ladder_for_workbench as xport

tmp = Path(tempfile.mkdtemp(prefix="ladder_export_test_"))
db = tmp / "ladder_results.db"
cfg_path = tmp / "models_config.json"
state_path = tmp / "ladder_state.json"
data_root = tmp / "ui"

# ---- 配置：2 款模型 / 2 个初始账号 ----
cfg = {
    "version": "test", "comment": "synthetic",
    "rooms": {
        "houou": {"name": "凤凰卓", "min_dan": 7, "min_rating": 2000.0, "bonus": [90.0, 45.0, 0.0]},
        "tokujou": {"name": "特上卓", "min_dan": 4, "min_rating": 1800.0, "bonus": [75.0, 30.0, 0.0]},
        "joukyuu": {"name": "上级卓", "min_dan": 1, "min_rating": 1600.0, "bonus": [60.0, 15.0, 0.0]},
        "ippan": {"name": "一般卓", "min_dan": 0, "min_rating": 0.0, "bonus": [30.0, 15.0, 0.0]}},
    "physical_models": [
        {"model_id": "chouxiang", "file": "chouxiang.pth", "type": "dqn", "style": "t"},
        {"model_id": "Bin_0910", "file": "Bin_0910.pth", "type": "dqn", "style": "t"}],
    "avatars": [
        {"avatar_id": "抽象-1", "model_id": "chouxiang", "display_name": "抽象-1",
         "role": "tokujou_native", "role_desc": "t", "init_dan": 4, "init_pt": 800,
         "init_rating": 1900.0},
        {"avatar_id": "Bastion", "model_id": "Bin_0910", "display_name": "Bastion",
         "role": "contender", "role_desc": "t", "init_dan": 7, "init_pt": 1400,
         "init_rating": 2100.0}],
}
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

# ---- 库：抽象-1 打了 2 局后掉进上级卓被回收；抽象-1#2 是回收后补的新席 ----
shutil.copy("D:/tenhoulib/.diag/db_audit.db", db)   # 借真实库的建表语句
con = sqlite3.connect(str(db))
con.execute("DELETE FROM ladder_games")
con.execute("DELETE FROM player_stats")
con.execute("CREATE TABLE IF NOT EXISTS ladder_roster ("
            "avatar_id TEXT PRIMARY KEY, model_id TEXT NOT NULL,"
            "display_name TEXT, role TEXT, role_desc TEXT,"
            "init_dan INT, init_pt INT, init_rating REAL, gen INT DEFAULT 1,"
            "parent_id TEXT, spawned_seed INT, spawned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "retired_seed INT, retired_at TIMESTAMP)")
for r in [("抽象-1", "chouxiang", "抽象-1", "tokujou_native", "t", 4, 800, 1900.0, 1, None, 300000, 300900),
          ("Bastion", "Bin_0910", "Bastion", "contender", "t", 7, 1400, 2100.0, 1, None, 300000, None),
          ("抽象-1#2", "chouxiang", "抽象-1#2", "tokujou_native", "t", 4, 800, 1800.0, 2, "抽象-1", 300900, None)]:
    con.execute("INSERT INTO ladder_roster VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?,NULL)", r)
# 抽象-1 的 2 局（最终掉到 3 段 / R1790 → 上级卓 → 会被回收）
for i, (seed, rank, pb, pa, ra, rb) in enumerate([
        (300000, 4, 800, 725, 1900.0, 1874.0),
        (300001, 4, 725, 650, 1874.0, 1848.0)]):
    con.execute("INSERT INTO ladder_games (room, seed_idx, split, seat, avatar_id, model_id,"
                " rank, score, pt_before, pt_after, dan_before, dan_after,"
                " rating_before, rating_after, table_avg_r) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("tokujou", seed, i % 2, 0, "抽象-1", "chouxiang", rank, 5000,
                 pb, pa, 4, 4, ra, rb, 1900.0))
# 抽象-1#2 的 3 局
for i, (seed, rank, pb, pa, ra, rb) in enumerate([
        (300900, 1, 800, 875, 1800.0, 1826.0),
        (300901, 2, 875, 905, 1826.0, 1834.0),
        (300902, 3, 905, 905, 1834.0, 1826.0)]):
    con.execute("INSERT INTO ladder_games (room, seed_idx, split, seat, avatar_id, model_id,"
                " rank, score, pt_before, pt_after, dan_before, dan_after,"
                " rating_before, rating_after, table_avg_r) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("tokujou", seed, i % 2, 0, "抽象-1#2", "chouxiang", rank, 30000,
                 pb, pa, 4, 4, ra, rb, 1900.0))
for r in [("抽象-1", 2, 0, 0, 0, 2, 0, 0), ("抽象-1#2", 3, 1, 1, 1, 0, 0, 0),
          ("Bastion", 0, 0, 0, 0, 0, 0, 0)]:
    con.execute("INSERT INTO player_stats VALUES (?,?,?,?,?,?,?,?)", r)
con.commit()
con.close()
state_path.write_text(json.dumps({"saved_at": "test", "players": {
    "抽象-1": {"dan": 4, "pt": 650, "rating": 1848.0, "games": 2, "r4": 2,
               "retired": True},
    "抽象-1#2": {"dan": 4, "pt": 905, "rating": 1826.0, "games": 3, "r1": 1, "r2": 1, "r3": 1},
    "Bastion": {"dan": 7, "pt": 1400, "rating": 2100.0, "games": 0}}},
    ensure_ascii=False), encoding="utf-8")

# ---- 跑真实导出 ----
info = xport.export_all(db_path=db, state_path=state_path, config_path=cfg_path,
                        data_root=data_root, season_id="synthetic-test")
snap = data_root / "ladder" / "seasons" / "synthetic-test" / "snapshots" / "latest"
summary = json.loads((snap / "account_summary.json").read_text(encoding="utf-8"))
print("=" * 88)
print("导出结果")
print("=" * 88)
print("accounts 数:", len(summary["accounts"]), " 返回信息:", info)
print()
print(f"{'account_id':<14}{'gen':>4}{'retired':>9}{'lin':>10}{'dan':>5}{'pt':>7}{'R':>9}{'games':>7}{'特局':>6}")
for a in sorted(summary["accounts"], key=lambda x: (x["generation"], x["account_id"])):
    print(f"{a['account_id']:<14}{a['generation']:>4}{str(a['retired']):>9}"
          f"{str(a['lineage']):>10}{a['rank_ordinal']:>5}{a['pt_current']:>7.0f}"
          f"{a['rating']:>9.1f}{a['games']:>7}{a['games_tokujou']:>6}")

ids = {a["account_id"] for a in summary["accounts"]}
checks = [
    ("世代账号 抽象-1#2 出现在榜单", "抽象-1#2" in ids),
    ("抽象-1#2 标记 gen=2", any(a["account_id"] == "抽象-1#2" and a["generation"] == 2
                              for a in summary["accounts"])),
    ("抽象-1#2 血缘指向 抽象-1", any(a["account_id"] == "抽象-1#2" and a["lineage"] == "抽象-1"
                                 for a in summary["accounts"])),
    ("抽象-1 标记 retired=True", any(a["account_id"] == "抽象-1" and a["retired"]
                                 for a in summary["accounts"])),
    ("Bastion 未标记 retired", not any(a["account_id"] == "Bastion" and a["retired"]
                                   for a in summary["accounts"])),
    ("抽象-1#2 局数=3", any(a["account_id"] == "抽象-1#2" and a["games"] == 3
                          for a in summary["accounts"])),
    ("抽象-1 局数=2", any(a["account_id"] == "抽象-1" and a["games"] == 2
                        for a in summary["accounts"])),
]
print()
allok = True
for name, ok in checks:
    print(("  [PASS] " if ok else "  [FAIL] ") + name)
    allok &= ok
print()
print("RESULT:", "PASS" if allok else "FAIL")
shutil.rmtree(tmp, ignore_errors=True)

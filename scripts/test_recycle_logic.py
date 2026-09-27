# -*- coding: utf-8 -*-
"""回收逻辑单测：用 AST 抽出 runner 里 recycle_stuck 的**真实源码**，
在桩环境执行，验证回收/补席语义（不复制函数体，杜绝测试与实现漂移）。
"""
import ast, json, sqlite3, sys, tempfile, shutil
from pathlib import Path

sys.path.insert(0, "D:/tenhoulib/colab_deploy")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from ladder_engine import PlayerState, DAN_NAMES

RUNNER = Path("D:/tenhoulib/.diag/ladder_arena_atozuke.py")
src = RUNNER.read_text(encoding="utf-8")
tree = ast.parse(src)

# ---- 抽出 main() 内 recycle_stuck / roster_register / _root_id 的真实源码 ----
wanted = {"recycle_stuck", "roster_register", "_root_id"}
chunks = {}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in wanted:
        chunks[node.name] = ast.get_source_segment(src, node)
missing = wanted - set(chunks)
assert not missing, f"抽不到源码: {missing}"

tmp = Path(tempfile.mkdtemp(prefix="recycle_test_"))
local_db = tmp / "ladder.db"
con = sqlite3.connect(str(local_db))
con.execute("CREATE TABLE IF NOT EXISTS ladder_roster ("
            "avatar_id TEXT PRIMARY KEY, model_id TEXT NOT NULL,"
            "display_name TEXT, role TEXT, role_desc TEXT,"
            "init_dan INT, init_pt INT, init_rating REAL, gen INT DEFAULT 1,"
            "parent_id TEXT, spawned_seed INT,"
            "spawned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "retired_seed INT, retired_at TIMESTAMP)")
con.commit()
con.close()

# ---- 桩环境：只提供真实函数依赖的那些名字 ----
class Arena:
    def __init__(self, players):
        self.players = players
        self.physical_models = {}

last_seed = {}
ns = {
    "sqlite3": sqlite3, "local_db": local_db, "arena": None,
    "PlayerState": PlayerState, "last_seed": last_seed, "print": print,
    "DAN_NAMES": DAN_NAMES, "roster_register": None, "_root_id": None,
}
exec(compile(chunks["_root_id"], "<_root_id>", "exec"), ns)
exec(compile(chunks["roster_register"], "<roster_register>", "exec"), ns)
exec(compile(chunks["recycle_stuck"], "<recycle_stuck>", "exec"), ns)
recycle_stuck = ns["recycle_stuck"]


def mk(aid, mid, dan, pt, r, retired=False):
    p = PlayerState(avatar_id=aid, model_id=mid, display_name=aid, role="tokujou_native",
                    role_desc="", dan=dan, pt=pt, rating=r)
    p.retired = retired
    return p


def scenario(name, players):
    arena = Arena(players)
    ns["arena"] = arena
    last_seed.clear()
    out = recycle_stuck(300900)
    return arena, out


PASS, FAIL = [], []
def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"   {detail}" if detail else ""))


print("=" * 90)
print("回收逻辑验证")
print("=" * 90)

# --- 场景 1：四段/R1792（掉出特上）→ 应被回收并补新席 ---
arena, out = scenario("s1", {
    "抽象-1": mk("抽象-1", "chouxiang", 4, 305, 1792.45),
    "Bastion": mk("Bastion", "Bin_0910", 7, 2075, 2119.53),
})
okk = (len(out) == 1 and out[0][0] == "抽象-1" and out[0][2] == "抽象-1#2")
chk("掉出特上的账号被回收，同模型补 #2 新席", okk, str([(o[0], o[2]) for o in out]))
chk("旧账号标记 retired=True", arena.players["抽象-1"].retired)
chk("旧账号数据未被篡改（仍 4段/305pt/R1792.45）",
    (arena.players["抽象-1"].dan, arena.players["抽象-1"].pt,
     arena.players["抽象-1"].rating) == (4, 305, 1792.45))
new = arena.players.get("抽象-1#2")
chk("新席在四段水面（4段/800pt/R1800）",
    new is not None and (new.dan, new.pt, new.rating) == (4, 800, 1800.0),
    f"{new.dan}/{new.pt}/{new.rating}" if new else "缺失")
chk("新席模型与旧席一致", new and new.model_id == "chouxiang")
chk("新席在凤凰/特上合格池（get_room=tokujou）", new and new.get_room() == "tokujou")
chk("新席已入名册（gen=2, parent=抽象-1）", new and any(
    r[0] == "抽象-1#2" for r in sqlite3.connect(str(local_db)).execute(
        "SELECT avatar_id FROM ladder_roster WHERE gen=2 AND parent_id='抽象-1'")))

# --- 场景 2：三段（PT 降段导致）→ 同样回收 ---
arena, out = scenario("s2", {
    "全速-1": mk("全速-1", "zensoku", 3, 600, 1900.0),
    "Bastion": mk("Bastion", "Bin_0910", 7, 2075, 2119.53),
})
chk("三段（R 仍达标但段位不足）被回收", len(out) == 1 and out[0][0] == "全速-1")
chk("三段旧席原样留库（3段/600pt）",
    (arena.players["全速-1"].dan, arena.players["全速-1"].pt) == (3, 600))
chk("新席补到四段水面", arena.players["全速-1#2"].dan == 4
    and arena.players["全速-1#2"].pt == 800)

# --- 场景 3：特上/凤凰在位账号不得被回收 ---
arena, out = scenario("s3", {
    "Bastion": mk("Bastion", "Bin_0910", 7, 2075, 2119.53),     # 凤凰
    "Nova1-A": mk("Nova1-A", "distill_nova", 7, 1175, 2168.46), # 凤凰
    "抽象-2": mk("抽象-2", "chouxiang", 5, 325, 1801.0),        # 特上（R 刚好达标）
    "Luna-A": mk("Luna-A", "distill_41b_infer", 8, 2905, 2301.34),
})
chk("特上/凤凰在位账号一律不动", out == [] and not any(
    p.retired for p in arena.players.values()))
chk("未凭空生成新席", set(arena.players) == {"Bastion", "Nova1-A", "抽象-2", "Luna-A"})

# --- 场景 4：已回收的不重复回收；天凤位豁免 ---
arena, out = scenario("s4", {
    "抽象-1": mk("抽象-1", "chouxiang", 4, 305, 1792.45, retired=True),
    "天凤位甲": mk("天凤位甲", "Bin_0910", 11, 4000, 2050.0),
})
chk("已回收账号不重复回收", out == [])
chk("天凤位豁免（即使 R<2000 也不回收）", not arena.players["天凤位甲"].retired)

# --- 场景 5：同一血脉连续回收 → 世代号递增 ---
arena, out = scenario("s5", {
    "抽象-1": mk("抽象-1", "chouxiang", 4, 305, 1792.45, retired=True),
    "抽象-1#2": mk("抽象-1#2", "chouxiang", 4, 300, 1790.0),
    "抽象-1#3": mk("抽象-1#3", "chouxiang", 3, 600, 1850.0),
})
chk("同血脉多席且都掉出特上 → 按序补 #4/#5",
    sorted(o[2] for o in out) == ["抽象-1#4", "抽象-1#5"],
    str(sorted(o[2] for o in out)))
chk("旧席全部标记回收", arena.players["抽象-1#2"].retired and arena.players["抽象-1#3"].retired)

# --- 场景 6：新席进入 last_seed 且年龄为 -1（优先上桌）---
chk("新席写入 last_seed 且值为 -1（最优先上桌）",
    last_seed.get("抽象-1#4") == -1 and last_seed.get("抽象-1#5") == -1,
    str(last_seed))

print()
print(f"结果：PASS={len(PASS)}  FAIL={len(FAIL)}")
print("RESULT:", "PASS" if not FAIL else "FAIL: " + "; ".join(FAIL))
shutil.rmtree(tmp, ignore_errors=True)

# -*- coding: utf-8 -*-
"""桌位分配单测：AST 抽出 runner 里 allocate_tables 的真实源码执行。

需求（用户口径）：总桌数 6；凤凰优先吃满自己的池——凤7 开 1 桌、凤8 开 2 桌。
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = Path("D:/tenhoulib/.diag/ladder_arena_atozuke.py").read_text(encoding="utf-8")
tree = ast.parse(SRC)
chunk = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "allocate_tables":
        chunk = ast.get_source_segment(SRC, node)
        break
assert chunk, "抽不到 allocate_tables 源码"
ns = {}
exec(compile(chunk, "<allocate_tables>", "exec"), ns)
allocate = ns["allocate_tables"]

PASS, FAIL = [], []
def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("   " + detail) if detail else ""))

def pools(h, t, j=0, i=0):
    return {"houou": ["a"] * h, "tokujou": ["b"] * t,
            "joukyuu": ["c"] * j, "ippan": ["d"] * i}

print("=" * 92)
print("凤凰优先 + 总数卡 6")
print("=" * 92)
CASES = [
    # (凤池, 特池, 期望 凤桌, 期望 特桌, 说明)
    (7, 23, 1, 5, "凤7→1桌（余3席轮空），剩余预算全给特上"),
    (8, 22, 2, 4, "凤8→2桌，特上吃剩余 4 张"),
    (11, 19, 2, 4, "凤11→2桌（余3席轮空），不挤占特上超过预算"),
    (4, 26, 1, 5, "凤4→1桌"),
    (12, 18, 3, 3, "凤12→3桌"),
    (3, 27, 0, 6, "凤<4 席开 0 桌，特上吃满 6 张"),
    (0, 30, 0, 6, "无凤桌时特上吃满"),
    (6, 24, 1, 5, "凤6→1桌（余2席轮空）"),
    (20, 10, 5, 1, "凤多到吃满预算，特上只剩 1 张"),
    (28, 2, 6, 0, "凤吃满 6 张，特上池<4 开 0 桌"),
]
for h, t, eh, et, why in CASES:
    got = allocate(pools(h, t), 6)
    ok = got["houou"] == eh and got["tokujou"] == et and got["houou"] + got["tokujou"] <= 6
    chk("凤%d/特%d -> 凤%d桌 特%d桌  (%s)" % (h, t, eh, et, why), ok,
        "got 凤%d 特%d 共%d" % (got["houou"], got["tokujou"], got["houou"] + got["tokujou"]))

print()
print("=" * 92)
print("不变量")
print("=" * 92)
for h in range(0, 33, 3):
    for t in range(0, 33, 5):
        g = allocate(pools(h, t), 6)
        tot = sum(g.values())
        if tot > 6 or g["houou"] > h // 4 or g["tokujou"] > t // 4 \
                or g["houou"] != min(h // 4, 6):
            chk("凤%d/特%d 不变量" % (h, t), False, str(g))
            break
    else:
        continue
    break
else:
    chk("11x7 组合：总数<=6、各卓<=池//4、凤凰优先吃满 全部成立", True)

g = allocate(pools(7, 23, 5, 0), 6)
chk("上级有池时不越权抢在凤凰之前", g["houou"] == 1, str(g))
g2 = allocate(pools(7, 23), 6, per_room=2)
chk("per_room=2 仍可作单卓上限", g2["houou"] == 1 and g2["tokujou"] == 2, str(g2))
g3 = allocate(pools(7, 23), 0)
chk("total=0 时不放桌", sum(g3.values()) == 0, str(g3))
g4 = allocate(pools(0, 0, 0, 0), 6)
chk("空池安全", sum(g4.values()) == 0, str(g4))

print()
print("结果：PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
print("RESULT:", "PASS" if not FAIL else "FAIL: " + "; ".join(FAIL))

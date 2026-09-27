# -*- coding: utf-8 -*-
"""组桌公平性仿真：以真实池构成（凤7/特21/上2）+ 真实模型→分身映射，
复刻 pick_tables 的选取逻辑，统计每个席位的【上桌率】。

用于回答"同名/同模型分身是否被系统性挤掉"。
"""
import random, sys, collections, json
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MODEL = {}
SEC = {
    "houou": ["LuckyJ-v2", "Shadow-J", "Nova-X", "Bastion", "Consensus",
              "V4Best-B", "Nova1-B"],
    "tokujou": ["梦幻情怀-A", "梦幻情怀-B", "全速-1", "全速-2", "全速-3", "全速-4",
                "全速-特5", "抽象-1", "抽象-2", "抽象-3", "抽象-4", "抽象-5",
                "抽象-特6", "V4Best-特1", "V4Best-特2", "Nova1-特1", "Nova1-特2",
                "V4Best-A", "V4Best-C", "全速-1b", "Nova1-A"],
}
# 用真实映射填充（简化：按上面的映射表）
M = {"chouxiang": ["抽象-1", "抽象-2", "抽象-3", "抽象-4", "抽象-5", "抽象-特6"],
     "ext_mortal": ["V4Best-A", "V4Best-B", "V4Best-C", "V4Best-特1", "V4Best-特2"],
     "zensoku": ["全速-1", "全速-2", "全速-3", "全速-4", "全速-特5"],
     "distill_nova": ["Nova1-A", "Nova1-B", "Nova1-特1", "Nova1-特2"],
     "awr_luckyj": ["LuckyJ-v2", "LuckyJ2-分身"],
     "xiaolin_clone_v1_infer": ["梦幻情怀-A", "梦幻情怀-B"],
     "distill_41b_infer": ["Luna-A", "Luna-B"],
     "luckyj_clone_v1": ["Shadow-J"], "distill_nova_v2": ["Nova-X"],
     "Bin_0910": ["Bastion"], "distill_consensus_v3": ["Consensus"]}
for mid, ids in M.items():
    for i in ids:
        MODEL[i] = mid
MODEL["全速-1b"] = "zensoku"

# 真实池：凤7 + 特21（上面 tokujou 列表 21 个）+ 上2
SEC["tokujou"] = ["梦幻情怀-A", "梦幻情怀-B", "全速-1", "全速-2", "全速-3", "全速-4",
                  "全速-特5", "抽象-1", "抽象-2", "抽象-3", "抽象-4", "抽象-5",
                  "抽象-特6", "V4Best-特1", "V4Best-特2", "Nova1-特1", "Nova1-特2",
                  "V4Best-A", "V4Best-C", "Nova1-A", "全速-1b"]
SEC["joukyuu"] = ["抽象-4b", "抽象-2b"]   # 占位，下两行重命名
MODEL["抽象-4b"], MODEL["抽象-2b"] = "chouxiang", "chouxiang"
SEC = {"houou": ["LuckyJ-v2", "Shadow-J", "Nova-X", "Bastion", "Consensus",
                 "V4Best-B", "Nova1-B"],
       "tokujou": ["梦幻情怀-A", "梦幻情怀-B", "全速-1", "全速-2", "全速-3", "全速-4",
                   "全速-特5", "抽象-1", "抽象-2", "抽象-3", "抽象-5",
                   "抽象-特6", "V4Best-特1", "V4Best-特2", "Nova1-特1", "Nova1-特2",
                   "V4Best-A", "V4Best-C", "Nova1-A", "抽象-4b", "抽象-2b"],
       "joukyuu": ["抽象-4", "抽象-2"]}
MODEL["抽象-4"], MODEL["抽象-2"] = "chouxiang", "chouxiang"

ROOM_OF = {}
for room, ids in SEC.items():
    for i in ids:
        ROOM_OF[i] = room


def pick_tables(pool, n_tables):
    """与生产 runner 逐字一致。"""
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
                mid = MODEL[aid]
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
        if len(picked) < 4:
            break
        tables.append(picked)
        used_avatars |= set(picked)
        used_across |= {MODEL[x] for x in picked}
    return tables


N = 400
sel = collections.Counter()
seat_rounds = collections.Counter()
for _ in range(N):
    for room in ("houou", "tokujou", "joukyuu"):
        pool = SEC[room]
        ts = pick_tables(pool, 3)
        for t in ts:
            for a in t:
                sel[(room, a)] += 1
        for a in pool:
            seat_rounds[(room, a)] += 1

print("=" * 96)
print(f"组桌公平性仿真（{N} 轮，tables_per_room=3）")
print("=" * 96)
for room in ("houou", "tokujou", "joukyuu"):
    ids = SEC[room]
    n_tab = len(pick_tables(list(ids), 3))
    print(f"\n--- {room}  池 {len(ids)} 席 -> 实际开桌 {n_tab} 张，上桌 {n_tab*4} 席，"
          f"每轮固定轮空 {len(ids)-n_tab*4} 席 ---")
    rows = sorted(((round(sel[(room, a)] / seat_rounds[(room, a)] * 100, 1), a, MODEL[a])
                   for a in ids), reverse=True)
    for rate, a, m in rows:
        bar = "#" * int(rate / 2.5)
        print(f"   {a:<14} {rate:>5.1f}%  {bar:<40} {m}")
    if n_tab:
        same = collections.defaultdict(list)
        for rate, a, m in rows:
            same[m].append(rate)
        print("   同模型分身上桌率差异:")
        for m, v in same.items():
            if len(v) > 1:
                print(f"     {m:<24} {[f'{x}%' for x in v]}  极差 {max(v)-min(v):.1f}pp")

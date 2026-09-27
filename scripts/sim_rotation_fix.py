# -*- coding: utf-8 -*-
"""验证轮转公平修复：完整复刻新版 pick_tables（含 last_seed 轮转年龄），
跑多轮动态仿真，对比【随机取人】与【轮转年龄优先】两种策略的上桌率分布。
"""
import random, sys, collections
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

M = {"chouxiang": ["抽象-1", "抽象-2", "抽象-3", "抽象-5", "抽象-特6", "抽象-4b", "抽象-2b"],
     "ext_mortal": ["V4Best-A", "V4Best-B", "V4Best-C", "V4Best-特1", "V4Best-特2"],
     "zensoku": ["全速-1", "全速-2", "全速-3", "全速-4", "全速-特5"],
     "distill_nova": ["Nova1-A", "Nova1-B", "Nova1-特1", "Nova1-特2"],
     "awr_luckyj": ["LuckyJ-v2", "LuckyJ2-分身"],
     "xiaolin_clone_v1_infer": ["梦幻情怀-A", "梦幻情怀-B"],
     "distill_41b_infer": ["Luna-A", "Luna-B"],
     "luckyj_clone_v1": ["Shadow-J"], "distill_nova_v2": ["Nova-X"],
     "Bin_0910": ["Bastion"], "distill_consensus_v3": ["Consensus"]}
MODEL = {a: m for m, ids in M.items() for a in ids}
SEC = {"houou": ["LuckyJ-v2", "Shadow-J", "Nova-X", "Bastion", "Consensus",
                 "V4Best-B", "Nova1-B"],
       "tokujou": ["梦幻情怀-A", "梦幻情怀-B", "全速-1", "全速-2", "全速-3", "全速-4",
                   "全速-特5", "抽象-1", "抽象-3", "抽象-5", "抽象-特6", "V4Best-特1",
                   "V4Best-特2", "Nova1-特1", "Nova1-特2", "V4Best-A", "V4Best-C",
                   "Nova1-A", "Nova1-B", "LuckyJ2-分身", "Luna-B"],
       "joukyuu": ["抽象-2", "抽象-4b"]}


def pick_tables(pool, n_tables, last_seed, rotate):
    """复刻 runner 的 pick_tables；rotate=False 用旧的 random.shuffle。"""
    if rotate:
        pool = sorted(pool, key=lambda aid: (last_seed.get(aid, -1), random.random()))
    else:
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


def run(rotate, rounds=300, tables_per_room=3):
    last_seed = {}
    sel = collections.Counter()
    for rnd in range(rounds):
        for room, ids in SEC.items():
            for t in pick_tables(list(ids), tables_per_room, last_seed, rotate):
                for a in t:
                    sel[a] += 1
                    last_seed[a] = rnd
    return sel


print("=" * 100)
print("上桌率对比（300 轮，tables_per_room=3）")
print("=" * 100)
for rotate, label in ((False, "旧 · 随机取人"), (True, "新 · 轮转年龄优先")):
    random.seed(20260925)
    sel = run(rotate)
    print(f"\n── {label} ──")
    for room in ("houou", "tokujou", "joukyuu"):
        ids = [a for a in SEC[room]]
        rates = {a: sel[a] / 300 * 100 for a in ids}
        vals = list(rates.values())
        spread = max(vals) - min(vals)
        # 按分身数分组，看上桌率是否与分身数相关
        bymodel = collections.defaultdict(list)
        for a in ids:
            bymodel[MODEL[a]].append(rates[a])
        # 相关系数：同池内 分身数 vs 平均上桌率
        xs = [len(v) for v in bymodel.values()]
        ys = [sum(v) / len(v) for v in bymodel.values()]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        corr = cov / den if den else 0.0
        print(f"  {room:8s} 上桌率 {min(vals):5.1f}% ~ {max(vals):5.1f}%   极差 {spread:5.1f}pp"
              f"   分身数↔上桌率 相关 {corr:+.3f}")
        if room == "tokujou":
            for m, v in sorted(bymodel.items(), key=lambda kv: -len(kv[1])):
                print(f"      {m:<24} {len(v)} 分身  平均 {sum(v)/len(v):5.1f}%  "
                      + " ".join(f"{x:.0f}%" for x in sorted(v, reverse=True)))

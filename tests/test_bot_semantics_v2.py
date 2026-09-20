"""语义口径回归：吃完标签格式、pass 口径、3n+1/3n+2 路由、默认牌河加权抽样。

不依赖 native/模型，仅覆盖 parser 与渲染标签层。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

from parser import parse_sim_command  # noqa: E402
from render_png import candidate_label, pass_mode  # noqa: E402


def cand(name: str) -> dict:
    """轻量候选字典：与 normalize_candidate 对纯动作名的结果等价（不引入 native 依赖）。"""
    if name.startswith("chi:"):
        core, _, follow = name[4:].partition(">")
        tiles = [core[i:i + 2] for i in range(0, len(core), 2)]
        return {"tile": "chi", "chi": tiles, "candidate": name, "follow_up_discard": follow or None}
    if name.startswith("pon:"):
        return {"tile": "pon", "pon": True, "candidate": name, "call_tile": name[4:6]}
    if name == "pass":
        return {"tile": "pass", "pass": True, "candidate": "pass"}
    if name in ("ron", "tsumo"):
        return {"tile": name, "candidate": name, name: True}
    return {"tile": name, "candidate": name}


# ---------- 4. 吃完标签：chi:1m2m -> "12m吃" ----------
def test_chi_label_uses_compact_chinese_suffix():
    assert candidate_label(cand("chi:1m2m")) == "12m吃"
    assert candidate_label(cand("chi:2m4m")) == "24m吃"
    # 后切跟随牌保持 >9s 形式，不吞掉
    assert candidate_label(cand("chi:1m2m>9s")) == "12m吃>9s"


def test_pon_label_unchanged():
    assert candidate_label(cand("pon:3m")) == "碰 3m"


# ---------- 3. pass 口径：见逃 vs 跳过 ----------
def test_pass_is_agari_when_win_branch_present():
    cands = [cand("ron"), cand("pass")]
    assert pass_mode(cands) == "agari"
    assert candidate_label(cand("pass"), cands) == "见逃 (过)"


def test_pass_is_skip_for_plain_fuuro_decision():
    cands = [cand("chi:1m2m"), cand("pon:3m"), cand("pass")]
    assert pass_mode(cands) == "fuuro"
    assert candidate_label(cand("pass"), cands) == "跳过"


# ---------- 2. 3n+1 / 3n+2 路由强校验 ----------
def test_thirteen_tiles_with_discard_candidates_is_rejected():
    # 13 张（3n+1）却给了纯切牌候选：必须报错，不能混进打牌判断
    req, err = parse_sim_command("/sim 12334567889m9s4z d9p c=9s x=2 S4-0 20")
    assert req is None and err is not None
    assert "3n+2" in err and "副露" in err


def test_fourteen_tiles_with_fuuro_candidates_is_rejected():
    req, err = parse_sim_command("/sim 12334567889m9s4z9p d9p c=chi:3m,pass x=2 S4-0 20")
    assert req is None and err is not None
    assert "3n+1" in err


def test_thirteen_tiles_response_ok_and_fourteen_discard_ok():
    req, err = parse_sim_command("/sim 12334567889m9s4z d9p c=chi:3m,pass x=2 S4-0 20")
    assert err is None and req is not None
    req2, err2 = parse_sim_command("/sim 12334567889m9s4z9p d9p c=9s x=2 S4-0 20")
    assert err2 is None and req2 is not None


# ---------- 牌河加权抽样 ----------
def test_default_rivers_deterministic_and_excludes_own_honors():
    cmd = "/sim 12334567889m9s4z d9p c=chi:3m,pass x=3 S4-0 seat=东 P116,290,416,178 20"
    a, _ = parse_sim_command(cmd)
    b, _ = parse_sim_command(cmd)
    assert a["opponent_rivers"] == b["opponent_rivers"], "同一牌局必须生成同一牌河（可复现）"

    # 手里有 4z，所有他家牌河都不应出现 4z
    for p, river in enumerate(a["opponent_rivers"]):
        assert all(t[0] != "4z" for t in river), f"玩家{p}牌河出现了自己持有的字牌 4z"


def test_river_sampling_is_weighted_not_fixed_priority():
    """不同巡目/手牌的抽样应产生不同牌河；且 28 数牌出现率显著低于幺九/字牌。"""
    from parser import _generate_default_rivers

    honors_and_19 = 0
    mid_28 = 0
    for x in range(2, 12):
        hand = ["1m", "2m", "3m", "3m", "4m", "5m", "6m", "7m", "8m", "8m", "9m", "9s", "4z"]
        _, rivers = _generate_default_rivers(hand, 0, 0, x)
        for river in rivers:
            for t, _, _ in river:
                if t.endswith("z") or t[0] in "19":
                    honors_and_19 += 1
                elif t[0] in "28":
                    mid_28 += 1
    assert honors_and_19 > 0
    # 28 数牌权重为幺九/字牌的 1/5，样本上不应反超
    assert mid_28 < honors_and_19


# ---------- 赤五作为独立候选 ----------
def test_red_five_chi_expands_as_separate_candidate():
    from parser import _infer_chi_consumed
    # 手牌同时有普通 5m 与赤 0m：吃 4m 应展开两个候选（赤五打点不同）
    assert _infer_chi_consumed(["0m", "5m", "6m", "9s"], "4m") == [["5m", "6m"], ["0m", "6m"]]
    # 只有赤五时仍可成立
    assert _infer_chi_consumed(["4m", "0m", "9s"], "6m") == [["4m", "0m"]]
    # 缺张时不得伪造
    assert _infer_chi_consumed(["5m", "5m"], "4m") == []


def test_red_five_chi_end_to_end():
    req, err = parse_sim_command("/sim 0456m11223399p9s d9p c=chi:4m,pass x=2 S4-0 20")
    assert err is None
    names = [c.get("candidate") for c in req["discards"]]
    assert "chi:5m6m" in names and "chi:0m6m" in names


# ---------- 大明杠不模拟 ----------
def test_daiminkan_is_rejected_not_simulated():
    req, err = parse_sim_command("/sim 12334567889m9s4z d9p c=daiminkan,pass x=2 S4-0 20")
    assert req is None and err is not None
    assert "不模拟" in err

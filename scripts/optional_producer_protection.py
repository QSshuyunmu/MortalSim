# -*- coding: utf-8 -*-
"""
【可选 · 暂未启用】生产者（特上原住民）保级保护补丁
=================================================

背景 / 动机
-----------
当前 v2.3 方案中，四段生产者跌破 0pt 会降段至三段，并因段位不足四段被
驱逐出特上、跌入上级卓。长期运行的副作用是：

1. 特上鱼塘会被逐渐抽干，对手多样性下降；
2. 上级卓被长期激活，每批次多出一路串行调度开销。

启用后：生产者四段跌破 0pt 时**不降段、不降卓**，只把配点重置回 800pt，
并继续留在特上。对照组（5 席冲顶主力 + 9 席特凤升降机）不受影响，
仍走完整降卓链路，因此降卓压力测试依然成立。

实测（连吃 300 次四位）
----------------------
- 启用后：16 席生产者全部稳定停在 四段 / R1800.00 / 特上卓
- 对照组 LuckyJ-v2：一路降至初段并落入上级卓

如何使用
--------
把本文件的全部内容作为一个新的代码单元格，插入到「编译 libriichi」单元格
与「启动天梯赛季」单元格之间，然后正常运行即可。补丁是幂等的：
若文件已打过补丁则自动跳过。

注意事项
--------
- 生产者的 Rating 会被钳制在 1800，长期贴地，**R 对它们不再有区分度**。
  后续横向比较特上模型强弱时，请改用 PT 与安定段位，不要看 R。
- 生产者之间的对局会长期发生在同一批账号之间，特上对手多样性略降，
  这是「鱼塘稳定」的代价。
"""

# ==================== 以下为补丁单元格本体 ====================
import os, json, sys, importlib, logging

ENGINE = '/content/colab_arena/ladder_engine.py'
CONFIG = '/content/colab_arena/models_config.json'

# ── 生产者策略参数（如需调整只改这里）──────────────────────────────
PRODUCER_ROLE         = 'tokujou_native'  # 享受保护的角色
PRODUCER_FLOOR_DAN    = 4                 # 段位下限：四段（跌破 0pt 重置为 800pt）
PRODUCER_FLOOR_RATING = 1800.0            # Rating 下限：特上门槛，防止被 R 挤出

for _p in ['/content/colab_arena', '/content/colab_arena/mortal']:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _rd(p):
    with open(p, 'r', encoding='utf-8', newline='') as f:
        return f.read()


def _wr(p, s):
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


_src = _rd(ENGINE)

if 'self.floor_dan = floor_dan' in _src and 'self.floor_rating' in _src:
    print('[skip] ladder_engine.py 已包含段位/评级下限保护，无需补丁')
else:
    # 1) 构造函数新增 floor_dan / floor_rating
    _old = """        rating: float
    ):
        self.avatar_id = avatar_id"""
    _new = """        rating: float,
        floor_dan: int = 1,
        floor_rating: float = None,
    ):
        self.avatar_id = avatar_id"""
    assert _src.count(_old) == 1, '构造函数签名匹配失败'
    _src = _src.replace(_old, _new)

    # 2) 字段初始化
    _old = """        self.rating = rating
        self.games = 0"""
    _new = """        self.rating = rating
        # 段位/评级下限保护：用于「生产者」账号（特上原住民）。
        # 触达下限后不再降段、不再降卓，只重置配点，从而长期稳定产出对局。
        # 默认 floor_dan=1 即常规行为（可一路降到初段）。
        self.floor_dan = floor_dan
        self.floor_rating = floor_rating
        self.games = 0"""
    assert _src.count(_old) == 1, '字段初始化匹配失败'
    _src = _src.replace(_old, _new)

    _old = """        self.is_tenhou = (dan >= 11)"""
    _new = """        self.is_tenhou = (dan >= 11)
        self.reset_count = 0"""
    assert _src.count(_old) == 1, 'is_tenhou 匹配失败'
    _src = _src.replace(_old, _new)

    # 3) 降段分支：触达下限改为保级重置
    _old = """            elif self.pt < 0:
                if self.dan > 1:
                    self.dan -= 1
                    self.pt = 200 * self.dan
                    log.warning(f"🔻 降段！账号 [{self.display_name}] 跌破 0pt，降至 {DAN_NAMES.get(self.dan, f'{self.dan}段')} (重置 {self.pt} pt)")
                else:
                    self.pt = 0"""
    _new = """            elif self.pt < 0:
                if self.dan > self.floor_dan:
                    self.dan -= 1
                    self.pt = 200 * self.dan
                    log.warning(f"🔻 降段！账号 [{self.display_name}] 跌破 0pt，降至 {DAN_NAMES.get(self.dan, f'{self.dan}段')} (重置 {self.pt} pt)")
                elif self.dan == self.floor_dan and self.floor_dan > 1:
                    # 生产者账号触达段位下限：不降段、不降卓，仅重置配点。
                    self.pt = 200 * self.dan
                    self.reset_count += 1
                    log.info(
                        f"♻️ 保级重置！账号 [{self.display_name}] 触达下限 "
                        f"{DAN_NAMES.get(self.floor_dan, f'{self.floor_dan}段')}，配点重置为 {self.pt} pt"
                        f"（第 {self.reset_count} 次，不降卓）"
                    )
                else:
                    self.pt = 0"""
    assert _src.count(_old) == 1, '降段分支匹配失败'
    _src = _src.replace(_old, _new)

    # 4) Rating 下限钳制
    _old = """        self.rating = round(float(self.rating) + float(delta_r), 2)

        self.peak_dan"""
    _new = """        self.rating = round(float(self.rating) + float(delta_r), 2)

        # 生产者账号的 Rating 下限保护：确保不会被 R 门槛挤出所在卓别。
        if self.floor_rating is not None and self.rating < self.floor_rating:
            self.rating = float(self.floor_rating)

        self.peak_dan"""
    assert _src.count(_old) == 1, 'Rating 更新段匹配失败'
    _src = _src.replace(_old, _new)

    # 5) load_config 透传新字段
    _old = """                rating=a["init_rating"]
            )"""
    _new = """                rating=a["init_rating"],
                floor_dan=a.get("floor_dan", 1),
                floor_rating=a.get("floor_rating"),
            )"""
    assert _src.count(_old) == 1, 'load_config 匹配失败'
    _src = _src.replace(_old, _new)

    _wr(ENGINE, _src)
    print('[ok] ladder_engine.py 已注入段位/评级下限保护')

# ── 写入生产者下限配置 ──────────────────────────────────────────────
with open(CONFIG, 'r', encoding='utf-8') as f:
    _cfg = json.load(f)

_n = 0
for _a in _cfg['avatars']:
    if _a.get('role') == PRODUCER_ROLE:
        _a['floor_dan'] = PRODUCER_FLOOR_DAN
        _a['floor_rating'] = PRODUCER_FLOOR_RATING
        _n += 1
    else:
        _a.pop('floor_dan', None)
        _a.pop('floor_rating', None)

_cfg['version'] = '2.4'
_cfg['comment'] = (
    "Tenhou Multi-Tier Arena: 生产者(特上原住民)享段位/R下限保护 floor_dan=4/floor_rating=1800，"
    "跌破 0pt 时重置为 800pt 而非降入上级卓，保证特上鱼塘稳定产出对局"
)
_cfg['producer_policy'] = {
    'floor_dan': PRODUCER_FLOOR_DAN,
    'floor_rating': PRODUCER_FLOOR_RATING,
    'reset_pt': 200 * PRODUCER_FLOOR_DAN,
    'scope': PRODUCER_ROLE,
    'note': '仅作用于 role=tokujou_native 的 16 席特上原住民；contender/elevator 仍走完整降卓链路',
}
with open(CONFIG, 'w', encoding='utf-8', newline='') as f:
    json.dump(_cfg, f, ensure_ascii=False, indent=2)
print(f'[ok] models_config.json 已配置 {_n} 席 {PRODUCER_ROLE} 的下限保护')

# ── 自检：生产者不离特上，对照账号仍可降卓 ──────────────────────────
logging.disable(logging.CRITICAL)
import ladder_engine
importlib.reload(ladder_engine)
from ladder_engine import PlayerState, DAN_NAMES


def _mk(_a):
    return PlayerState(_a['avatar_id'], _a['model_id'], _a['display_name'], _a['role'],
                       _a.get('role_desc', ''), _a['init_dan'], _a['init_pt'], _a['init_rating'],
                       floor_dan=_a.get('floor_dan', 1), floor_rating=_a.get('floor_rating'))


_bad = []
for _a in _cfg['avatars']:
    if _a.get('role') != PRODUCER_ROLE:
        continue
    _p = _mk(_a)
    for _ in range(300):
        _p.apply_game_result(4, 7000, 1750.0, 'tokujou')
    if _p.get_room() != 'tokujou':
        _bad.append(_a['display_name'])
    print(f"   生产者 {_p.display_name:<14} 段位={DAN_NAMES[_p.dan]} pt={_p.pt:>5} "
          f"R={_p.rating:>7.2f} 保级重置={_p.reset_count}次 卓={_p.get_room()}")

_ctrl = _mk(next(_a for _a in _cfg['avatars']
                 if _a.get('role') != PRODUCER_ROLE and _a['init_dan'] <= 7))
for _ in range(300):
    _ctrl.apply_game_result(4, 7000, 1750.0, 'houou' if _ctrl.get_room() == 'houou' else 'tokujou')
print(f"   对照   {_ctrl.display_name:<14} 段位={DAN_NAMES[_ctrl.dan]} "
      f"R={_ctrl.rating:>7.2f} 卓={_ctrl.get_room()}")
logging.disable(logging.NOTSET)

assert not _bad, f'生产者仍被挤出特上: {_bad}'
assert _ctrl.get_room() == 'joukyuu', '对照账号未能正常降卓，降卓链路被破坏'
print()
print(f'=== 生产者保级保护已生效：{_n} 席原住民永驻特上，主力/升降机仍走完整降卓链路 ===')

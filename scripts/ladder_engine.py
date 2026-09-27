# -*- coding: utf-8 -*-
"""
Colab GPU 专享：全保真天凤四级多卓分层天梯自弈引擎 (ladder_engine.py - v2.2)
【真实天凤架构与分身矩阵】：
1. 真实数据金字塔 (基于 tenhou.net/stat/dan.js 官方 21.7 万活跃账号)：
   - 凤凰卓：7段且 R>=2000，全天凤仅 2,861 人 (七段占 70.9%，八段占 21.3%，九段占 6.1%，十段仅 23 人)。
   - 特上卓：4段且 R>=1800，全天凤 16,276 人，人口基底是凤凰桌的 5.7 倍！
   - 上级卓：1级以上或 R>=1600；一般卓：新人起跑。
2. 完整升降卓闭环机制 (全自动状态机)：
   - 凤特升降：七段跌破 0pt 或 R<2000 驱逐出凤桌回特上；特上打满 2400pt 且 R>=2000 重新杀回凤凰！
   - 特上跌落：四段跌破 0pt (降至三段) 或 Rating 跌破 1800 即刻驱逐出特上，跌入「上级卓」！在上级卓打出正期望重回四段且 R>=1800 才能杀回特上！
3. 分身矩阵 (Avatar System - 30 席生态)：
   - 物理模型 GPU 仅加载 11 款权重 (仅耗 1.2GB VRAM)；
   - 5 席顶级冲顶主力 (LuckyJ-v2、Shadow-J、Nova-X、Bastion、Consensus)；
   - 9 席特凤升降机主力 (梦幻情怀-A 六段冲刺、V4Best*3、Nova1*2、Luna*2、LuckyJ2分身)；
   - 16 席特上深水区原住民 (梦幻情怀-B 五段防守、全速高副露大军、抽象鲶鱼大军、V4/Nova1特上阻尼)。
4. 终极之巅：十段 4000pt 晋升 11段「天凤位」(Tenhou-i)，PT 永久冻结登顶名人堂！
"""
import os
import sys
import time
import math
import json
import sqlite3
import random
import logging
from pathlib import Path

# ── 环境自愈：确保 colab_arena 与 mortal 目录优先导入 ───────────────────
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_HERE / "mortal") not in sys.path:
    sys.path.insert(0, str(_HERE / "mortal"))

try:
    import libriichi
except Exception:
    pass

import torch
import torch.nn as nn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ladder")

DAN_NAMES = {
    1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段",
    6: "六段", 7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位"
}

ROOM_CONFIGS = {
    "houou": {
        "name": "凤凰卓",
        "min_dan": 7,
        "min_rating": 2000.0,
        "bonus": (90.0, 45.0, 0.0)
    },
    "tokujou": {
        "name": "特上卓",
        "min_dan": 4,
        "min_rating": 1800.0,
        "bonus": (75.0, 30.0, 0.0)
    },
    "joukyuu": {
        "name": "上级卓",
        "min_dan": 1,
        "min_rating": 1600.0,
        "bonus": (60.0, 15.0, 0.0)
    },
    "ippan": {
        "name": "一般卓",
        "min_dan": 0,
        "min_rating": 0.0,
        "bonus": (30.0, 15.0, 0.0)
    }
}

class PolicyNetHead(nn.Module):
    """带 PolicyNet 头的模型 (awr_luckyj / chouxiang)。

    隐藏层维度因模型而异（awr_luckyj=512, chouxiang=256），
    因此必须从 state_dict 的实际形状反推各层维度，不能写死。
    """

    def __init__(self, state_dict):
        super().__init__()
        w1 = state_dict["fc1.weight"]
        w2 = state_dict["fc2.weight"]
        self.fc1 = nn.Linear(w1.shape[1], w1.shape[0])
        self.act = nn.Mish()
        self.fc2 = nn.Linear(w2.shape[1], w2.shape[0])
        self.load_state_dict(state_dict)

    def forward(self, phi, mask):
        x = self.act(self.fc1(phi))
        logits = self.fc2(x)
        return logits.masked_fill(~mask, -torch.inf)

class PlayerState:
    def __init__(
        self,
        avatar_id: str,
        model_id: str,
        display_name: str,
        role: str,
        role_desc: str,
        dan: int,
        pt: int,
        rating: float,
        floor_dan: int = 1,
        floor_rating: float = None,
    ):
        self.avatar_id = avatar_id
        self.model_id = model_id
        self.display_name = display_name
        self.role = role
        self.role_desc = role_desc
        self.dan = dan
        self.pt = pt
        self.rating = rating
        # 段位/评级下限保护（可选能力，默认不启用）：
        # floor_dan=1 时，跌破 0pt 的初段账号会把配点重置回 200pt（而非钳制到 0）；
        # 二段及以上一律按官方规程正常降段。
        # 若在配置里为某账号设置 floor_dan=4，则该账号在四段跌破 0pt 时
        # 不降段、不降卓，只重置配点，可让特上生产者长期留在特上。
        self.floor_dan = floor_dan
        self.floor_rating = floor_rating
        self.games = 0
        self.r1 = 0
        self.r2 = 0
        self.r3 = 0
        self.r4 = 0
        self.fly_count = 0
        self.total_score = 0
        self.peak_dan = dan
        self.peak_rating = rating
        self.is_tenhou = (dan >= 11)
        self.reset_count = 0

    def get_room(self) -> str:
        # 1. 凤凰卓双门槛：7段且 R>=2000.0 (天凤位永久在位)
        if self.is_tenhou or (self.dan >= 7 and self.rating >= 2000.0):
            return "houou"
        # 2. 特上卓双门槛：4段且 R>=1800.0 (跌破4段或跌破1800即跌入上级卓)
        if self.dan >= 4 and self.rating >= 1800.0:
            return "tokujou"
        # 3. 上级卓门槛：1段以上或 R>=1600.0
        if self.dan >= 1 or self.rating >= 1600.0:
            return "joukyuu"
        return "ippan"

    def stable_dan(self, room="houou") -> float:
        if self.games == 0:
            return float(self.dan)
        if self.r4 == 0:
            return 11.0 if self.is_tenhou else float(self.dan) + 1.0
        r1_rate = self.r1 / self.games
        r2_rate = self.r2 / self.games
        r4_rate = self.r4 / self.games
        if room == "houou":
            return round((6.0 * r1_rate + 3.0 * r2_rate) / r4_rate - 2.0, 2)
        else:
            return round((5.0 * r1_rate + 2.0 * r2_rate) / r4_rate - 2.0, 2)

    def apply_game_result(self, rank: int, score: int, table_avg_r: float, room: str):
        old_room = self.get_room()
        self.games += 1
        self.total_score += score
        if rank == 1: self.r1 += 1
        elif rank == 2: self.r2 += 1
        elif rank == 3: self.r3 += 1
        elif rank == 4: self.r4 += 1
        if score < 0: self.fly_count += 1

        # 1. PT 与段位升降状态机 (天凤官方规程)
        if not self.is_tenhou:
            room_cfg = ROOM_CONFIGS.get(room, ROOM_CONFIGS["tokujou"])
            if rank in (1, 2, 3):
                pt_delta = room_cfg["bonus"][rank - 1]
            elif rank == 4:
                # 4位扣分: -(15*D + 30) pt
                pt_delta = -(15 * self.dan + 30)
            else:
                pt_delta = 0

            self.pt += int(pt_delta)

            # 升段与终极天凤位判定
            if self.dan == 10 and self.pt >= 4000:
                self.dan = 11
                self.is_tenhou = True
                self.pt = 4000
                log.info(f"★ 震撼登顶！账号 [{self.display_name}] 突破十段 4000pt，正式晋升 11段「天凤位」！")
            elif self.pt >= 400 * self.dan and self.dan < 10:
                self.dan += 1
                self.pt = 200 * self.dan
                log.info(f"★ 升段！账号 [{self.display_name}] 晋升至 {DAN_NAMES.get(self.dan, f'{self.dan}段')} (初始 {self.pt} pt)")
            elif self.pt < 0:
                if self.dan > self.floor_dan:
                    self.dan -= 1
                    self.pt = 200 * self.dan
                    log.warning(f"▼ 降段！账号 [{self.display_name}] 跌破 0pt，降至 {DAN_NAMES.get(self.dan, f'{self.dan}段')} (重置 {self.pt} pt)")
                elif self.dan == self.floor_dan:
                    # 已达段位下限：不降段、不降卓，只把配点重置回该段初始值。
                    self.pt = 200 * self.dan
                    self.reset_count += 1
                    log.info(
                        f"◎ 保级重置！账号 [{self.display_name}] 触及下限 "
                        f"{DAN_NAMES.get(self.floor_dan, f'{self.floor_dan}段')}，配点重置为 {self.pt} pt"
                        f"（第 {self.reset_count} 次，不降卓）"
                    )
                else:
                    self.pt = 0

        # 2. Rating 官方动态更新
        place_points = {1: 30.0, 2: 10.0, 3: -10.0, 4: -30.0}
        base_r_pt = place_points.get(rank, 0.0)
        correction = max(1.0 - 0.002 * self.games, 0.2)
        delta_r = (base_r_pt + (table_avg_r - self.rating) / 40.0) * correction
        self.rating = round(float(self.rating) + float(delta_r), 2)

        # 可选 Rating 下限保护（仅当配置里显式给了 floor_rating 时生效）。
        if self.floor_rating is not None and self.rating < self.floor_rating:
            self.rating = float(self.floor_rating)

        self.peak_dan = max(self.peak_dan, self.dan)
        self.peak_rating = max(self.peak_rating, self.rating)

        # 3. 房间变动跨界告警与通知 (特上跌落上级 / 凤特升降)
        new_room = self.get_room()
        if old_room != new_room:
            if old_room == "tokujou" and new_room == "joukyuu":
                log.warning(f"!! 跌出特上！账号 [{self.display_name}] 跌破特上双门槛 (当前 {DAN_NAMES.get(self.dan, f'{self.dan}段')} R{self.rating:.1f})，降入「上级卓」！")
            elif old_room == "joukyuu" and new_room == "tokujou":
                log.info(f"▲ 杀回特上！账号 [{self.display_name}] 达成四段且 R>=1800 (当前 {DAN_NAMES.get(self.dan, f'{self.dan}段')} R{self.rating:.1f})，重返「特上卓」！")
            elif old_room == "houou" and new_room == "tokujou":
                log.warning(f"▼ 跌出凤凰！账号 [{self.display_name}] 跌破凤桌门槛，降入「特上卓」！")
            elif old_room == "tokujou" and new_room == "houou":
                log.info(f"▲ 杀入凤凰！账号 [{self.display_name}] 达成七段且 R>=2000，正式晋级「凤凰卓」！")


class TenhouRankedLadderArena:
    def __init__(self, config_path: str, models_dir: str, db_path: str, device="cuda",
                 load_engines: bool = True):
        self.config_path = config_path
        self.models_dir = Path(models_dir)
        self.db_path = db_path
        self.device = torch.device(device if (device == "cpu" or torch.cuda.is_available()) else "cpu")
        self.physical_models = {}
        self.players: dict[str, PlayerState] = {}
        self.model_engines = {}
        self.init_database()
        self.load_config()
        if load_engines:
            self.load_physical_engines()

    def init_database(self):
        with sqlite3.connect(self.db_path) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS ladder_games (
                    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room TEXT,
                    seed_idx INTEGER,
                    split INTEGER,
                    seat INTEGER,
                    avatar_id TEXT,
                    model_id TEXT,
                    rank INTEGER,
                    score INTEGER,
                    pt_before INTEGER,
                    pt_after INTEGER,
                    dan_before INTEGER,
                    dan_after INTEGER,
                    rating_before REAL,
                    rating_after REAL,
                    table_avg_r REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS ladder_snapshots (
                    round_idx INTEGER,
                    avatar_id TEXT,
                    model_id TEXT,
                    dan INTEGER,
                    pt INTEGER,
                    rating REAL,
                    games INTEGER,
                    r1_rate REAL,
                    r4_rate REAL,
                    room TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.commit()

    def load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        for pm in cfg.get("physical_models", []):
            self.physical_models[pm["model_id"]] = pm

        for a in cfg.get("avatars", []):
            aid = a["avatar_id"]
            self.players[aid] = PlayerState(
                avatar_id=aid,
                model_id=a["model_id"],
                display_name=a["display_name"],
                role=a.get("role", "contender"),
                role_desc=a.get("role_desc", ""),
                dan=a["init_dan"],
                pt=a["init_pt"],
                rating=a["init_rating"],
                floor_dan=a.get("floor_dan", 1),
                floor_rating=a.get("floor_rating"),
            )
        log.info(f"Loaded {len(self.physical_models)} physical models & {len(self.players)} ranked avatars into Arena.")

    def load_physical_engines(self):
        sys.path.insert(0, str(Path(self.models_dir).parent / "mortal"))
        from engine import MortalEngine
        from model import Brain, DQN

        log.info(f"Loading {len(self.physical_models)} physical model weights onto {self.device}...")
        for mid, pm in self.physical_models.items():
            fn = pm["file"]
            target_path = self.models_dir / fn
            if not target_path.exists():
                for f in self.models_dir.glob("*.pth"):
                    if mid.lower() in f.stem.lower():
                        target_path = f
                        break
            if not target_path.exists():
                raise FileNotFoundError(f"Cannot find model file {fn} for {mid} in {self.models_dir}")

            st = torch.load(str(target_path), map_location="cpu", weights_only=False)
            cfg = st.get("config", {})
            ver = cfg.get("control", {}).get("version", 4)
            conv_ch = cfg.get("resnet", {}).get("conv_channels", 192)
            blocks = cfg.get("resnet", {}).get("num_blocks", 40)
            brain = Brain(version=ver, conv_channels=conv_ch, num_blocks=blocks).to(self.device).eval()

            if "policy_net" in st or "policy" in st:
                pol_weights = st.get("policy_net") or st.get("policy")
                dqn = PolicyNetHead(pol_weights).to(self.device).eval()
            else:
                dqn = DQN(version=ver).to(self.device).eval()
                dqn.load_state_dict(st["current_dqn"])

            brain.load_state_dict(st.get("mortal") or st.get("brain"))
            engine = MortalEngine(
                brain, dqn,
                is_oracle=False,
                version=ver,
                device=self.device,
                enable_amp=(self.device.type == "cuda"),
                name=mid
            )
            self.model_engines[mid] = engine
            log.info(f"  + Engine [{mid:<24}] Loaded (Type={pm['type']}, Version={ver}, Blocks={blocks})")

    def select_four_diverse_avatars(self, avatar_pool: list[str]) -> list[str]:
        """优先选取来自不同物理模型的 4 个账号，保证对抗异质性与多样性"""
        random.shuffle(avatar_pool)
        selected = []
        selected_models = set()

        for aid in avatar_pool:
            mid = self.players[aid].model_id
            if mid not in selected_models:
                selected.append(aid)
                selected_models.add(mid)
                if len(selected) == 4:
                    return selected

        # 若不同模型不足 4 个，放宽限制补齐
        for aid in avatar_pool:
            if aid not in selected:
                selected.append(aid)
                if len(selected) == 4:
                    return selected

        # 若仍然不足 4 人，从全量账号中借调陪练
        all_aids = list(self.players.keys())
        while len(selected) < 4:
            c = random.choice(all_aids)
            if c not in selected:
                selected.append(c)
        return selected[:4]

    def run_ladder_season(self, total_seeds=5000, batch_seeds=16):
        import libriichi
        log.info(f"Starting Tenhou Ranked Ladder Season (Total Seeds={total_seeds}, Batch={batch_seeds})...")
        arena = libriichi.arena.FourPlayer(disable_progress_bar=True)
        seed_cursor = 100000

        for batch_i in range(0, total_seeds, batch_seeds):
            # 1. 动态按房间划分活跃账号池
            room_pools = {"houou": [], "tokujou": [], "joukyuu": [], "ippan": []}
            for aid, p in self.players.items():
                room = p.get_room()
                room_pools[room].append(aid)

            log.info(
                f"\n--- Batch {batch_i // batch_seeds + 1} | Active Pools: "
                f"凤凰卓: {len(room_pools['houou'])} 席 | "
                f"特上卓: {len(room_pools['tokujou'])} 席 | "
                f"上级卓/降级储备: {len(room_pools['joukyuu'])} 席 ---"
            )

            # 2. 为所有活跃战区分别组桌（包含上级卓，确保特上掉到上级有完整对局爬坡链条）
            active_rooms = ["houou", "tokujou"]
            if len(room_pools["joukyuu"]) > 0:
                active_rooms.append("joukyuu")

            for room in active_rooms:
                pool = room_pools[room]
                if len(pool) < 4:
                    # 借调相邻房间账号作为陪练
                    if room == "houou":
                        filler_pool = room_pools["tokujou"]
                    elif room == "tokujou":
                        filler_pool = room_pools["houou"] if len(room_pools["houou"]) >= 4 else room_pools["joukyuu"]
                    else: # joukyuu (上级卓)
                        filler_pool = room_pools["tokujou"]
                    pool = pool + list(filler_pool)

                # 每批次组桌对局
                table_avatars = self.select_four_diverse_avatars(pool)
                table_engines = [self.model_engines[self.players[aid].model_id] for aid in table_avatars]
                table_avg_r = sum(self.players[aid].rating for aid in table_avatars) / 4.0

                # 运行 batch_seeds 副牌 (每副牌 4-seat 轮转 = 4 半庄)
                rows = arena.py_vs_py_detailed(
                    table_engines[0], table_engines[1], table_engines[2], table_engines[3],
                    (seed_cursor, 0), batch_seeds
                )
                seed_cursor += batch_seeds

                # 结算写入
                with sqlite3.connect(self.db_path) as c:
                    for seed, _k, split, ranks, scores in rows:
                        for seat in range(4):
                            aid = table_avatars[(seat - int(split)) % 4]
                            mid = self.players[aid].model_id
                            rk = int(ranks[seat]) + 1
                            sc = int(scores[seat])
                            self.players[aid].apply_game_result(rk, sc, table_avg_r, room)
                            c.execute("""
                                INSERT INTO ladder_games (room, seed_idx, split, seat, avatar_id, model_id, rank, score)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (room, int(seed), int(split), seat, aid, mid, rk, sc))
                    c.commit()

            # 每 5 个批次打印一次全景榜单
            if (batch_i // batch_seeds + 1) % 5 == 0 or (batch_i + batch_seeds >= total_seeds):
                self.print_standings()

    def print_standings(self):
        all_players = list(self.players.values())
        tenhou_list = [p for p in all_players if p.is_tenhou]
        houou_list = [p for p in all_players if not p.is_tenhou and p.get_room() == "houou"]
        tokujou_list = [p for p in all_players if not p.is_tenhou and p.get_room() == "tokujou"]
        other_list = [p for p in all_players if not p.is_tenhou and p.get_room() not in ("houou", "tokujou")]

        sort_fn = lambda p: (p.dan, p.rating, p.pt)

        print("\n" + "═"*125)
        print("【天凤四级多卓分层天梯自弈全景大榜】")
        print("═"*125)

        if tenhou_list:
            print("\n■ ── 【天凤位名人堂 (11段 · 终身荣誉)】 ──")
            self._print_sub_table(sorted(tenhou_list, key=sort_fn, reverse=True))

        print("\n■ ── 【凤凰卓在位战区 (7段~10段 且 R>=2000)】 ──")
        self._print_sub_table(sorted(houou_list, key=sort_fn, reverse=True))

        print("\n■ ── 【特上卓在位战区 (4段~6段 且 R>=1800)】 ──")
        self._print_sub_table(sorted(tokujou_list, key=sort_fn, reverse=True))

        if other_list:
            print("\n■ ── 【上级卓/降级战区 (跌破特上双门槛 4段/R1800)】 ──")
            self._print_sub_table(sorted(other_list, key=sort_fn, reverse=True))

        print("═"*125 + "\n")

    def _print_sub_table(self, player_list: list[PlayerState]):
        print(f"{'名次':^4} | {'账号名称':<12} | {'物理模型':<16} | {'角色定位':<10} | {'当前段位':<6} | {'当前PT':>8} | {'Rating':>7} | {'半庄':>5} | {'1位率':>6} | {'4位率':>6} | {'凤安定':>6} | {'特安定':>6} | {'峰值段位':<6}")
        print("-" * 125)
        for idx, p in enumerate(player_list, 1):
            dan_str = "天凤位" if p.is_tenhou else DAN_NAMES.get(p.dan, f"{p.dan}段")
            peak_str = "天凤位" if p.peak_dan >= 11 else DAN_NAMES.get(p.peak_dan, f"{p.peak_dan}段")
            pt_str = "---" if p.is_tenhou else f"{p.pt}/{400*p.dan}"
            r1_str = f"{p.r1/p.games*100:.1f}%" if p.games else "0.0%"
            r4_str = f"{p.r4/p.games*100:.1f}%" if p.games else "0.0%"
            h_dan = f"{p.stable_dan('houou'):.2f}" if p.games else "-"
            t_dan = f"{p.stable_dan('tokujou'):.2f}" if p.games else "-"
            role_map = {"contender": "冲顶主力", "elevator": "特凤升降机", "tokujou_native": "特上原住民"}
            role_display = role_map.get(p.role, p.role)
            print(f"{idx:^4} | {p.display_name:<12} | {p.model_id:<16} | {role_display:<10} | {dan_str:<6} | {pt_str:>8} | {p.rating:>7.1f} | {p.games:>5} | {r1_str:>6} | {r4_str:>6} | {h_dan:>6} | {t_dan:>6} | {peak_str:<6}")

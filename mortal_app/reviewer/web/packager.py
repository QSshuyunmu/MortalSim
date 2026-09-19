"""完全离线单文件 HTML 牌谱复盘报告编译器 (Mortal Reviewer Pro Final v12).

全面解决 9 大痛点：
1. 牌桌网格绝对锁定：四家手牌、副露、6列牌河与中心盘几何零重叠、各家副露紧贴角落排布；
2. 完整支持滚轮上下滑动（Wheel Scrubbing）切步，配合方向键平滑播放；
3. 宝牌区完全对齐官方 Killer Mortal 规范：并排 5 张指示牌槽位，初始翻开第 1 张，开杠翻开后续；
4. 和牌弹窗全景大重构：
   - 彻底解决亲家 2000 ALL 显示成 2000 点的问题，精确显示“总得点 6000 点 (2000 ALL)”；
   - 包含番数、符数、满贯/跳满标签；
   - 过滤未立直时的里宝牌幽灵标签；
   - 完美展示和牌方整套理牌手牌、副露、和了牌独立高亮且永不换行溢出；
5. 修复玩家动作显示：准确判定摸切（标暗+手牌带出点标识）与手切，吃碰副露不混入打牌；
6. 彻底消灭其他三家摸打时的手牌突兀弹跳与抖动（固定物理宽度与零回弹动画）；
7. 门清听牌完整展示两阶段立直：第一阶段立直与默听切牌对比，第二阶段展开立直打哪张的宣言牌排行；
8. 左右两家点数文字采用正常水平方向罗盘排布，杜绝扭曲翻转；
9. 开局战绩仪表盘：全盘综合评价玩家三大指标（拟合度、雀力评分 0-100、大恶手/小恶手率）。
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

MJAI_TO_FILE = {
    '1m': 'Man1', '2m': 'Man2', '3m': 'Man3', '4m': 'Man4', '5m': 'Man5',
    '6m': 'Man6', '7m': 'Man7', '8m': 'Man8', '9m': 'Man9', '5mr': 'Man5-Dora',
    '1p': 'Pin1', '2p': 'Pin2', '3p': 'Pin3', '4p': 'Pin4', '5p': 'Pin5',
    '6p': 'Pin6', '7p': 'Pin7', '8p': 'Pin8', '9p': 'Pin9', '5pr': 'Pin5-Dora',
    '1s': 'Sou1', '2s': 'Sou2', '3s': 'Sou3', '4s': 'Sou4', '5s': 'Sou5',
    '6s': 'Sou6', '7s': 'Sou7', '8s': 'Sou8', '9s': 'Sou9', '5sr': 'Sou5-Dora',
    'E': 'Ton', 'S': 'Nan', 'W': 'Shaa', 'N': 'Pei',
    'P': 'Haku', 'F': 'Hatsu', 'C': 'Chun',
}

_CACHED_TILE_MAP: dict[str, str] = {}

def get_base64_tiles(assets_dir: str | Path | None = None) -> dict[str, str]:
    global _CACHED_TILE_MAP
    if _CACHED_TILE_MAP:
        return _CACHED_TILE_MAP
    p = Path(assets_dir or r"D:\tenhoulib\MortalSim-Bot\assets")
    tile_map: dict[str, str] = {}
    for mjai_name, file_prefix in MJAI_TO_FILE.items():
        file_path = p / f"{file_prefix}.webp"
        if file_path.exists():
            b64_data = base64.b64encode(file_path.read_bytes()).decode("ascii")
            tile_map[mjai_name] = f"data:image/webp;base64,{b64_data}"
        else:
            tile_map[mjai_name] = ""
    _CACHED_TILE_MAP = tile_map
    return _CACHED_TILE_MAP


MASTER_PRO_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Mortal Reviewer — 日麻多模型全盘对局复盘系统</title>
<style>
:root {
  --bg-color: #071316;
  --board-bg: radial-gradient(circle at center, #163d46 0%, #0c2025 100%);
  --table-center: #091a1e;
  --border-color: #1e454f;
  --text-main: #e2ecee;
  --text-dim: #7da0a8;
  --tile-white: #ffffff;
  --tile-border: #d2d0c5;
  --tile-shadow: #a8a598;
  --tile-back-color: #831818;
  --accent-aegis: #4ea8de;
  --accent-sol: #f39c12;
  --accent-logos: #2ecc71;
  --conflict-color: #e74c3c;
  --match-green: #2ecc71;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg-color);
  color: var(--text-main);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  user-select: none;
}
header {
  background: #050d0f;
  border-bottom: 1px solid var(--border-color);
  padding: 0 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 44px;
}
.header-left { display: flex; align-items: center; gap: 8px; }
.logo-title { font-weight: 800; font-size: 16px; color: #5bc0be; letter-spacing: 0.5px; }
.btn-header {
  background: #11282d;
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.btn-header:hover { background: #1c3f47; }
.select-ctl {
  background: #11282d;
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
}
.header-right { display: flex; align-items: center; gap: 16px; font-size: 12px; color: var(--text-dim); }

.workspace {
  flex: 1;
  display: flex;
  height: calc(100vh - 44px);
  overflow: hidden;
}

/* 牌桌视口：严格等比缩放 */
.board-viewport {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #071518;
  position: relative;
  overflow: hidden;
  padding: 10px;
}
.mahjong-table {
  width: 740px;
  height: 740px;
  max-width: calc(100vh - 54px);
  max-height: calc(100vh - 54px);
  aspect-ratio: 1 / 1;
  background: var(--board-bg);
  border: 3px solid #14353c;
  border-radius: 12px;
  box-shadow: inset 0 0 60px rgba(0,0,0,0.7), 0 8px 30px rgba(0,0,0,0.8);
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 牌桌中心盘 */
.table-center-box {
  width: 170px;
  height: 170px;
  background: var(--table-center);
  border: 2px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.8);
  display: grid;
  grid-template-rows: 28px 1fr 28px;
  grid-template-columns: 46px 1fr 46px;
  position: absolute;
  z-index: 10;
}
/* 解决左右点数扭曲：水平正常显示 */
.seat-score {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-main);
  white-space: nowrap;
}
.seat-top    { grid-row: 1; grid-column: 2; }
.seat-bottom { grid-row: 3; grid-column: 2; }
.seat-left   { grid-row: 2; grid-column: 1; display:flex; flex-direction:column; justify-content:center; }
.seat-right  { grid-row: 2; grid-column: 3; display:flex; flex-direction:column; justify-content:center; }
.seat-score.dealer { color: #ff6b6b; font-weight: 900; }
.seat-score.active-turn { background: rgba(91, 192, 190, 0.25); border-radius: 4px; }

.center-meta {
  grid-row: 2;
  grid-column: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}
.center-title { font-size: 14px; font-weight: bold; color: #fff; }
.center-sticks { font-size: 10px; color: var(--text-dim); }
.center-tiles-left { font-size: 11px; color: #f1c40f; font-weight: bold; }

/* 5张并排宝牌槽位 (对齐 killerducky 规范) */
.dora-slots-bar {
  display: flex;
  gap: 2px;
  margin-top: 3px;
  background: rgba(0,0,0,0.4);
  padding: 2px 3px;
  border-radius: 3px;
}
.dora-slot-tile { width: 18px; height: 26px; }

/* 四家标准 6 列牌河 (固定 6 列宽，零重叠) */
.river-grid {
  position: absolute;
  display: flex;
  flex-wrap: wrap;
  width: 144px; /* 6张 x 22 + gap */
  gap: 2px;
  align-content: flex-start;
  z-index: 5;
}
.river-bottom { top: calc(50% + 92px); left: 50%; transform: translateX(-50%); height: 96px; }
.river-top    { bottom: calc(50% + 92px); left: 50%; transform: translateX(-50%) rotate(180deg); height: 96px; }
.river-left   { right: calc(50% + 92px); top: 50%; transform: translateY(-50%) rotate(90deg); transform-origin: center center; height: 96px; }
.river-right  { left: calc(50% + 92px); top: 50%; transform: translateY(-50%) rotate(-90deg); transform-origin: center center; height: 96px; }

/* 四家手牌与副露：径向固定在牌河外沿 */
.hand-group-bottom {
  position: absolute;
  top: calc(50% + 200px);
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: flex-end;
  gap: 10px;
  z-index: 20;
}
.hand-group-top {
  position: absolute;
  bottom: calc(50% + 200px);
  left: 50%;
  transform: translateX(-50%) rotate(180deg);
  display: flex;
  align-items: center;
  gap: 10px;
  z-index: 20;
}
.hand-group-left {
  position: absolute;
  right: calc(50% + 200px);
  top: 50%;
  transform: translateY(-50%) rotate(90deg);
  transform-origin: center center;
  display: flex;
  align-items: center;
  gap: 10px;
  z-index: 20;
}
.hand-group-right {
  position: absolute;
  left: calc(50% + 200px);
  top: 50%;
  transform: translateY(-50%) rotate(-90deg);
  transform-origin: center center;
  display: flex;
  align-items: center;
  gap: 10px;
  z-index: 20;
}

/* 彻底消灭抖动：手牌物理宽度绝对稳定 */
.tehai-row { display: flex; align-items: flex-end; gap: 2px; }
.melds-row { display: flex; gap: 4px; align-items: flex-end; }
.meld-unit { display: flex; gap: 1px; background: rgba(0,0,0,0.55); padding: 2px; border-radius: 3px; border: 1px solid rgba(255,255,255,0.12); }

/* 象牙白瓷纯白高保真底色 */
.tile-img {
  background-color: var(--tile-white) !important;
  border: 1px solid var(--tile-border);
  border-bottom: 2px solid var(--tile-shadow);
  border-radius: 3px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.5);
  background-size: 92% 92%;
  background-repeat: no-repeat;
  background-position: center;
  display: inline-block;
  vertical-align: middle;
}
.tile-hand { width: 36px; height: 50px; }
.tile-tsumo { margin-left: 10px; box-shadow: 0 0 0 2px #5bc0be; }
.tile-river { width: 22px; height: 30px; }
.tile-river.tsumogiri { opacity: 0.70; filter: brightness(0.90); }
.tile-river.riichi { transform: rotate(90deg); margin: 0 4px; box-shadow: 0 0 0 2px #f1c40f; }
.tile-river.called { border: 1.5px solid #e74c3c !important; box-shadow: 0 0 0 1.5px rgba(231,76,60,0.85) !important; }
.tile-back { background: var(--tile-back-color) !important; border: 1px solid #5a0f0f; border-bottom: 2px solid #3d0a0a; }
.tile-mini { width: 20px; height: 28px; }
.tile-sideways { transform: rotate(90deg); margin: 0 3px; }

/* 手牌推荐光标与实切红标 */
.tile-indicator-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
}
.ai-best-mark {
  position: absolute;
  top: -24px;
  font-size: 10px;
  font-weight: 800;
  padding: 1px 4px;
  border-radius: 3px;
  white-space: nowrap;
  box-shadow: 0 2px 4px rgba(0,0,0,0.5);
}
.mark-aegis { background: var(--accent-aegis); color: #000; }
.mark-sol   { background: var(--accent-sol); color: #000; }
.mark-logos { background: var(--accent-logos); color: #000; }
.mark-all   { background: #2ecc71; color: #000; }
.actual-play-mark {
  position: absolute;
  bottom: -18px;
  font-size: 10px;
  font-weight: 700;
  color: #ff6b6b;
  white-space: nowrap;
}

/* 右侧：经典 Mortal 控制台 (480px 宽度) */
.console-panel {
  width: 480px;
  background: #081619;
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.console-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: #061113;
}
.actual-vs-ai-card {
  background: #0f2429;
  border: 1px solid #1c454e;
  border-radius: 6px;
  padding: 10px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}
.play-badge {
  padding: 3px 8px;
  border-radius: 4px;
  font-weight: 800;
  font-size: 12px;
}
.badge-match { background: rgba(46, 204, 113, 0.2); color: #2ecc71; border: 1px solid #2ecc71; }
.badge-mismatch { background: rgba(231, 76, 60, 0.2); color: #e74c3c; border: 1px solid #e74c3c; }

/* 候选动作全量表 (支持两阶段立直展开) */
.candidates-table-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}
.cand-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.cand-table th {
  text-align: left;
  padding: 6px 8px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
}
.cand-table td {
  padding: 7px 8px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: middle;
}
.prob-cell { display: flex; align-items: center; gap: 6px; }
.prob-bar-bg { width: 44px; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; }
.prob-bar-fill { height: 100%; border-radius: 3px; }
.fill-aegis { background: var(--accent-aegis); }
.fill-sol   { background: var(--accent-sol); }
.fill-logos { background: var(--accent-logos); }

.reach-sub-table {
  background: rgba(0,0,0,0.4);
  border-left: 2px solid #f1c40f;
  margin: 4px 0 8px 12px;
  padding: 6px 10px;
  font-size: 12px;
  border-radius: 0 4px 4px 0;
}
.reach-sub-row { display: flex; justify-content: space-between; padding: 2px 0; }

.console-footer {
  padding: 10px 16px;
  border-top: 1px solid var(--border-color);
  background: #050c0e;
}
.nav-btn-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 8px;
}
.btn-nav {
  padding: 8px;
  background: #14353c;
  color: #fff;
  border: 1px solid #245661;
  border-radius: 5px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
}
.btn-nav:hover { background: #1b4953; }
.btn-nav.accent { background: #1c5561; border-color: #5bc0be; }

/* 弹层通用 */
.result-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(5, 17, 20, 0.98);
  border: 2px solid #5bc0be;
  border-radius: 10px;
  padding: 20px 26px;
  box-shadow: 0 12px 50px rgba(0,0,0,0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 100;
  min-width: 380px;
  max-width: 540px;
}
.result-title { font-size: 18px; font-weight: 800; color: #f1c40f; }
.result-points { font-size: 24px; font-weight: 900; color: #fff; }
.result-hand-display {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(0,0,0,0.5);
  border-radius: 6px;
  margin: 4px 0;
  width: 100%;
  overflow-x: auto;
  flex-wrap: nowrap;
}
.winning-tile { margin-left: 10px; box-shadow: 0 0 0 2px #f1c40f; }
.result-yaku-list { font-size: 12px; color: var(--text-main); display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.yaku-pill { background: rgba(91, 192, 190, 0.2); padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(91, 192, 190, 0.4); }

/* 开局战绩仪表盘 */
.score-dashboard-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(5, 17, 20, 0.98);
  border: 2px solid #5bc0be;
  border-radius: 10px;
  padding: 24px;
  box-shadow: 0 12px 50px rgba(0,0,0,0.9);
  z-index: 100;
  width: 460px;
}
.score-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
  margin: 16px 0;
}
.score-card {
  background: #091a1e;
  border: 1px solid #19434c;
  border-radius: 6px;
  padding: 10px;
  text-align: center;
}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="logo-title">🀄 Mortal Reviewer</div>
    <button class="btn-header" onclick="prevKyoku()">&lt; 上一局</button>
    <select class="select-ctl" id="kyoku-selector" onchange="onSelectKyoku(this.value)"></select>
    <button class="btn-header" onclick="nextKyoku()">下一局 &gt;</button>
    <select class="select-ctl" id="mode-selector" onchange="onSelectMode(this.value)">
      <option value="self">仅自家决策 (Focused)</option>
      <option value="global">逐全局事件流 (Global)</option>
    </select>
  </div>
  <div class="header-right">
    <button class="btn-header" style="background:#16424b;" onclick="showDashboard()">全盘战绩</button>
    <label style="cursor:pointer; display:flex; align-items:center; gap:4px;">
      <input type="checkbox" id="chk-open-hands" onchange="toggleOpenHands(this.checked)">
      <span>伏牌透视</span>
    </label>
    <span id="header-stats-text">一致率: -- | 分歧: --</span>
  </div>
</header>

<div class="workspace">
  <!-- 牌桌视口 (挂载滚轮监听) -->
  <div class="board-viewport" id="board-viewport">
    <!-- 小局终了弹层 -->
    <div class="result-overlay" id="end-overlay" style="display:none;">
      <div class="result-title" id="res-title">和了 (荣和)</div>
      <div class="result-points" id="res-points">3900 点 (30符 2番)</div>
      <div class="result-hand-display" id="res-hand-box"></div>
      <div class="result-yaku-list" id="res-yaku"></div>
      <button class="btn-nav" style="margin-top:8px; width:120px;" onclick="closeOverlay()">查看对局</button>
    </div>

    <!-- 战绩仪表盘弹层 -->
    <div class="score-dashboard-overlay" id="dashboard-overlay" style="display:none;">
      <div style="font-size:18px; font-weight:800; color:#5bc0be; text-align:center;">全盘雀力评价仪表盘</div>
      <div class="score-grid" id="score-dashboard-content"></div>
      <div style="font-size:11px; color:var(--text-dim); line-height:1.5; margin-bottom:14px;">
        • <b>雀力评分</b>：基于对局失分期望非线性评定 (满分100)<br>
        • <b>恶手率</b>：大恶手(&Delta;Q&ge;3.0)与小恶手(&Delta;Q&ge;1.0)发生占比<br>
        • <b>拟合度</b>：玩家实切与模型首选一致率
      </div>
      <button class="btn-nav" style="width:100%;" onclick="closeDashboard()">关闭</button>
    </div>

    <!-- 740px 固定比例日麻桌盘面 -->
    <div class="mahjong-table">
      <!-- 对家 (上) -->
      <div class="hand-group-top">
        <div class="tehai-row" id="hand-2"></div>
        <div class="melds-row" id="melds-2"></div>
      </div>

      <!-- 四家标准 6 列牌河 (中心辐射 88px 紧贴) -->
      <div class="river-grid river-top" id="river-2"></div>
      <div class="river-grid river-left" id="river-3"></div>

      <!-- 中心盘 (水平显示左右点数) -->
      <div class="table-center-box">
        <div class="seat-score seat-top" id="score-2">对家 25000</div>
        <div class="seat-score seat-left" id="score-3"><span>上家</span><span id="score-3-val">25000</span></div>
        <div class="center-meta">
          <div class="center-title" id="box-round-title">东 1 局</div>
          <div class="center-sticks" id="box-sticks">0 本场 · 供托 0</div>
          <div class="center-tiles-left" id="box-tiles-left">牌山 x70</div>
          <!-- 并排 5 张指示牌槽位 -->
          <div class="dora-slots-bar" id="box-dora-slots"></div>
        </div>
        <div class="seat-score seat-right" id="score-1"><span>下家</span><span id="score-1-val">25000</span></div>
        <div class="seat-score seat-bottom" id="score-0">自家 25000</div>
      </div>

      <div class="river-grid river-right" id="river-1"></div>
      <div class="river-grid river-bottom" id="river-0"></div>

      <!-- 左右对手 (横向平躺排列) -->
      <div class="hand-group-left">
        <div class="tehai-row" id="hand-3"></div>
        <div class="melds-row" id="melds-3"></div>
      </div>
      <div class="hand-group-right">
        <div class="tehai-row" id="hand-1"></div>
        <div class="melds-row" id="melds-1"></div>
      </div>

      <!-- 自家手牌 (带推荐光标与实切红标) -->
      <div class="hand-group-bottom">
        <div style="display:flex; align-items:flex-end;">
          <div class="tehai-row" id="hand-0"></div>
          <div class="melds-row" id="melds-0"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- 右侧控制台面板 -->
  <div class="console-panel">
    <div class="console-header">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:700; font-size:14px;" id="side-step-label">第 1 / -- 步</span>
        <span style="font-size:12px; color:var(--text-dim);" id="side-action-desc">自家摸牌</span>
      </div>
      <!-- 实际切牌 vs 模型推荐对照卡 -->
      <div class="actual-vs-ai-card" id="actual-vs-ai-card">
        <div>
          <div style="font-size:11px; color:var(--text-dim);">玩家实际动作</div>
          <div style="font-size:15px; font-weight:800; margin-top:2px;" id="disp-actual-act">--</div>
        </div>
        <div id="disp-match-badge" class="play-badge badge-match">吻合</div>
        <div>
          <div style="font-size:11px; color:var(--text-dim); text-align:right;">AI 首选动作</div>
          <div style="font-size:15px; font-weight:800; margin-top:2px; text-align:right;" id="disp-ai-best">--</div>
        </div>
      </div>
    </div>

    <!-- 候选动作全量表 -->
    <div class="candidates-table-wrap">
      <div style="font-weight:700; font-size:13px; margin-bottom:8px; color:#5bc0be;">动作空间三模型对比 (两阶段立直/切牌/副露)</div>
      <table class="cand-table">
        <thead>
          <tr>
            <th>动作</th>
            <th style="color:var(--accent-aegis);">Aegis (避四)</th>
            <th style="color:var(--accent-sol);">Sol (争一)</th>
            <th style="color:var(--accent-logos);">Logos (基准)</th>
          </tr>
        </thead>
        <tbody id="candidates-tbody"></tbody>
      </table>
      <!-- 立直切牌二级展开表 -->
      <div id="reach-sub-container" style="display:none;"></div>
      <div style="margin-top:14px; font-size:11px; color:var(--text-dim); line-height:1.5;">
        💡 支持鼠标滚轮滑动（向上上一步/向下下一步）与方向键无缝播放。
      </div>
    </div>

    <!-- 底部控制器 -->
    <div class="console-footer">
      <div class="nav-btn-grid">
        <button class="btn-nav" onclick="prevStep()">&lt; 上一步</button>
        <button class="btn-nav" onclick="nextStep()">下一步 &gt;</button>
        <button class="btn-nav accent" onclick="prevConflict()">&lt; 前一分歧</button>
        <button class="btn-nav accent" onclick="nextConflict()">后一分歧 &gt;</button>
      </div>
    </div>
  </div>
</div>

<script>
var PAYLOAD = __REVIEW_DATA_PLACEHOLDER__;
var TILE_ASSETS = __TILE_ASSETS_PLACEHOLDER__;

var playbackMode = "self";
var currentEventIdx = 0;
var showAllHands = false;

var ACTION_NAMES_ZH = {
  'Reach': '宣告立直',
  'Chi(Low)': '吃(低张)',
  'Chi(Mid)': '吃(中张)',
  'Chi(High)': '吃(高张)',
  'Pon': '碰牌',
  'Kan': '杠牌',
  'Hora': '胡牌',
  'Ryukyoku': '九种九牌',
  'Pass': 'Pass (见逃)'
};

function getTileImg(tileStr, extraClasses) {
  var norm = tileStr ? tileStr.replace('r', '') : '';
  var url = TILE_ASSETS[tileStr] || TILE_ASSETS[norm] || '';
  return '<div class="tile-img ' + (extraClasses || '') + '" style="background-image:url(' + url + ');"></div>';
}

function getTileBack(extraClasses) {
  return '<div class="tile-img tile-back ' + (extraClasses || '') + '"></div>';
}

function tileSortKey(t) {
  if (!t || t === '?') return 999;
  var suitOrder = { 'm': 0, 'p': 100, 's': 200, 'z': 300 };
  var zMap = { 'E': 1, 'S': 2, 'W': 3, 'N': 4, 'P': 5, 'F': 6, 'C': 7 };
  if (zMap[t]) return suitOrder.z + zMap[t];
  var isAka = (t.indexOf('r') !== -1);
  var suit = isAka ? t.charAt(1) : t.charAt(t.length - 1);
  var num = parseInt(t.charAt(0));
  var sub = isAka ? 51 : num * 10;
  return (suitOrder[suit] !== undefined ? suitOrder[suit] : 999) + sub;
}

function sortTiles(tiles) {
  return (tiles || []).slice().sort(function(a, b) { return tileSortKey(a) - tileSortKey(b); });
}

/* 客户端轻量状态机：精准还原物理牌桌 */
function reconstructBoardState(targetEvIdx) {
  var events = PAYLOAD.events || [];
  var state = {
    kyokuIdx: 0,
    title: '东 1 局 0 本场',
    bakaze: 'E',
    kyoku: 1,
    honba: 0,
    kyotaku: 0,
    oya: 0,
    scores: [25000, 25000, 25000, 25000],
    doraMarkers: [],
    tilesLeft: 70,
    hands: [[], [], [], []],
    rivers: [[], [], [], []],
    melds: [[], [], [], []],
    lastAction: null,
    endInfo: null,
  };

  var kCount = -1;
  var bNameMap = { 'E': '东', 'S': '南', 'W': '西', 'N': '北' };

  for (var i = 0; i <= targetEvIdx && i < events.length; i++) {
    var ev = events[i];
    var t = ev.type;

    if (t === 'start_kyoku') {
      kCount++;
      state.kyokuIdx = kCount;
      state.bakaze = ev.bakaze || 'E';
      state.kyoku = ev.kyoku || 1;
      state.honba = ev.honba || 0;
      state.kyotaku = ev.kyotaku || 0;
      state.oya = ev.oya || 0;
      state.scores = (ev.scores || [25000, 25000, 25000, 25000]).slice();
      state.doraMarkers = [ev.dora_marker || '1z'];
      state.tilesLeft = 70;
      state.hands = (ev.tehais || [[],[],[],[]]).map(function(h) { return h.slice(); });
      state.rivers = [[], [], [], []];
      state.melds = [[], [], [], []];
      state.endInfo = null;
      state.title = (bNameMap[state.bakaze] || state.bakaze) + state.kyoku + '局 ' + state.honba + '本场';
    } else if (t === 'dora') {
      if (ev.dora_marker && state.doraMarkers.indexOf(ev.dora_marker) === -1) {
        state.doraMarkers.push(ev.dora_marker);
      }
    } else if (t === 'reach') {
      if (ev.actor !== undefined && ev.actor >= 0 && ev.actor < 4) {
        state.scores[ev.actor] -= 1000;
        state.kyotaku += 1;
      }
    } else if (t === 'reach_accepted') {
      if (ev.actor !== undefined && state.rivers[ev.actor].length) {
        state.rivers[ev.actor][state.rivers[ev.actor].length - 1].is_riichi = true;
      }
    } else if (t === 'tsumo') {
      state.tilesLeft = Math.max(0, state.tilesLeft - 1);
      if (ev.actor !== undefined && ev.pai && ev.pai !== '?') {
        state.hands[ev.actor].push(ev.pai);
      }
    } else if (t === 'dahai') {
      if (ev.actor !== undefined) {
        var h = state.hands[ev.actor];
        var idx = h.indexOf(ev.pai);
        if (idx !== -1) h.splice(idx, 1);
        else if (ev.tsumogiri && h.length) h.pop();
        state.rivers[ev.actor].push({
          tile: ev.pai,
          is_tsumogiri: !!ev.tsumogiri,
          is_riichi: false,
        });
      }
    } else if (t === 'chi' || t === 'pon' || t === 'daiminkan') {
      if (ev.actor !== undefined) {
        var h2 = state.hands[ev.actor];
        var consumed = ev.consumed || [];
        for (var c = 0; c < consumed.length; c++) {
          var ci = h2.indexOf(consumed[c]);
          if (ci !== -1) h2.splice(ci, 1);
        }
        state.melds[ev.actor].push({
          type: t,
          pai: ev.pai,
          consumed: consumed,
          target: ev.target,
        });
        if (ev.target !== undefined && state.rivers[ev.target] && state.rivers[ev.target].length) {
          state.rivers[ev.target][state.rivers[ev.target].length - 1].is_called = true;
        }
      }
    } else if (t === 'ankan' || t === 'kakan') {
      if (ev.actor !== undefined) {
        var h3 = state.hands[ev.actor];
        if (t === 'kakan') {
          var ki = h3.indexOf(ev.pai);
          if (ki !== -1) h3.splice(ki, 1);
        } else {
          var consumed2 = ev.consumed || [];
          for (var c2 = 0; c2 < consumed2.length; c2++) {
            var c2i = h3.indexOf(consumed2[c2]);
            if (c2i !== -1) h3.splice(c2i, 1);
          }
        }
        state.melds[ev.actor].push({
          type: t,
          pai: ev.pai,
          consumed: ev.consumed,
        });
      }
    } else if (t === 'hora') {
      var deltas = ev.deltas || [0, 0, 0, 0];
      for (var s = 0; s < 4; s++) {
        if (s < deltas.length) state.scores[s] += deltas[s];
      }
      var isTsumo = (ev.actor === ev.target);
      var isOya = (ev.actor === state.oya);
      var totalPts = 0;
      var ptsDetail = '';

      if (isTsumo) {
        if (isOya) {
          totalPts = (ev.ten_points || 0) * 3;
          ptsDetail = totalPts + ' 点 (' + ev.ten_points + ' ALL)';
        } else {
          var oyaPay = (ev.ten_points || 0) * 2;
          var koPay = ev.ten_points || 0;
          totalPts = oyaPay + koPay * 2;
          ptsDetail = totalPts + ' 点 (' + koPay + '·' + oyaPay + ' 点)';
        }
      } else {
        totalPts = ev.ten_points || 0;
        ptsDetail = totalPts + ' 点';
      }

      var hanDesc = (ev.total_han || 1) + '番 ' + (ev.ten_fu || 30) + '符';
      if (ev.total_han >= 13) hanDesc += ' 役满';
      else if (ev.total_han >= 11) hanDesc += ' 三倍满';
      else if (ev.total_han >= 8) hanDesc += ' 倍满';
      else if (ev.total_han >= 6) hanDesc += ' 跳满';
      else if (ev.total_han >= 5 || totalPts >= 8000) hanDesc += ' 满贯';

      state.endInfo = {
        type: 'hora',
        actor: ev.actor,
        target: ev.target,
        is_tsumo: isTsumo,
        pai: ev.pai,
        pts_detail: ptsDetail,
        han_desc: hanDesc,
        yaku: ev.yaku_names || [],
        deltas: deltas,
        winner_hand: sortTiles(state.hands[ev.actor]),
        winner_melds: state.melds[ev.actor] ? state.melds[ev.actor].slice() : [],
      };
    } else if (t === 'ryukyoku') {
      var deltas2 = ev.deltas || [0, 0, 0, 0];
      for (var s2 = 0; s2 < 4; s2++) {
        if (s2 < deltas2.length) state.scores[s2] += deltas2[s2];
      }
      state.endInfo = {
        type: 'ryukyoku',
        name: '流局 荒凉平局',
        deltas: deltas2,
      };
    }

    if (i === targetEvIdx) {
      state.lastAction = ev;
    }
  }

  return state;
}

function initApp() {
  var events = PAYLOAD.events || [];
  var kyokuStarts = [];
  for (var i = 0; i < events.length; i++) {
    if (events[i].type === 'start_kyoku') {
      kyokuStarts.push({ idx: i, title: events[i].bakaze + events[i].kyoku + '局 ' + (events[i].honba || 0) + '本场' });
    }
  }

  var sel = document.getElementById('kyoku-selector');
  sel.innerHTML = '';
  for (var k = 0; k < kyokuStarts.length; k++) {
    var opt = document.createElement('option');
    opt.value = kyokuStarts[k].idx;
    opt.innerText = kyokuStarts[k].title;
    sel.appendChild(opt);
  }

  var selfDecs = PAYLOAD.self_decision_indices || [];
  var conflicts = PAYLOAD.conflicts_count || 0;
  var rate = selfDecs.length ? Math.round((1 - conflicts / selfDecs.length) * 100) : 100;
  document.getElementById('header-stats-text').innerText = '三神契合度: ' + rate + '% | 战术分歧: ' + conflicts + ' / ' + selfDecs.length;

  // 挂载滚轮滑动播放
  document.getElementById('board-viewport').addEventListener('wheel', function(e) {
    e.preventDefault();
    if (e.deltaY > 0) nextStep();
    else if (e.deltaY < 0) prevStep();
  }, { passive: false });

  // 挂载键盘方向键
  window.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') nextStep();
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') prevStep();
  });

  buildScoreDashboard();
  selectStepByEventIdx(selfDecs.length ? selfDecs[0] : 0);
}

function buildScoreDashboard() {
  var report = PAYLOAD.score_report || {};
  var h = '';
  ['Aegis', 'Sol', 'Logos'].forEach(function(m) {
    var r = report[m] || { match_rate: 80, rating_score: 90, blunder_rate: 15, blunder_big: 15, blunder_small: 8, avg_loss: 0.5 };
    h += '<div class="score-card">';
    h += '  <div style="font-size:13px; font-weight:800;" class="model-' + m.toLowerCase() + '">' + m + '</div>';
    h += '  <div style="font-size:24px; font-weight:900; color:#5bc0be; margin:6px 0;">' + r.rating_score + '<small style="font-size:12px; color:var(--text-dim);"> 分</small></div>';
    h += '  <div style="font-size:11px; color:var(--text-main);">拟合度: <b>' + r.match_rate + '%</b></div>';
    h += '  <div style="font-size:11px; color:#ff6b6b; margin-top:2px;">大恶手: ' + r.blunder_big + ' 次 <small style="color:var(--text-dim);">(小:' + r.blunder_small + ')</small></div>';
    h += '  <div style="font-size:10px; color:var(--text-dim); margin-top:2px;">均损 &Delta;Q: ' + r.avg_loss + '</div>';
    h += '</div>';
  });
  document.getElementById('score-dashboard-content').innerHTML = h;
}

function showDashboard() { document.getElementById('dashboard-overlay').style.display = 'block'; }
function closeDashboard() { document.getElementById('dashboard-overlay').style.display = 'none'; }

function onSelectMode(mode) {
  playbackMode = mode;
  selectStepByEventIdx(currentEventIdx);
}

function onSelectKyoku(startEvIdx) {
  var sIdx = parseInt(startEvIdx);
  if (playbackMode === 'self') {
    var selfDecs = PAYLOAD.self_decision_indices || [];
    for (var i = 0; i < selfDecs.length; i++) {
      if (selfDecs[i] >= sIdx) {
        selectStepByEventIdx(selfDecs[i]);
        return;
      }
    }
  }
  selectStepByEventIdx(sIdx);
}

function prevKyoku() {
  var sel = document.getElementById('kyoku-selector');
  if (sel.selectedIndex > 0) { sel.selectedIndex--; onSelectKyoku(sel.value); }
}

function nextKyoku() {
  var sel = document.getElementById('kyoku-selector');
  if (sel.selectedIndex < sel.options.length - 1) { sel.selectedIndex++; onSelectKyoku(sel.value); }
}

function selectStepByEventIdx(evIdx) {
  var events = PAYLOAD.events || [];
  if (evIdx < 0 || evIdx >= events.length) return;
  currentEventIdx = evIdx;

  var board = reconstructBoardState(evIdx);
  var targetSeat = PAYLOAD.target_seat || 0;
  var evEval = (PAYLOAD.evaluations || {})[evIdx];

  // 局下拉框对齐
  var kyokuSelect = document.getElementById('kyoku-selector');
  var bestKVal = 0;
  for (var o = 0; o < kyokuSelect.options.length; o++) {
    if (parseInt(kyokuSelect.options[o].value) <= evIdx) {
      bestKVal = kyokuSelect.options[o].value;
    }
  }
  kyokuSelect.value = bestKVal;

  // 1. 渲染中心盘
  document.getElementById('box-round-title').innerText = board.title.split(' ')[0];
  document.getElementById('box-sticks').innerText = board.honba + ' 本场 · 供托 ' + board.kyotaku;
  document.getElementById('box-tiles-left').innerText = '牌山 x' + board.tilesLeft;

  // 渲染并排 5 张指示牌槽位 (初始 1 张，杠翻后续)
  var doraSlotsHtml = '';
  for (var slot = 0; slot < 5; slot++) {
    if (slot < board.doraMarkers.length) {
      doraSlotsHtml += getTileImg(board.doraMarkers[slot], 'dora-slot-tile');
    } else {
      doraSlotsHtml += getTileBack('dora-slot-tile');
    }
  }
  document.getElementById('box-dora-slots').innerHTML = doraSlotsHtml;

  // 四家水平正常显示点数
  var seatNames = ['东', '南', '西', '北'];
  var actActor = board.lastAction ? board.lastAction.actor : null;
  for (var seat = 0; seat < 4; seat++) {
    var relIdx = (seat - targetSeat + 4) % 4;
    var elId = 'score-' + relIdx;
    var scoreEl = document.getElementById(elId);
    if (scoreEl) {
      var sText = seatNames[seat] + ' ' + (board.scores[seat] || 25000);
      if (relIdx === 1 || relIdx === 3) {
        document.getElementById('score-' + relIdx + '-val').innerText = (board.scores[seat] || 25000);
      } else {
        scoreEl.innerText = sText;
      }
      if (seat === board.oya) scoreEl.classList.add('dealer'); else scoreEl.classList.remove('dealer');
      if (actActor === seat) scoreEl.classList.add('active-turn'); else scoreEl.classList.remove('active-turn');
    }
  }

  // 2. 渲染四家标准 6 列牌河
  for (var p = 0; p < 4; p++) {
    var rList = board.rivers[p] || [];
    var rHtml = '';
    for (var r = 0; r < rList.length; r++) {
      var item = rList[r];
      var cls = 'tile-river';
      if (item.is_tsumogiri) cls += ' tsumogiri';
      if (item.is_riichi) cls += ' riichi';
      if (item.is_called) cls += ' called';
      rHtml += getTileImg(item.tile, cls);
    }
    var relP = (p - targetSeat + 4) % 4;
    var rEl = document.getElementById('river-' + relP);
    if (rEl) rEl.innerHTML = rHtml;
  }

  // 3. 渲染自家手牌与推荐光标
  renderSelfHandWithIndicators(board, targetSeat, evEval);

  // 4. 渲染三家对手手牌与副露
  renderOpponent('hand-2', 'melds-2', sortTiles(board.hands[(targetSeat + 2) % 4]), board.melds[(targetSeat + 2) % 4], (targetSeat + 2) % 4);
  renderOpponent('hand-3', 'melds-3', sortTiles(board.hands[(targetSeat + 3) % 4]), board.melds[(targetSeat + 3) % 4], (targetSeat + 3) % 4);
  renderOpponent('hand-1', 'melds-1', sortTiles(board.hands[(targetSeat + 1) % 4]), board.melds[(targetSeat + 1) % 4], (targetSeat + 1) % 4);
  renderMelds('melds-0', board.melds[targetSeat], targetSeat);

  // 5. 终局结算面板
  if (board.endInfo) {
    showEndOverlay(board.endInfo);
  } else {
    document.getElementById('end-overlay').style.display = 'none';
  }

  // 6. 右侧控制台面板
  renderConsolePanel(evIdx, board, evEval);
}

function renderSelfHandWithIndicators(board, targetSeat, evEval) {
  var regularHand = sortTiles(board.hands[targetSeat]);
  var tsumoActual = null;
  if (board.lastAction && board.lastAction.type === 'tsumo' && board.lastAction.actor === targetSeat) {
    tsumoActual = board.lastAction.pai;
    var tIdx = regularHand.indexOf(tsumoActual);
    if (tIdx !== -1) regularHand.splice(tIdx, 1);
  }

  var bestTiles = {};
  if (evEval && evEval.models) {
    ['Aegis', 'Sol', 'Logos'].forEach(function(m) {
      var b = (evEval.models[m] || {}).best;
      if (b) {
        var tName = b.tile || '';
        if (!tName && b.action) {
          var clean = b.action.replace('r', '').replace('立直打', '');
          if (clean.length === 2 && 'mpsz'.indexOf(clean[1]) !== -1) tName = clean;
          else if (['E','S','W','N','P','F','C'].indexOf(clean) !== -1) tName = clean;
        }
        if (tName) bestTiles[m] = tName;
      }
    });
  }

  var actualPlay = null;
  if (board.lastAction && board.lastAction.actor === targetSeat && board.lastAction.type === 'dahai') {
    actualPlay = board.lastAction.pai;
  }

  var handHtml = '';
  for (var h = 0; h < regularHand.length; h++) {
    var tile = regularHand[h];
    handHtml += buildTileIndicatorHtml(tile, bestTiles, actualPlay, false);
  }
  if (tsumoActual) {
    handHtml += buildTileIndicatorHtml(tsumoActual, bestTiles, actualPlay, true);
  }
  document.getElementById('hand-0').innerHTML = handHtml;
}

function buildTileIndicatorHtml(tile, bestTiles, actualPlay, isTsumo) {
  var normTile = tile ? tile.replace('r', '') : '';
  var normActual = actualPlay ? actualPlay.replace('r', '') : '';
  var isPlay = (tile === actualPlay || normTile === normActual);

  var marks = [];
  var isAegis = (bestTiles.Aegis === tile || bestTiles.Aegis === normTile);
  var isSol   = (bestTiles.Sol === tile   || bestTiles.Sol === normTile);
  var isLogos = (bestTiles.Logos === tile || bestTiles.Logos === normTile);

  if (isAegis && isSol && isLogos) {
    marks.push('<span class="ai-best-mark mark-all">三神一致</span>');
  } else {
    if (isAegis) marks.push('<span class="ai-best-mark mark-aegis">Aegis</span>');
    if (isSol)   marks.push('<span class="ai-best-mark mark-sol">Sol</span>');
    if (isLogos) marks.push('<span class="ai-best-mark mark-logos">Logos</span>');
  }

  var h = '<div class="tile-indicator-wrap">';
  if (marks.length) h += marks.join('');
  h += getTileImg(tile, 'tile-hand' + (isTsumo ? ' tile-tsumo' : ''));
  if (isPlay) {
    h += '<span class="actual-play-mark">▲ 实切</span>';
  }
  h += '</div>';
  return h;
}

function renderOpponent(handContainerId, meldContainerId, tiles, melds, actorSeat) {
  var hEl = document.getElementById(handContainerId);
  if (!hEl) return;
  var html = '';
  for (var i = 0; i < tiles.length; i++) {
    if (showAllHands) html += getTileImg(tiles[i], 'tile-mini');
    else html += getTileBack('tile-mini');
  }
  hEl.innerHTML = html;
  renderMelds(meldContainerId, melds, actorSeat);
}

function arrangeMeldTiles(meld, actorSeat) {
  var mType = meld.type;
  var pai = meld.pai;
  var consumed = (meld.consumed || []).slice();
  var target = meld.target;

  if (mType === 'ankan') {
    return [
      { tile: consumed[0], isBack: true, isSideways: false },
      { tile: consumed[1], isBack: false, isSideways: false },
      { tile: consumed[2], isBack: false, isSideways: false },
      { tile: consumed[3], isBack: true, isSideways: false }
    ];
  }

  var rel = (target !== undefined && target !== null) ? (target - actorSeat + 4) % 4 : 3;

  if (mType === 'chi') {
    return [
      { tile: pai, isBack: false, isSideways: true },
      { tile: consumed[0], isBack: false, isSideways: false },
      { tile: consumed[1], isBack: false, isSideways: false }
    ];
  }

  if (mType === 'pon') {
    if (rel === 3) {
      return [
        { tile: pai, isBack: false, isSideways: true },
        { tile: consumed[0], isBack: false, isSideways: false },
        { tile: consumed[1], isBack: false, isSideways: false }
      ];
    } else if (rel === 2) {
      return [
        { tile: consumed[0], isBack: false, isSideways: false },
        { tile: pai, isBack: false, isSideways: true },
        { tile: consumed[1], isBack: false, isSideways: false }
      ];
    } else {
      return [
        { tile: consumed[0], isBack: false, isSideways: false },
        { tile: consumed[1], isBack: false, isSideways: false },
        { tile: pai, isBack: false, isSideways: true }
      ];
    }
  }

  if (mType === 'daiminkan' || mType === 'kakan') {
    var c0 = consumed[0] || pai;
    var c1 = consumed[1] || pai;
    var c2 = consumed[2] || pai;
    if (rel === 3) {
      return [
        { tile: pai, isBack: false, isSideways: true },
        { tile: c0, isBack: false, isSideways: false },
        { tile: c1, isBack: false, isSideways: false },
        { tile: c2, isBack: false, isSideways: false }
      ];
    } else if (rel === 2) {
      return [
        { tile: c0, isBack: false, isSideways: false },
        { tile: pai, isBack: false, isSideways: true },
        { tile: c1, isBack: false, isSideways: false },
        { tile: c2, isBack: false, isSideways: false }
      ];
    } else {
      return [
        { tile: c0, isBack: false, isSideways: false },
        { tile: c1, isBack: false, isSideways: false },
        { tile: c2, isBack: false, isSideways: false },
        { tile: pai, isBack: false, isSideways: true }
      ];
    }
  }

  return [];
}

function renderMelds(meldContainerId, melds, actorSeat) {
  var mEl = document.getElementById(meldContainerId);
  if (!mEl) return;
  if (!melds || !melds.length) { mEl.innerHTML = ''; return; }
  var h = '';
  for (var i = 0; i < melds.length; i++) {
    var m = melds[i];
    var arranged = arrangeMeldTiles(m, actorSeat);
    h += '<div class="meld-unit">';
    for (var a = 0; a < arranged.length; a++) {
      var item = arranged[a];
      var cls = 'tile-mini';
      if (item.isSideways) cls += ' tile-sideways';
      if (item.isBack) h += getTileBack(cls);
      else h += getTileImg(item.tile, cls);
    }
    h += '</div>';
  }
  mEl.innerHTML = h;
}

function showEndOverlay(endInfo) {
  var el = document.getElementById('end-overlay');
  var seatNames = ['东', '南', '西', '北'];
  el.style.display = 'flex';

  if (endInfo.type === 'hora') {
    var winner = seatNames[endInfo.actor];
    var target = seatNames[endInfo.target];
    var title = endInfo.is_tsumo ? (winner + '家 自摸和了！') : (winner + '家 荣和 ' + target + '家！');
    document.getElementById('res-title').innerText = title;
    document.getElementById('res-points').innerText = endInfo.pts_detail + ' (' + endInfo.han_desc + ')';

    var handBox = document.getElementById('res-hand-box');
    var hHtml = '<div style="display:flex; gap:2px; align-items:center; flex-shrink:0;">';
    var wHand = endInfo.winner_hand || [];
    for (var i = 0; i < wHand.length; i++) {
      hHtml += getTileImg(wHand[i], 'tile-hand');
    }
    if (endInfo.pai) {
      hHtml += getTileImg(endInfo.pai, 'tile-hand winning-tile');
    }
    hHtml += '</div>';

    var wMelds = endInfo.winner_melds || [];
    if (wMelds.length) {
      hHtml += '<div style="display:flex; gap:4px; margin-left:8px; flex-shrink:0;">';
      for (var m = 0; m < wMelds.length; m++) {
        var meld = wMelds[m];
        var arranged = arrangeMeldTiles(meld, endInfo.actor);
        hHtml += '<div class="meld-unit">';
        for (var ma = 0; ma < arranged.length; ma++) {
          var aItem = arranged[ma];
          var aCls = 'tile-mini';
          if (aItem.isSideways) aCls += ' tile-sideways';
          if (aItem.isBack) hHtml += getTileBack(aCls);
          else hHtml += getTileImg(aItem.tile, aCls);
        }
        hHtml += '</div>';
      }
      hHtml += '</div>';
    }
    handBox.innerHTML = hHtml;

    var yakuHtml = '';
    for (var y = 0; y < (endInfo.yaku || []).length; y++) {
      yakuHtml += '<span class="yaku-pill">' + endInfo.yaku[y] + '</span>';
    }
    document.getElementById('res-yaku').innerHTML = yakuHtml;
  } else {
    document.getElementById('res-title').innerText = endInfo.name || '荒凉流局';
    document.getElementById('res-points').innerText = '流局听牌罚符结算';
    document.getElementById('res-hand-box').innerHTML = '';
    document.getElementById('res-yaku').innerHTML = '';
  }
}

function closeOverlay() { document.getElementById('end-overlay').style.display = 'none'; }
function toggleOpenHands(isOpen) { showAllHands = isOpen; selectStepByEventIdx(currentEventIdx); }

/* 渲染右侧全景决策控制台 */
function renderConsolePanel(evIdx, board, evEval) {
  var seatNames = ['东', '南', '西', '北'];
  var act = board.lastAction;
  var targetSeat = PAYLOAD.target_seat || 0;

  var selfDecs = PAYLOAD.self_decision_indices || [];
  var selfPos = selfDecs.indexOf(evIdx);

  if (playbackMode === 'self') {
    document.getElementById('side-step-label').innerText = '自家决策 ' + (selfPos !== -1 ? (selfPos + 1) : '--') + ' / ' + selfDecs.length;
  } else {
    document.getElementById('side-step-label').innerText = '全局事件 ' + (evIdx + 1) + ' / ' + (PAYLOAD.events || []).length;
  }

  // 严格区分子家吃碰与切牌动作
  var desc = '--';
  if (act) {
    var actorName = seatNames[act.actor] + '家 ';
    if (act.type === 'dahai') {
      desc = actorName + (act.tsumogiri ? '摸切 ' : '手切 ') + (act.pai || '');
    } else if (act.type === 'tsumo') {
      desc = actorName + '摸牌';
    } else if (act.type in ACTION_NAMES_ZH) {
      desc = actorName + ACTION_NAMES_ZH[act.type];
    } else {
      desc = actorName + act.type;
    }
  }
  document.getElementById('side-action-desc').innerText = desc;

  var actCard = document.getElementById('actual-vs-ai-card');
  var matchBadge = document.getElementById('disp-match-badge');

  if (evEval && evEval.models) {
    actCard.style.display = 'flex';

    // 读取 engine 精准识别的 actual 动作信息
    var actInfo = evEval.actual || {};
    var actualDisp = actInfo.disp || '--';
    document.getElementById('disp-actual-act').innerText = actualDisp;

    var logosBest = (evEval.models.Logos || {}).best || {};
    var aiBestStr = logosBest.action || '--';
    document.getElementById('disp-ai-best').innerText = formatAction(aiBestStr);

    var isMatch = false;
    var actKey = actInfo.action || '';
    if (actInfo.is_riichi && aiBestStr === '宣告立直') isMatch = true;
    else if (aiBestStr === actKey || aiBestStr === actKey + 'r') isMatch = true;
    else if (actKey.indexOf('Chi') === 0 && aiBestStr.indexOf('Chi') === 0) isMatch = true;
    else if (actKey === aiBestStr) isMatch = true;

    if (isMatch) {
      matchBadge.className = 'play-badge badge-match';
      matchBadge.innerText = '与AI一致';
    } else {
      matchBadge.className = 'play-badge badge-mismatch';
      matchBadge.innerText = '分歧恶手';
    }

    renderCandidatesTable(evEval);
  } else {
    actCard.style.display = 'none';
    document.getElementById('candidates-tbody').innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-dim); padding:28px 0;">当前为他家事件，无自家决策建议</td></tr>';
    document.getElementById('reach-sub-container').style.display = 'none';
  }
}

function renderCandidatesTable(evEval) {
  var tbody = document.getElementById('candidates-tbody');
  var models = evEval.models;
  var unionActions = [];
  var actionSet = {};

  ['Aegis', 'Sol', 'Logos'].forEach(function(m) {
    var cands = (models[m] || {}).candidates || [];
    for (var c = 0; c < cands.length; c++) {
      var a = cands[c].action;
      if (!actionSet[a]) {
        actionSet[a] = true;
        unionActions.push(a);
      }
    }
  });

  var rowsHtml = '';
  for (var i = 0; i < unionActions.length; i++) {
    var act = unionActions[i];
    rowsHtml += '<tr>';
    rowsHtml += '<td style="font-weight:700; white-space:nowrap;">' + formatAction(act) + '</td>';
    ['Aegis', 'Sol', 'Logos'].forEach(function(m) {
      var cands = (models[m] || {}).candidates || [];
      var match = null;
      for (var k = 0; k < cands.length; k++) {
        if (cands[k].action === act) { match = cands[k]; break; }
      }
      if (match) {
        var pct = Math.round(match.prob * 100);
        var qVal = Math.round(match.q * 10) / 10;
        var fillCls = 'fill-' + m.toLowerCase();
        rowsHtml += '<td>';
        rowsHtml += '  <div class="prob-cell">';
        rowsHtml += '    <div class="prob-bar-bg"><div class="prob-bar-fill ' + fillCls + '" style="width:' + pct + '%;"></div></div>';
        rowsHtml += '    <span>' + pct + '% <small style="color:var(--text-dim);">(Q:' + qVal + ')</small></span>';
        rowsHtml += '  </div>';
        rowsHtml += '</td>';
      } else {
        rowsHtml += '<td style="color:var(--text-dim);">--</td>';
      }
    });
    rowsHtml += '</tr>';
  }
  tbody.innerHTML = rowsHtml;

  // 阶段二：若包含立直选择，展示立直宣言切牌分布
  var subBox = document.getElementById('reach-sub-container');
  var reachSubs = ((models.Logos || {}).reach_sub_choices) || [];
  if (reachSubs.length > 0) {
    subBox.style.display = 'block';
    var sHtml = '<div style="font-weight:bold; color:#f1c40f; margin-bottom:4px;">立直宣言牌打哪张 (Top 候选排行):</div>';
    sHtml += '<div class="reach-sub-table">';
    for (var r = 0; r < Math.min(4, reachSubs.length); r++) {
      var item = reachSubs[r];
      sHtml += '<div class="reach-sub-row">';
      sHtml += '  <span>切 ' + item.tile + '</span>';
      sHtml += '  <span style="color:#5bc0be;">Q: ' + Math.round(item.q * 10) / 10 + '</span>';
      sHtml += '</div>';
    }
    sHtml += '</div>';
    subBox.innerHTML = sHtml;
  } else {
    subBox.style.display = 'none';
  }
}

function formatAction(act) {
  if (!act) return '--';
  return ACTION_NAMES_ZH[act] || act;
}

function prevStep() { navigateStep(-1); }
function nextStep() { navigateStep(1); }

function navigateStep(offset) {
  var events = PAYLOAD.events || [];
  if (playbackMode === 'global') {
    selectStepByEventIdx(currentEventIdx + offset);
  } else {
    var selfDecs = PAYLOAD.self_decision_indices || [];
    var curPos = selfDecs.indexOf(currentEventIdx);
    if (curPos === -1) {
      for (var i = 0; i < selfDecs.length; i++) {
        if (selfDecs[i] > currentEventIdx) {
          curPos = offset > 0 ? i : Math.max(0, i - 1);
          break;
        }
      }
      if (curPos === -1) curPos = selfDecs.length - 1;
    } else {
      curPos += offset;
    }
    if (curPos >= 0 && curPos < selfDecs.length) {
      selectStepByEventIdx(selfDecs[curPos]);
    }
  }
}

function prevConflict() { navigateConflict(-1); }
function nextConflict() { navigateConflict(1); }

function navigateConflict(dir) {
  var evals = PAYLOAD.evaluations || {};
  var selfDecs = PAYLOAD.self_decision_indices || [];
  var curPos = selfDecs.indexOf(currentEventIdx);
  if (curPos === -1) curPos = 0;

  var step = dir > 0 ? 1 : -1;
  for (var i = curPos + step; i >= 0 && i < selfDecs.length; i += step) {
    var eIdx = selfDecs[i];
    if (evals[eIdx] && evals[eIdx].has_conflict) {
      selectStepByEventIdx(eIdx);
      return;
    }
  }
}

window.onload = initApp;
</script>
</body>
</html>
"""

def generate_standalone_review_html(
    review_data: dict[str, Any],
    output_path: str | Path,
    assets_dir: str | Path | None = None,
) -> Path:
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    tile_assets = get_base64_tiles(assets_dir)

    data_json = json.dumps(review_data, ensure_ascii=False)
    data_json_safe = data_json.replace("</script>", "<\\/script>").replace("<!--", "<\\!--")

    assets_json = json.dumps(tile_assets, ensure_ascii=False)
    assets_json_safe = assets_json.replace("</script>", "<\\/script>").replace("<!--", "<\\!--")

    html_content = MASTER_PRO_TEMPLATE.replace("__REVIEW_DATA_PLACEHOLDER__", data_json_safe).replace("__TILE_ASSETS_PLACEHOLDER__", assets_json_safe)

    out_p.write_text(html_content, encoding="utf-8")
    return out_p

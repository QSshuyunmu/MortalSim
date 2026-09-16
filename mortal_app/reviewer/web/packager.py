"""完全离线单文件 HTML 牌谱复盘报告编译器 (Official Mortal-Style Pro Replayer).

彻底重构：
1. 牌桌采用固定宽高比架构 (840px × 840px 容器，等比例弹性缩放)，牌河紧贴中心盘，对手手牌与副露紧锁四边，彻底杜绝窗口拉伸时的位置漂移；
2. 彻底废除右侧冗余的时间流卡片列表，替换为官方 Mortal 经典的大型【当前决策全景控制台】：
   - 顶部：玩家实际动作 vs 模型首选动作的明确对照卡；
   - 中部：三模型横向概率与 Q 值对比大表格，包含直观柱状条与分歧标识；
   - 底部：步进导航与恶手损失统计；
3. 自家手牌上方动态渲染【模型推荐切牌光标/立柱】与【玩家实切恶手红标】，一眼看出跑谱学习差异；
4. 顶部增加上一局/下一局跳转与双模式切换；
5. 小局终了弹窗展示完整真实和牌牌姿、副露、和了牌高亮与详细役种清单；
6. 牌河标准 6 列宽，摸手切、立直横置、被鸣红框完美共存。
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


REPLAYER_HTML_TEMPLATE = """<!DOCTYPE html>
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
.header-left { display: flex; align-items: center; gap: 10px; }
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
  font-size: 13px;
  cursor: pointer;
}
.header-right { display: flex; align-items: center; gap: 16px; font-size: 12px; color: var(--text-dim); }

.workspace {
  flex: 1;
  display: flex;
  height: calc(100vh - 44px);
  overflow: hidden;
}

/* 牌桌区域：必须使用居中相对定位容器，杜绝绝对定位随窗口漂移 */
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
  width: 680px;
  height: 680px;
  max-width: calc(100vh - 56px);
  max-height: calc(100vh - 56px);
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
  width: 190px;
  height: 190px;
  background: var(--table-center);
  border: 2px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.8);
  display: grid;
  grid-template-rows: 32px 1fr 32px;
  grid-template-columns: 32px 1fr 32px;
  position: absolute;
  z-index: 10;
}
.seat-score {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-main);
}
.seat-top    { grid-row: 1; grid-column: 2; }
.seat-bottom { grid-row: 3; grid-column: 2; }
.seat-left   { grid-row: 2; grid-column: 1; writing-mode: vertical-rl; transform: rotate(180deg); }
.seat-right  { grid-row: 2; grid-column: 3; writing-mode: vertical-rl; }
.seat-score.dealer { color: #ff6b6b; }
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
.center-title { font-size: 15px; font-weight: bold; color: #fff; }
.center-sticks { font-size: 11px; color: var(--text-dim); }
.center-tiles-left { font-size: 11px; color: #f1c40f; font-weight: bold; }
.dora-bar { display: flex; gap: 2px; margin-top: 2px; }

/* 四家标准 6 列牌河：紧靠中心盘四周边沿，距离仅 8px！ */
.river-grid {
  position: absolute;
  display: flex;
  flex-wrap: wrap;
  width: 156px; /* 6 张 x 24px + gap = 154px */
  gap: 2px;
  align-content: flex-start;
  z-index: 5;
}
/* 四家标准 6 列牌河：紧贴中心盘 190px 外边缘，距离仅 8px！ */
/* 中心盘位于 50%，半径 95px -> 紧贴外沿为 50% + 95px + 8px = calc(50% + 103px) */
.river-bottom { top: calc(50% + 103px); left: 50%; transform: translateX(-50%); height: 106px; }
.river-top    { bottom: calc(50% + 103px); left: 50%; transform: translateX(-50%) rotate(180deg); height: 106px; }
.river-left   { right: calc(50% + 103px); top: 50%; transform: translateY(-50%) rotate(90deg); transform-origin: center center; height: 106px; }
.river-right  { left: calc(50% + 103px); top: 50%; transform: translateY(-50%) rotate(-90deg); transform-origin: center center; height: 106px; }

/* 四家手牌与副露：紧贴牌河外侧 */
.hand-group-bottom {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  z-index: 20;
}
.hand-group-top {
  position: absolute;
  top: 16px;
  left: 50%;
  transform: translateX(-50%) rotate(180deg);
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 20;
}
.hand-group-left {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%) rotate(90deg);
  transform-origin: center center;
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 20;
}
.hand-group-right {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%) rotate(-90deg);
  transform-origin: center center;
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 20;
}

.tehai-row { display: flex; align-items: flex-end; gap: 2px; position: relative; }
.melds-row { display: flex; gap: 4px; align-items: flex-end; }
.meld-unit { display: flex; gap: 1px; background: rgba(0,0,0,0.5); padding: 2px; border-radius: 3px; border: 1px solid rgba(255,255,255,0.1); }

/* 纯白高保真象牙白瓷牌面 */
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
  position: relative;
}
.tile-hand { width: 38px; height: 54px; }
.tile-tsumo { margin-left: 12px; box-shadow: 0 0 0 2px #5bc0be; }
.tile-river { width: 24px; height: 32px; }
.tile-river.tsumogiri { opacity: 0.72; filter: brightness(0.92); }
.tile-river.riichi { transform: rotate(90deg); margin: 0 4px; box-shadow: 0 0 0 2px #f1c40f; }
.tile-river.called { border: 1.5px solid #e74c3c !important; box-shadow: 0 0 0 1.5px rgba(231,76,60,0.85) !important; }
.tile-back { background: var(--tile-back-color) !important; border: 1px solid #5a0f0f; border-bottom: 2px solid #3d0a0a; }
.tile-mini { width: 22px; height: 30px; }
.tile-sideways { transform: rotate(90deg); margin: 0 4px; }

/* 跑谱核心：自家手牌上方的决策指标指示器（实切红标 vs 推荐光标） */
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

/* 右侧：经典 Mortal 风格决策控制台 (460px 宽度) */
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

/* 决策候选表 */
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
  padding: 8px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: middle;
}
.prob-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.prob-bar-bg {
  width: 50px;
  height: 6px;
  background: rgba(255,255,255,0.1);
  border-radius: 3px;
  overflow: hidden;
}
.prob-bar-fill { height: 100%; border-radius: 3px; }
.fill-aegis { background: var(--accent-aegis); }
.fill-sol   { background: var(--accent-sol); }
.fill-logos { background: var(--accent-logos); }

/* 控制器与战绩统计 */
.console-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  background: #050c0e;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.nav-btn-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 8px;
}
.btn-nav {
  padding: 9px;
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

/* 终局弹窗 */
.result-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(5, 17, 20, 0.98);
  border: 2px solid #5bc0be;
  border-radius: 10px;
  padding: 20px 30px;
  box-shadow: 0 12px 50px rgba(0,0,0,0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  z-index: 100;
  min-width: 380px;
  max-width: 520px;
}
.result-title { font-size: 20px; font-weight: 800; color: #f1c40f; }
.result-points { font-size: 24px; font-weight: 900; color: #fff; }
.result-hand-display {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(0,0,0,0.5);
  border-radius: 6px;
  margin: 6px 0;
  width: 100%;
}
.winning-tile { margin-left: 10px; box-shadow: 0 0 0 2px #f1c40f; }
.result-yaku-list { font-size: 12px; color: var(--text-main); display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.yaku-pill { background: rgba(91, 192, 190, 0.2); padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(91, 192, 190, 0.4); }
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
    <label style="cursor:pointer; display:flex; align-items:center; gap:4px;">
      <input type="checkbox" id="chk-open-hands" onchange="toggleOpenHands(this.checked)">
      <span>伏牌透视</span>
    </label>
    <span id="header-stats-text">三神契合度: -- | 分歧: --</span>
  </div>
</header>

<div class="workspace">
  <!-- 牌桌视口 -->
  <div class="board-viewport">
    <!-- 小局终了弹层 -->
    <div class="result-overlay" id="end-overlay" style="display:none;">
      <div class="result-title" id="res-title">和了 (荣和)</div>
      <div class="result-points" id="res-points">3900 点 (30符 2番)</div>
      <div class="result-hand-display" id="res-hand-box"></div>
      <div class="result-yaku-list" id="res-yaku"></div>
      <button class="btn-nav" style="margin-top:8px; width:120px;" onclick="closeOverlay()">查看对局</button>
    </div>

    <!-- 固定比例麻将桌盘面 (820px × 820px) -->
    <div class="mahjong-table">
      <!-- 对家 (上) -->
      <div class="hand-group-top">
        <div class="tehai-row" id="hand-2"></div>
        <div class="melds-row" id="melds-2"></div>
      </div>

      <!-- 四家标准 6 列牌河 (紧贴中心盘) -->
      <div class="river-grid river-top" id="river-2"></div>
      <div class="river-grid river-left" id="river-3"></div>

      <!-- 中心盘 -->
      <div class="table-center-box">
        <div class="seat-score seat-top" id="score-2">对家 25000</div>
        <div class="seat-score seat-left" id="score-3">上家 25000</div>
        <div class="center-meta">
          <div class="center-title" id="box-round-title">东 1 局</div>
          <div class="center-sticks" id="box-sticks">0 本场 · 供托 0</div>
          <div class="center-tiles-left" id="box-tiles-left">牌山 x70</div>
          <div class="dora-bar" id="box-dora-bar"></div>
        </div>
        <div class="seat-score seat-right" id="score-1">下家 25000</div>
        <div class="seat-score seat-bottom" id="score-0">自家 25000</div>
      </div>

      <div class="river-grid river-right" id="river-1"></div>
      <div class="river-grid river-bottom" id="river-0"></div>

      <!-- 左右两家对手 (横向平躺排列，绝不竖立截断) -->
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

  <!-- 右侧：经典 Mortal 控制台面板 -->
  <div class="console-panel">
    <div class="console-header">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:700; font-size:14px;" id="side-step-label">第 1 / 148 步</span>
        <span style="font-size:12px; color:var(--text-dim);" id="side-action-desc">自家摸牌</span>
      </div>
      <!-- 实际切牌 vs 模型推荐对照卡 -->
      <div class="actual-vs-ai-card" id="actual-vs-ai-card">
        <div>
          <div style="font-size:11px; color:var(--text-dim);">玩家实际动作</div>
          <div style="font-size:16px; font-weight:800; margin-top:2px;" id="disp-actual-act">--</div>
        </div>
        <div id="disp-match-badge" class="play-badge badge-match">吻合</div>
        <div>
          <div style="font-size:11px; color:var(--text-dim); text-align:right;">AI 首选动作</div>
          <div style="font-size:16px; font-weight:800; margin-top:2px; text-align:right;" id="disp-ai-best">--</div>
        </div>
      </div>
    </div>

    <!-- 候选动作全量概率表 -->
    <div class="candidates-table-wrap">
      <div style="font-weight:700; font-size:13px; margin-bottom:8px; color:#5bc0be;">动作空间三模型对比 (Q值与权重)</div>
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
      <div style="margin-top:16px; font-size:11px; color:var(--text-dim); line-height:1.6;">
        💡 <b>跑谱对比指南</b>：Aegis 代表极致避四防守（天凤风格），Sol 代表高打点立直争一（M-League风格），Logos 为经典均衡基准。
      </div>
    </div>

    <!-- 底部控制区 -->
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

var playbackMode = "self"; // "self" | "global"
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

/* 客户端轻量极速状态机：根据事件索引重建牌桌瞬时物理世界 */
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
      state.endInfo = {
        type: 'hora',
        actor: ev.actor,
        target: ev.target,
        is_tsumo: (ev.actor === ev.target),
        pai: ev.pai,
        ten_points: ev.ten_points || 0,
        ten_fu: ev.ten_fu || 0,
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

  selectStepByEventIdx(selfDecs.length ? selfDecs[0] : 0);
}

function onSelectMode(mode) {
  playbackMode = mode;
  selectStepByEventIdx(currentEventIdx);
}

function onSelectKyoku(startEvIdx) {
  selectStepByEventIdx(parseInt(startEvIdx));
}

function prevKyoku() {
  var sel = document.getElementById('kyoku-selector');
  if (sel.selectedIndex > 0) {
    sel.selectedIndex--;
    onSelectKyoku(sel.value);
  }
}

function nextKyoku() {
  var sel = document.getElementById('kyoku-selector');
  if (sel.selectedIndex < sel.options.length - 1) {
    sel.selectedIndex++;
    onSelectKyoku(sel.value);
  }
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

  var doraHtml = '';
  for (var dm = 0; dm < board.doraMarkers.length; dm++) {
    doraHtml += getTileImg(board.doraMarkers[dm], 'tile-river');
  }
  document.getElementById('box-dora-bar').innerHTML = doraHtml;

  var seatNames = ['东', '南', '西', '北'];
  var actActor = board.lastAction ? board.lastAction.actor : null;
  for (var seat = 0; seat < 4; seat++) {
    var relIdx = (seat - targetSeat + 4) % 4;
    var elId = 'score-' + relIdx;
    var scoreEl = document.getElementById(elId);
    if (scoreEl) {
      scoreEl.innerText = seatNames[seat] + ' ' + (board.scores[seat] || 25000);
      if (seat === board.oya) scoreEl.classList.add('dealer'); else scoreEl.classList.remove('dealer');
      if (actActor === seat) scoreEl.classList.add('active-turn'); else scoreEl.classList.remove('active-turn');
    }
  }

  // 2. 渲染四家标准 6 列牌河 (紧贴中心盘)
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

  // 3. 渲染自家理牌手牌 + 跑谱核心指示器 (AI 最佳光标 vs 玩家实切)
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

  // 6. 渲染右侧全景控制台
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

  // 获取三模型的最优推荐牌（兼容 .tile 与从 .action 中提取牌名）
  var bestTiles = {};
  if (evEval && evEval.models) {
    ['Aegis', 'Sol', 'Logos'].forEach(function(m) {
      var b = (evEval.models[m] || {}).best;
      if (b) {
        var tName = b.tile || '';
        if (!tName && b.action) {
          var clean = b.action.replace('r', '');
          if (clean.length === 2 && 'mpsz'.indexOf(clean[1]) !== -1) tName = clean;
          else if (['E','S','W','N','P','F','C'].indexOf(clean) !== -1) tName = clean;
        }
        if (tName) bestTiles[m] = tName;
      }
    });
  }

  // 获取玩家实切牌
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
    document.getElementById('res-points').innerText = endInfo.ten_points + ' 点 (' + endInfo.ten_fu + '符)';

    var handBox = document.getElementById('res-hand-box');
    var hHtml = '<div style="display:flex; gap:2px; align-items:center;">';
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
      hHtml += '<div style="display:flex; gap:4px; margin-left:8px;">';
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

function closeOverlay() {
  document.getElementById('end-overlay').style.display = 'none';
}

function toggleOpenHands(isOpen) {
  showAllHands = isOpen;
  selectStepByEventIdx(currentEventIdx);
}

/* 渲染右侧经典 Mortal 控制台面板 */
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

  var desc = act ? (seatNames[act.actor] + '家 ' + act.type + ' ' + (act.pai || '')) : '--';
  document.getElementById('side-action-desc').innerText = desc;

  // 对照卡
  var actCard = document.getElementById('actual-vs-ai-card');
  var matchBadge = document.getElementById('disp-match-badge');

  if (evEval && evEval.models) {
    actCard.style.display = 'flex';
    var actualStr = act && act.pai ? (act.pai + (act.riichi ? 'r' : '')) : (act ? act.type : '--');
    document.getElementById('disp-actual-act').innerText = formatAction(actualStr);

    var logosBest = (evEval.models.Logos || {}).best || {};
    var aiBestStr = logosBest.action || '--';
    document.getElementById('disp-ai-best').innerText = formatAction(aiBestStr);

    var isMatch = (actualStr === aiBestStr);
    if (isMatch) {
      matchBadge.className = 'play-badge badge-match';
      matchBadge.innerText = '与AI一致';
    } else {
      matchBadge.className = 'play-badge badge-mismatch';
      matchBadge.innerText = '分歧恶手';
    }

    // 候选表格
    renderCandidatesTable(evEval.models);
  } else {
    actCard.style.display = 'none';
    document.getElementById('candidates-tbody').innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-dim); padding:30px 0;">当前动作为他家事件，无自家模型建议</td></tr>';
  }
}

function renderCandidatesTable(models) {
  var tbody = document.getElementById('candidates-tbody');
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
    rowsHtml += '<td style="font-weight:700;">' + formatAction(act) + '</td>';
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

    html_content = REPLAYER_HTML_TEMPLATE.replace("__REVIEW_DATA_PLACEHOLDER__", data_json_safe).replace("__TILE_ASSETS_PLACEHOLDER__", assets_json_safe)

    out_p.write_text(html_content, encoding="utf-8")
    return out_p

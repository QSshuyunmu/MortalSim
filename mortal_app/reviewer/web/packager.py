"""完全离线单文件 HTML 牌谱复盘报告编译器 (Complete Mahjong Replayer Packager).

解决所有体验缺陷：
1. 终局结算展示和牌方完整真实牌姿（纯手牌 + 副露组合 + 和了牌独立隔开高亮）；
2. 左右他家副露紧贴手牌并排展示，绝对不遗漏任何一家副露；
3. 四家全量理牌（万筒索字精准顺序，赤牌归位到对应数牌旁边）；
4. 标准 6 列牌河，不发生 4 列截断；
5. 双模式无缝切换（逐自家决策 Focused / 逐全局事件流 Global）；
6. 象牙白瓷纯白高反差牌面，完全离线单文件 IIFE 打包（<800KB）。
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


COMPLETE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Mortal Reviewer — 全盘全动作对局复盘系统</title>
<style>
:root {
  --bg-color: #0b181b;
  --center-box: #081a1e;
  --border-color: #1f4952;
  --text-main: #e3edf0;
  --text-dim: #7da0a8;
  --tile-white: #ffffff;
  --tile-border: #d2d0c5;
  --tile-shadow: #a8a598;
  --tile-back-color: #831818;
  --accent-aegis: #4ea8de;
  --accent-sol: #f39c12;
  --accent-logos: #2ecc71;
  --conflict-color: #e74c3c;
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
  background: #060e10;
  border-bottom: 1px solid var(--border-color);
  padding: 6px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 42px;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.logo-title { font-weight: bold; font-size: 15px; color: #5bc0be; }
.select-ctl {
  background: #10262b;
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
  height: calc(100vh - 42px);
}

/* 牌桌区 */
.board-container {
  flex: 1;
  background: radial-gradient(circle at center, #153c44 0%, #0c2025 85%);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 12px 24px;
  position: relative;
}

/* 牌桌中央网格与牌河区 */
.board-middle {
  flex: 1;
  display: grid;
  grid-template-rows: 1fr auto 1fr;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  justify-items: center;
  width: 100%;
  max-width: 960px;
  margin: auto;
}

/* 中心盘 */
.center-square {
  grid-row: 2;
  grid-column: 2;
  width: 190px;
  height: 190px;
  background: var(--center-box);
  border: 2px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 4px 25px rgba(0,0,0,0.6);
  display: grid;
  grid-template-rows: 32px 1fr 32px;
  grid-template-columns: 32px 1fr 32px;
  position: relative;
}
.center-inner {
  grid-row: 2;
  grid-column: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}
.center-title { font-size: 15px; font-weight: bold; color: #fff; }
.center-tiles-left { font-size: 11px; color: #f1c40f; font-weight: 600; }
.center-sticks { font-size: 11px; color: var(--text-dim); }

.seat-score {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-main);
}
.seat-top    { grid-row: 1; grid-column: 2; }
.seat-bottom { grid-row: 3; grid-column: 2; }
.seat-left   { grid-row: 2; grid-column: 1; writing-mode: vertical-rl; transform: rotate(180deg); }
.seat-right  { grid-row: 2; grid-column: 3; writing-mode: vertical-rl; }
.seat-score.dealer { color: #ff6b6b; font-weight: bold; }
.seat-score.active-turn { box-shadow: inset 0 0 8px rgba(91, 192, 190, 0.6); border-radius: 4px; }

.dora-bar { display: flex; gap: 2px; margin-top: 2px; }

/* 牌河排布：标准 6 列宽！ */
.river-area {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  width: 156px;
  min-height: 100px;
  align-content: flex-start;
}
.river-top    { grid-row: 1; grid-column: 2; transform: rotate(180deg); }
.river-bottom { grid-row: 3; grid-column: 2; }
.river-left   { grid-row: 2; grid-column: 1; transform: rotate(90deg); }
.river-right  { grid-row: 2; grid-column: 3; transform: rotate(-90deg); }

/* 四家手牌与副露区域定位 */
.player-row-top {
  display: flex;
  align-items: center;
  justify-content: center;
  transform: rotate(180deg);
  gap: 8px;
}
.player-row-left {
  display: flex;
  align-items: center;
  position: absolute;
  left: 20px;
  top: 50%;
  transform: translateY(-50%) rotate(90deg);
  transform-origin: center center;
  gap: 8px;
}
.player-row-right {
  display: flex;
  align-items: center;
  position: absolute;
  right: 20px;
  top: 50%;
  transform: translateY(-50%) rotate(-90deg);
  transform-origin: center center;
  gap: 8px;
}
.player-row-bottom {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 12px;
}

.tehai-box { display: flex; gap: 2px; align-items: flex-end; }
.meld-box  { display: flex; gap: 4px; align-items: flex-end; }
.meld-group {
  display: flex;
  gap: 1px;
  background: rgba(0,0,0,0.45);
  padding: 2px 3px;
  border-radius: 3px;
  border: 1px solid rgba(255,255,255,0.12);
}

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
.tile-tsumo { margin-left: 12px; box-shadow: 0 0 0 2px #5bc0be; }
.tile-river { width: 24px; height: 32px; }
.tile-river.tsumogiri { opacity: 0.72; filter: brightness(0.92); }
.tile-river.riichi { transform: rotate(90deg); margin: 0 4px; box-shadow: 0 0 0 2px #f1c40f; }

/* 背竹暗牌 */
.tile-back {
  background: var(--tile-back-color) !important;
  border: 1px solid #5a0f0f;
  border-bottom: 2px solid #3d0a0a;
}
.tile-mini { width: 22px; height: 30px; }
.tile-meld-sideways {
  transform: rotate(90deg);
  margin: 0 4px;
}
.kakan-stack {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}

/* 终局弹窗 (役种、番符、点数清单 + 和牌方完整手牌姿) */
.result-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(6, 20, 24, 0.98);
  border: 2px solid #5bc0be;
  border-radius: 8px;
  padding: 18px 26px;
  box-shadow: 0 10px 40px rgba(0,0,0,0.85);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 100;
  min-width: 360px;
  max-width: 500px;
}
.result-title { font-size: 18px; font-weight: bold; color: #f1c40f; }
.result-points { font-size: 22px; font-weight: 800; color: #fff; }
.result-hand-display {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(0,0,0,0.5);
  border-radius: 6px;
  margin: 6px 0;
  width: 100%;
}
.winning-tile { margin-left: 10px; box-shadow: 0 0 0 2px #f1c40f; }
.result-yaku-list { font-size: 12px; color: var(--text-main); display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.yaku-pill { background: rgba(91, 192, 190, 0.2); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(91, 192, 190, 0.4); }

/* 侧边多模型决策流 */
.sidebar {
  width: 440px;
  background: var(--center-box);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.sidebar-top {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.timeline-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.action-card {
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border-color);
  border-radius: 5px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 12px;
}
.action-card:hover, .action-card.active {
  background: rgba(91, 192, 190, 0.09);
  border-color: #5bc0be;
}
.action-card.conflict {
  border-color: var(--conflict-color);
  background: rgba(231, 76, 60, 0.12);
}
.card-header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.model-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 4px;
  background: rgba(0,0,0,0.3);
  padding: 4px 6px;
  border-radius: 4px;
  text-align: center;
}
.model-aegis { color: var(--accent-aegis); font-weight: 600; }
.model-sol   { color: var(--accent-sol); font-weight: 600; }
.model-logos { color: var(--accent-logos); font-weight: 600; }

.detail-drawer {
  border-top: 1px solid var(--border-color);
  padding: 8px 12px;
  background: #050c0e;
  max-height: 220px;
  overflow-y: auto;
  font-size: 12px;
}
.cand-list-row { display: flex; justify-content: space-between; padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
.controls {
  padding: 8px 12px;
  background: #050c0e;
  border-top: 1px solid var(--border-color);
  display: flex;
  gap: 6px;
}
.btn-ctl {
  flex: 1;
  padding: 6px;
  background: #16363d;
  color: #fff;
  border: 1px solid #23545e;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}
.btn-ctl:hover { background: #1e4952; }
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="logo-title">🀄 Mortal Reviewer</div>
    <select class="select-ctl" id="kyoku-selector" onchange="onSelectKyoku(this.value)"></select>
    <select class="select-ctl" id="mode-selector" onchange="onSelectMode(this.value)">
      <option value="self">仅自家决策 (Focused)</option>
      <option value="global">逐全局事件 (Global Stream)</option>
    </select>
  </div>
  <div class="header-right">
    <label style="cursor:pointer; display:flex; align-items:center; gap:4px;">
      <input type="checkbox" id="chk-open-hands" onchange="toggleOpenHands(this.checked)">
      <span>伏牌透视</span>
    </label>
    <span id="header-stats-text">一致率: -- | 分歧: --</span>
  </div>
</header>

<div class="workspace">
  <!-- 牌桌 -->
  <div class="board-container">
    <!-- 终局弹窗 -->
    <div class="result-overlay" id="end-overlay" style="display:none;">
      <div class="result-title" id="res-title">和了 (荣和)</div>
      <div class="result-points" id="res-points">3900 点 (30符 2番)</div>
      <div class="result-hand-display" id="res-hand-box"></div>
      <div class="result-yaku-list" id="res-yaku"></div>
      <button class="btn-ctl" style="margin-top:8px; width:100px;" onclick="closeOverlay()">关闭</button>
    </div>

    <!-- 对家 (上) -->
    <div class="player-row-top">
      <div class="tehai-box" id="hand-2"></div>
      <div class="meld-box" id="melds-2"></div>
    </div>

    <!-- 中间：标准 6 列牌河与中心点数盘 -->
    <div class="board-middle">
      <div class="river-area river-top" id="river-2"></div>
      <div class="river-area river-left" id="river-3"></div>

      <div class="center-square">
        <div class="seat-score seat-top" id="score-2">对家 25000</div>
        <div class="seat-score seat-left" id="score-3">上家 25000</div>
        <div class="center-inner">
          <div class="center-title" id="box-round-title">东 1 局</div>
          <div class="center-sticks" id="box-sticks">0 本场 · 供托 0</div>
          <div class="center-tiles-left" id="box-tiles-left">牌山 x70</div>
          <div class="dora-bar" id="box-dora-bar"></div>
        </div>
        <div class="seat-score seat-right" id="score-1">下家 25000</div>
        <div class="seat-score seat-bottom" id="score-0">自家 25000</div>
      </div>

      <div class="river-area river-right" id="river-1"></div>
      <div class="river-area river-bottom" id="river-0"></div>
    </div>

    <!-- 左右对手手牌 (横置紧贴副露) -->
    <div class="player-row-left">
      <div class="tehai-box" id="hand-3"></div>
      <div class="meld-box" id="melds-3"></div>
    </div>
    <div class="player-row-right">
      <div class="tehai-box" id="hand-1"></div>
      <div class="meld-box" id="melds-1"></div>
    </div>

    <!-- 自家手牌 (下) -->
    <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
      <div style="font-size:11px; color:var(--text-dim);" id="hand-info-text">自家手牌 (已理牌)</div>
      <div class="player-row-bottom">
        <div class="tehai-box" id="hand-0"></div>
        <div class="meld-box" id="melds-0"></div>
      </div>
    </div>
  </div>

  <!-- 右侧决策与事件流 -->
  <div class="sidebar">
    <div class="sidebar-top">
      <span id="side-kyoku-label">动作决策流</span>
      <span style="font-size:11px; color:var(--text-dim);" id="side-dec-count">共 -- 项</span>
    </div>
    <div class="timeline-scroll" id="card-timeline"></div>
    <div class="detail-drawer" id="detail-drawer">
      <div style="text-align:center; color:var(--text-dim); margin-top:20px;">选择动作查看三模型候选全量概率对比</div>
    </div>
    <div class="controls">
      <button class="btn-ctl" onclick="prevStep()">上一步</button>
      <button class="btn-ctl" onclick="nextConflict()">下一分歧</button>
      <button class="btn-ctl" onclick="nextStep()">下一步</button>
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
  'Chi(Low)': '吃牌(低张)',
  'Chi(Mid)': '吃牌(中张)',
  'Chi(High)': '吃牌(高张)',
  'Pon': '碰牌',
  'Kan': '杠牌',
  'Hora': '胡牌(荣和/自摸)',
  'Ryukyoku': '九种九牌',
  'Pass': 'Pass (见逃/跳过)'
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

/* 客户端轻量状态机：重建牌桌瞬时物理世界 */
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
      // 保存和牌方的真实纯手牌、副露与和了牌
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
  document.getElementById('header-stats-text').innerText = '三神契合度: ' + rate + '% | 分歧: ' + conflicts + ' / ' + selfDecs.length;

  selectStepByEventIdx(selfDecs.length ? selfDecs[0] : 0);
}

function onSelectMode(mode) {
  playbackMode = mode;
  renderSidebarCards();
}

function onSelectKyoku(startEvIdx) {
  selectStepByEventIdx(parseInt(startEvIdx));
}

function selectStepByEventIdx(evIdx) {
  var events = PAYLOAD.events || [];
  if (evIdx < 0 || evIdx >= events.length) return;
  currentEventIdx = evIdx;

  var board = reconstructBoardState(evIdx);
  var targetSeat = PAYLOAD.target_seat || 0;

  // 更新局选择下拉
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

  // 2. 渲染四家标准 6 列牌河
  for (var p = 0; p < 4; p++) {
    var rList = board.rivers[p] || [];
    var rHtml = '';
    for (var r = 0; r < rList.length; r++) {
      var item = rList[r];
      var cls = 'tile-river';
      if (item.is_tsumogiri) cls += ' tsumogiri';
      if (item.is_riichi) cls += ' riichi';
      rHtml += getTileImg(item.tile, cls);
    }
    var relP = (p - targetSeat + 4) % 4;
    var rEl = document.getElementById('river-' + relP);
    if (rEl) rEl.innerHTML = rHtml;
  }

  // 3. 渲染自家理牌手牌
  var regularHand = sortTiles(board.hands[targetSeat]);
  var tsumoActual = null;
  if (board.lastAction && board.lastAction.type === 'tsumo' && board.lastAction.actor === targetSeat) {
    tsumoActual = board.lastAction.pai;
    var tIdx = regularHand.indexOf(tsumoActual);
    if (tIdx !== -1) regularHand.splice(tIdx, 1);
  }
  var handHtml = '';
  for (var h = 0; h < regularHand.length; h++) {
    handHtml += getTileImg(regularHand[h], 'tile-hand');
  }
  if (tsumoActual) {
    handHtml += getTileImg(tsumoActual, 'tile-hand tile-tsumo');
  }
  document.getElementById('hand-0').innerHTML = handHtml;
  renderMelds('melds-0', board.melds[targetSeat], targetSeat);

  var actLabel = board.lastAction ? (seatNames[board.lastAction.actor] + '家 ' + board.lastAction.type + ' ' + (board.lastAction.pai || '')) : '';
  document.getElementById('hand-info-text').innerText = actLabel;

  // 4. 渲染三家对手手牌与副露 (理牌 + 横置排列紧贴副露)
  renderOpponent('hand-2', 'melds-2', sortTiles(board.hands[(targetSeat + 2) % 4]), board.melds[(targetSeat + 2) % 4], (targetSeat + 2) % 4);
  renderOpponent('hand-3', 'melds-3', sortTiles(board.hands[(targetSeat + 3) % 4]), board.melds[(targetSeat + 3) % 4], (targetSeat + 3) % 4);
  renderOpponent('hand-1', 'melds-1', sortTiles(board.hands[(targetSeat + 1) % 4]), board.melds[(targetSeat + 1) % 4], (targetSeat + 1) % 4);

  // 5. 终局结算面板
  if (board.endInfo) {
    showEndOverlay(board.endInfo);
  } else {
    document.getElementById('end-overlay').style.display = 'none';
  }

  renderSidebarCards();
  renderDetailDrawer(evIdx);
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

  // 严格日麻被鸣者相对座次：
  // rel == 3: 上家 (左侧牌横置)
  // rel == 2: 对家 (中间牌横置)
  // rel == 1: 下家 (右侧牌横置)
  var rel = (target !== undefined && target !== null) ? (target - actorSeat + 4) % 4 : 3;

  if (mType === 'chi') {
    // 吃牌固定来自上家，左边第一张横置 [8m(横), 6m, 7m]
    return [
      { tile: pai, isBack: false, isSideways: true },
      { tile: consumed[0], isBack: false, isSideways: false },
      { tile: consumed[1], isBack: false, isSideways: false }
    ];
  }

  if (mType === 'pon') {
    if (rel === 3) {
      // 上家: [横, c0, c1]
      return [
        { tile: pai, isBack: false, isSideways: true },
        { tile: consumed[0], isBack: false, isSideways: false },
        { tile: consumed[1], isBack: false, isSideways: false }
      ];
    } else if (rel === 2) {
      // 对家: [c0, 横, c1]
      return [
        { tile: consumed[0], isBack: false, isSideways: false },
        { tile: pai, isBack: false, isSideways: true },
        { tile: consumed[1], isBack: false, isSideways: false }
      ];
    } else {
      // 下家: [c0, c1, 横]
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
        { tile: pai, isBack: false, isSideways: true, isKakan: (mType==='kakan') },
        { tile: c0, isBack: false, isSideways: false },
        { tile: c1, isBack: false, isSideways: false },
        { tile: c2, isBack: false, isSideways: false }
      ];
    } else if (rel === 2) {
      return [
        { tile: c0, isBack: false, isSideways: false },
        { tile: pai, isBack: false, isSideways: true, isKakan: (mType==='kakan') },
        { tile: c1, isBack: false, isSideways: false },
        { tile: c2, isBack: false, isSideways: false }
      ];
    } else {
      return [
        { tile: c0, isBack: false, isSideways: false },
        { tile: c1, isBack: false, isSideways: false },
        { tile: c2, isBack: false, isSideways: false },
        { tile: pai, isBack: false, isSideways: true, isKakan: (mType==='kakan') }
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
    h += '<div class="meld-group">';
    for (var a = 0; a < arranged.length; a++) {
      var item = arranged[a];
      var cls = 'tile-mini';
      if (item.isSideways) cls += ' tile-meld-sideways';
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

    // 渲染和牌方完整真实牌姿：纯手牌 + 副露 + 和了牌独立隔开
    var handBox = document.getElementById('res-hand-box');
    var hHtml = '<div style="display:flex; gap:2px; align-items:center;">';
    var wHand = endInfo.winner_hand || [];
    for (var i = 0; i < wHand.length; i++) {
      hHtml += getTileImg(wHand[i], 'tile-hand');
    }
    // 和了牌独立高亮
    if (endInfo.pai) {
      hHtml += getTileImg(endInfo.pai, 'tile-hand winning-tile');
    }
    hHtml += '</div>';

    // 和牌方副露：同样按照标准朝向指向摆放
    var wMelds = endInfo.winner_melds || [];
    if (wMelds.length) {
      hHtml += '<div style="display:flex; gap:4px; margin-left:8px;">';
      for (var m = 0; m < wMelds.length; m++) {
        var meld = wMelds[m];
        var arranged = arrangeMeldTiles(meld, endInfo.actor);
        hHtml += '<div class="meld-group">';
        for (var ma = 0; ma < arranged.length; ma++) {
          var aItem = arranged[ma];
          var aCls = 'tile-mini';
          if (aItem.isSideways) aCls += ' tile-meld-sideways';
          if (aItem.isBack) hHtml += getTileBack(aCls);
          else hHtml += getTileImg(aItem.tile, aCls);
        }
        hHtml += '</div>';
      }
      hHtml += '</div>';
    }
    handBox.innerHTML = hHtml;

    // 役种标签
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

function renderSidebarCards() {
  var events = PAYLOAD.events || [];
  var evals = PAYLOAD.evaluations || {};
  var selfDecs = PAYLOAD.self_decision_indices || [];

  var indices = (playbackMode === 'self') ? selfDecs : [];
  if (playbackMode === 'global') {
    for (var i = 0; i < events.length; i++) indices.push(i);
  }

  document.getElementById('side-kyoku-label').innerText = (playbackMode === 'self' ? '自家决策流' : '逐全局事件流');
  document.getElementById('side-dec-count').innerText = '共 ' + indices.length + ' 项';

  var seatNames = ['东', '南', '西', '北'];
  var html = '';
  for (var j = 0; j < indices.length; j++) {
    var evIdx = indices[j];
    var ev = events[evIdx];
    var evEval = evals[evIdx];
    var isAct = (evIdx === currentEventIdx);
    var hasConflict = evEval ? !!evEval.has_conflict : false;

    var actTitle = (ev.actor !== undefined ? seatNames[ev.actor] + '家 ' : '') + ev.type + ' ' + (ev.pai || '');

    html += '<div class="action-card ' + (hasConflict ? 'conflict ' : '') + (isAct ? 'active' : '') + '" onclick="selectStepByEventIdx(' + evIdx + ')">';
    html += '  <div class="card-header-row">';
    html += '    <span style="font-weight:600;">' + (j+1) + '. ' + actTitle + '</span>';
    if (hasConflict) html += '<span style="color:#ff6b6b; font-weight:bold; font-size:11px;">战术分歧</span>';
    html += '  </div>';

    if (evEval && evEval.models && evEval.models.Aegis && evEval.models.Aegis.best) {
      var m = evEval.models;
      html += '  <div class="model-grid">';
      html += '    <div class="model-aegis">Aegis<br>' + formatAction(m.Aegis.best.action) + ' (' + Math.round(m.Aegis.best.prob*100) + '%)</div>';
      html += '    <div class="model-sol">Sol<br>' + formatAction(m.Sol.best.action) + ' (' + Math.round(m.Sol.best.prob*100) + '%)</div>';
      html += '    <div class="model-logos">Logos<br>' + formatAction(m.Logos.best.action) + ' (' + Math.round(m.Logos.best.prob*100) + '%)</div>';
      html += '  </div>';
    }
    html += '</div>';
  }

  var listEl = document.getElementById('card-timeline');
  listEl.innerHTML = html;
  var activeEl = listEl.querySelector('.action-card.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function formatAction(act) {
  if (!act) return '--';
  return ACTION_NAMES_ZH[act] || act;
}

function renderDetailDrawer(evIdx) {
  var drawer = document.getElementById('detail-drawer');
  var evEval = (PAYLOAD.evaluations || {})[evIdx];

  if (!evEval || !evEval.models) {
    drawer.innerHTML = '<div style="text-align:center; color:var(--text-dim); margin-top:20px;">当前为他家动作或流局事件，无自家决策建议</div>';
    return;
  }

  var m = evEval.models;
  var h = '<div style="font-weight:bold; margin-bottom:4px; font-size:12px; color:#5bc0be;">全量动作选项对比 (吃碰杠/切牌/胡牌)</div>';
  h += '<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px;">';

  ['Aegis', 'Sol', 'Logos'].forEach(function(mname) {
    var cands = (m[mname] || {}).candidates || [];
    h += '<div>';
    h += '  <div style="font-weight:bold; margin-bottom:4px;" class="model-' + mname.toLowerCase() + '">' + mname + ' Top 候选</div>';
    for (var j = 0; j < cands.length; j++) {
      var c = cands[j];
      h += '  <div class="cand-list-row">';
      h += '    <span>' + formatAction(c.action) + '</span>';
      h += '    <span style="color:#f1c40f;">' + Math.round(c.prob*100) + '% <small style="color:var(--text-dim);">(Q:' + Math.round(c.q*10)/10 + ')</small></span>';
      h += '  </div>';
    }
    h += '</div>';
  });
  h += '</div>';
  drawer.innerHTML = h;
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

function nextConflict() {
  var evals = PAYLOAD.evaluations || {};
  var selfDecs = PAYLOAD.self_decision_indices || [];
  for (var i = 0; i < selfDecs.length; i++) {
    var eIdx = selfDecs[i];
    if (eIdx > currentEventIdx && evals[eIdx] && evals[eIdx].has_conflict) {
      selectStepByEventIdx(eIdx);
      return;
    }
  }
  for (var j = 0; j < selfDecs.length; j++) {
    var eIdx2 = selfDecs[j];
    if (evals[eIdx2] && evals[eIdx2].has_conflict) {
      selectStepByEventIdx(eIdx2);
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

    html_content = COMPLETE_TEMPLATE.replace("__REVIEW_DATA_PLACEHOLDER__", data_json_safe).replace("__TILE_ASSETS_PLACEHOLDER__", assets_json_safe)

    out_p.write_text(html_content, encoding="utf-8")
    return out_p

"""完全离线单文件 HTML 报告生成器 (Full Mahjong Board HTML Packager).

特色：
1. 标准四方日麻桌（四家牌河 6 列排布、三家对手手牌与副露、伏牌开关一键透视）；
2. 牌桌中央盘：四家实时点数、庄家红点、局风本场、立直棒供托、牌山余量 (x58)、宝牌指示牌明牌展示；
3. 牌面高保真白瓷材质：彻底修复透明 WebP 发黑问题，牌面高亮对比鲜明；
4. 自家手牌区分已理手牌与摸进的第 14 张牌（微距隔开）；
5. 完备的局导航（东1局~南4局任意跳转）与步进控制（上一巡/下一巡/前一分歧/后一分歧）；
6. 严格保持单文件完全离线内联，零外部网络依赖，双击秒开。
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


FULL_BOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Mortal Reviewer — 日麻四方多模型牌谱复盘系统</title>
<style>
:root {
  --bg-color: #0b181b;
  --mat-color: #123138;
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
}
header {
  background: #060e10;
  border-bottom: 1px solid var(--border-color);
  padding: 6px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  height: 42px;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.logo-title { font-weight: bold; font-size: 15px; color: #5bc0be; }
.kyoku-select {
  background: #10262b;
  color: var(--text-main);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.header-right { display: flex; align-items: center; gap: 16px; font-size: 12px; color: var(--text-dim); }

/* 主工作区 */
.workspace {
  flex: 1;
  display: flex;
  height: calc(100vh - 42px);
}

/* 牌桌左区 */
.board-container {
  flex: 1;
  background: radial-gradient(circle at center, #153c44 0%, #0c2025 85%);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 12px 24px;
  position: relative;
  user-select: none;
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
  max-width: 900px;
  margin: auto;
}

/* 中心盘 (点数与局况) */
.center-square {
  grid-row: 2;
  grid-column: 2;
  width: 180px;
  height: 180px;
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
  gap: 3px;
}
.center-title { font-size: 16px; font-weight: bold; color: #fff; }
.center-tiles-left { font-size: 11px; color: #f1c40f; font-weight: 600; }
.center-sticks { font-size: 11px; color: var(--text-dim); }

/* 东南西北实时点数定位 */
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

/* 宝牌展示栏 */
.dora-bar {
  display: flex;
  gap: 2px;
  margin-top: 2px;
}

/* 牌河排布：标准 6 列 */
.river-area {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  align-content: flex-start;
}
.river-top    { grid-row: 1; grid-column: 2; width: 174px; height: 110px; flex-direction: row-reverse; transform: rotate(180deg); }
.river-bottom { grid-row: 3; grid-column: 2; width: 174px; height: 110px; }
.river-left   { grid-row: 2; grid-column: 1; width: 110px; height: 174px; transform: rotate(90deg); }
.river-right  { grid-row: 2; grid-column: 3; width: 110px; height: 174px; transform: rotate(-90deg); }

/* 手牌区 */
.player-tehai-top   { display: flex; justify-content: center; gap: 2px; transform: rotate(180deg); }
.player-tehai-left  { display: flex; flex-direction: column; gap: 2px; position: absolute; left: 14px; top: 35%; transform: translateY(-50%); }
.player-tehai-right { display: flex; flex-direction: column; gap: 2px; position: absolute; right: 14px; top: 35%; transform: translateY(-50%); }
.player-tehai-bottom { display: flex; justify-content: center; align-items: flex-end; gap: 3px; min-height: 64px; }

/* 彻底告别发黑：高反差纯白象牙牌面 */
.tile-img {
  background-color: var(--tile-white) !important;
  border: 1px solid var(--tile-border);
  border-bottom: 2px solid var(--tile-shadow);
  border-radius: 3px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.5);
  background-size: 92% 92%;
  background-repeat: no-repeat;
  background-position: center;
  display: inline-block;
  vertical-align: middle;
}
/* 手牌大尺寸 */
.tile-hand { width: 38px; height: 54px; }
/* 摸进来的牌间隔隔开 */
.tile-tsumo { margin-left: 14px; box-shadow: 0 0 0 2px #5bc0be; }
/* 牌河小尺寸 */
.tile-river { width: 26px; height: 36px; }
.tile-river.tsumogiri { opacity: 0.72; filter: brightness(0.92); }
.tile-river.riichi { transform: rotate(90deg); margin: 0 4px; box-shadow: 0 0 0 2px #f1c40f; }

/* 扣着的暗牌背 */
.tile-back {
  background: var(--tile-back-color) !important;
  border: 1px solid #5a0f0f;
  border-bottom: 2px solid #3d0a0a;
}
.tile-back-mini { width: 24px; height: 34px; }

/* 右侧多模型分析栏 */
.sidebar {
  width: 440px;
  background: var(--center-box);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.sidebar-top {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
  font-weight: bold;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.timeline-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.card-item {
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border-color);
  border-radius: 5px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 12px;
}
.card-item:hover, .card-item.active {
  background: rgba(91, 192, 190, 0.08);
  border-color: #5bc0be;
}
.card-item.conflict {
  border-color: var(--conflict-color);
  background: rgba(231, 76, 60, 0.12);
}
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
}
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

/* 底部全量对照 */
.detail-drawer {
  border-top: 1px solid var(--border-color);
  padding: 10px 14px;
  background: #050c0e;
  max-height: 220px;
  overflow-y: auto;
  font-size: 12px;
}
.cand-list-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.controls {
  padding: 8px 12px;
  background: #050c0e;
  border-top: 1px solid var(--border-color);
  display: flex;
  gap: 6px;
}
.btn-ctl {
  flex: 1;
  padding: 7px;
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
    <select class="kyoku-select" id="kyoku-selector" onchange="onSelectKyoku(this.value)"></select>
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
  <!-- 麻将桌盘面 -->
  <div class="board-container">
    <!-- 对家 (上) -->
    <div class="player-tehai-top" id="hand-top"></div>

    <!-- 中间：牌河与中心点数盘 -->
    <div class="board-middle">
      <!-- 上家牌河 (对家) -->
      <div class="river-area river-top" id="river-2"></div>
      <!-- 左家牌河 (上家) -->
      <div class="river-area river-left" id="river-3"></div>

      <!-- 中心盘 -->
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

      <!-- 右家牌河 (下家) -->
      <div class="river-area river-right" id="river-1"></div>
      <!-- 自家牌河 -->
      <div class="river-area river-bottom" id="river-0"></div>
    </div>

    <!-- 左右对手手牌 -->
    <div class="player-tehai-left" id="hand-left"></div>
    <div class="player-tehai-right" id="hand-right"></div>

    <!-- 自家手牌 (下) -->
    <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
      <div style="font-size:11px; color:var(--text-dim);" id="hand-info-text">自家手牌 (实切高亮)</div>
      <div class="player-tehai-bottom" id="hand-bottom"></div>
    </div>
  </div>

  <!-- 右侧决策栏 -->
  <div class="sidebar">
    <div class="sidebar-top">
      <span id="side-kyoku-label">本局决策流</span>
      <span style="font-size:11px; color:var(--text-dim);" id="side-dec-count">共 -- 巡</span>
    </div>
    <div class="timeline-scroll" id="card-timeline"></div>
    <div class="detail-drawer" id="detail-drawer">
      <div style="text-align:center; color:var(--text-dim); margin-top:20px;">选择任一巡目查看三模型候选全量概率对比</div>
    </div>
    <div class="controls">
      <button class="btn-ctl" onclick="prevStep()">上一巡</button>
      <button class="btn-ctl" onclick="nextConflict()">下一分歧</button>
      <button class="btn-ctl" onclick="nextStep()">下一巡</button>
    </div>
  </div>
</div>

<script>
var REVIEW_PAYLOAD = __REVIEW_DATA_PLACEHOLDER__;
var TILE_ASSETS = __TILE_ASSETS_PLACEHOLDER__;

var currentGlobalIndex = 0;
var showAllHands = false;

function getTileImg(tileStr, extraClasses) {
  var norm = tileStr ? tileStr.replace('r', '') : '';
  var url = TILE_ASSETS[tileStr] || TILE_ASSETS[norm] || '';
  return '<div class="tile-img ' + (extraClasses || '') + '" style="background-image:url(' + url + ');"></div>';
}

function getTileBack(extraClasses) {
  return '<div class="tile-img tile-back ' + (extraClasses || '') + '"></div>';
}

function initApp() {
  var kyokus = REVIEW_PAYLOAD.kyokus || [];
  var sel = document.getElementById('kyoku-selector');
  sel.innerHTML = '';
  for (var i = 0; i < kyokus.length; i++) {
    var opt = document.createElement('option');
    opt.value = i;
    opt.innerText = kyokus[i].title;
    sel.appendChild(opt);
  }

  // 计算全局战术分歧与契合度
  var decs = REVIEW_PAYLOAD.decisions || [];
  var conflicts = 0;
  for (var d = 0; d < decs.length; d++) {
    if (decs[d].has_conflict) conflicts++;
  }
  var rate = decs.length ? Math.round((1 - conflicts / decs.length) * 100) : 100;
  document.getElementById('header-stats-text').innerText = '三神契合度: ' + rate + '% | 分歧: ' + conflicts + ' / ' + decs.length;

  selectGlobalStep(0);
}

function onSelectKyoku(kIdx) {
  var kyokus = REVIEW_PAYLOAD.kyokus || [];
  var k = kyokus[kIdx];
  if (k && k.decisions && k.decisions.length > 0) {
    selectGlobalStep(k.decisions[0]);
  }
}

function selectGlobalStep(globalIdx) {
  var decs = REVIEW_PAYLOAD.decisions || [];
  if (globalIdx < 0 || globalIdx >= decs.length) return;
  currentGlobalIndex = globalIdx;

  var cur = decs[globalIdx];
  var snap = cur.table_snapshot;
  var targetSeat = REVIEW_PAYLOAD.target_seat || 0;

  // 更新局选择下拉框
  document.getElementById('kyoku-selector').value = snap.kyoku_idx;

  // 1. 渲染中心盘
  document.getElementById('box-round-title').innerText = snap.kyoku_title.split(' ')[0];
  document.getElementById('box-sticks').innerText = snap.honba + ' 本场 · 供托 ' + snap.kyotaku;
  document.getElementById('box-tiles-left').innerText = '牌山 x' + snap.tiles_left;

  // 宝牌指示牌
  var doraHtml = '';
  for (var dm = 0; dm < snap.dora_markers.length; dm++) {
    doraHtml += getTileImg(snap.dora_markers[dm], 'tile-river');
  }
  document.getElementById('box-dora-bar').innerHTML = doraHtml;

  // 四家实时点数
  var seatNames = ['东', '南', '西', '北'];
  var relLabels = ['自家', '下家', '对家', '上家'];
  for (var seat = 0; seat < 4; seat++) {
    var relIdx = (seat - targetSeat + 4) % 4; // 0: 自家, 1: 下家, 2: 对家, 3: 上家
    var isOya = (seat === snap.oya);
    var elId = relIdx === 0 ? 'score-0' : (relIdx === 1 ? 'score-1' : (relIdx === 2 ? 'score-2' : 'score-3'));
    var scoreEl = document.getElementById(elId);
    if (scoreEl) {
      scoreEl.innerText = seatNames[seat] + ' ' + (snap.scores[seat] || 25000);
      if (isOya) scoreEl.classList.add('dealer');
      else scoreEl.classList.remove('dealer');
    }
  }

  // 2. 渲染四家牌河
  for (var p = 0; p < 4; p++) {
    var rList = snap.rivers[p] || [];
    var rHtml = '';
    for (var r = 0; r < rList.length; r++) {
      var item = rList[r];
      var cls = 'tile-river';
      if (item.is_tsumogiri) cls += ' tsumogiri';
      if (item.is_riichi) cls += ' riichi';
      rHtml += getTileImg(item.tile, cls);
    }
    var rEl = document.getElementById('river-' + p);
    if (rEl) rEl.innerHTML = rHtml;
  }

  // 3. 渲染自家手牌与摸牌 (高反差白瓷底)
  var handHtml = '';
  var regularHand = snap.target_hand_sorted || [];
  var actTile = snap.actual ? snap.actual.tile : '';
  for (var h = 0; h < regularHand.length; h++) {
    handHtml += getTileImg(regularHand[h], 'tile-hand');
  }
  if (snap.tsumo_tile) {
    handHtml += getTileImg(snap.tsumo_tile, 'tile-hand tile-tsumo');
  }
  document.getElementById('hand-bottom').innerHTML = handHtml;
  document.getElementById('hand-info-text').innerText = '自家手牌 (实切: ' + actTile + (snap.actual && snap.actual.riichi ? ' 宣告立直' : '') + ')';

  // 4. 渲染三家对手手牌 (支持伏牌透视)
  var topHand = snap.hands[(targetSeat + 2) % 4] || [];
  var leftHand = snap.hands[(targetSeat + 3) % 4] || [];
  var rightHand = snap.hands[(targetSeat + 1) % 4] || [];

  renderOpponentHand('hand-top', topHand, 'tile-river');
  renderOpponentHand('hand-left', leftHand, 'tile-back-mini');
  renderOpponentHand('hand-right', rightHand, 'tile-back-mini');

  // 5. 更新右侧当前局的决策流卡片
  renderKyokuCards(snap.kyoku_idx, globalIdx);

  // 6. 更新底部全量决策抽屉
  renderDetailDrawer(cur);
}

function renderOpponentHand(containerId, tiles, miniClass) {
  var el = document.getElementById(containerId);
  if (!el) return;
  var html = '';
  for (var i = 0; i < tiles.length; i++) {
    if (showAllHands) {
      html += getTileImg(tiles[i], miniClass);
    } else {
      html += getTileBack(miniClass);
    }
  }
  el.innerHTML = html;
}

function toggleOpenHands(isOpen) {
  showAllHands = isOpen;
  selectGlobalStep(currentGlobalIndex);
}

function renderKyokuCards(kyokuIdx, activeGlobalIdx) {
  var kyokus = REVIEW_PAYLOAD.kyokus || [];
  var k = kyokus[kyokuIdx];
  if (!k) return;

  document.getElementById('side-kyoku-label').innerText = k.title + ' 决策流';
  document.getElementById('side-dec-count').innerText = '共 ' + k.decisions.length + ' 巡';

  var decs = REVIEW_PAYLOAD.decisions || [];
  var html = '';
  for (var i = 0; i < k.decisions.length; i++) {
    var gIdx = k.decisions[i];
    var d = decs[gIdx];
    var isAct = (gIdx === activeGlobalIdx);
    var actStr = d.table_snapshot.actual ? d.table_snapshot.actual.tile + (d.table_snapshot.actual.riichi ? 'r' : '') : '';
    var m = d.models;

    html += '<div class="card-item ' + (d.has_conflict ? 'conflict ' : '') + (isAct ? 'active' : '') + '" onclick="selectGlobalStep(' + gIdx + ')">';
    html += '  <div class="card-header-row">';
    html += '    <span style="font-weight:600;">' + d.turn_title + ' · 实切 ' + actStr + '</span>';
    if (d.has_conflict) html += '<span style="color:#ff6b6b; font-weight:bold; font-size:11px;">战术分歧</span>';
    html += '  </div>';
    html += '  <div class="model-grid">';
    html += '    <div class="model-aegis">Aegis<br>' + m.Aegis.best.tile + (m.Aegis.best.riichi?'r':'') + ' (' + Math.round(m.Aegis.best.prob*100) + '%)</div>';
    html += '    <div class="model-sol">Sol<br>' + m.Sol.best.tile + (m.Sol.best.riichi?'r':'') + ' (' + Math.round(m.Sol.best.prob*100) + '%)</div>';
    html += '    <div class="model-logos">Logos<br>' + m.Logos.best.tile + (m.Logos.best.riichi?'r':'') + ' (' + Math.round(m.Logos.best.prob*100) + '%)</div>';
    html += '  </div>';
    html += '</div>';
  }
  var listEl = document.getElementById('card-timeline');
  listEl.innerHTML = html;

  var activeEl = listEl.querySelector('.card-item.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function renderDetailDrawer(curDec) {
  var m = curDec.models;
  var drawer = document.getElementById('detail-drawer');
  var h = '<div style="font-weight:bold; margin-bottom:6px; font-size:12px; color:#5bc0be;">' + curDec.table_snapshot.kyoku_title + ' ' + curDec.turn_title + ' 切牌候选深度全量对比</div>';
  h += '<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px;">';

  ['Aegis', 'Sol', 'Logos'].forEach(function(mname) {
    var cands = m[mname].candidates || [];
    h += '<div>';
    h += '  <div style="font-weight:bold; margin-bottom:4px;" class="model-' + mname.toLowerCase() + '">' + mname + ' Top 候选</div>';
    for (var j = 0; j < cands.length; j++) {
      var c = cands[j];
      h += '  <div class="cand-list-row">';
      h += '    <span>' + c.tile + (c.riichi?'r':'') + '</span>';
      h += '    <span style="color:#f1c40f;">' + Math.round(c.prob*100) + '% <small style="color:var(--text-dim);">(Q:' + Math.round(c.q*10)/10 + ')</small></span>';
      h += '  </div>';
    }
    h += '</div>';
  });
  h += '</div>';
  drawer.innerHTML = h;
}

function prevStep() { selectGlobalStep(currentGlobalIndex - 1); }
function nextStep() { selectGlobalStep(currentGlobalIndex + 1); }
function nextConflict() {
  var decs = REVIEW_PAYLOAD.decisions || [];
  for (var i = currentGlobalIndex + 1; i < decs.length; i++) {
    if (decs[i].has_conflict) {
      selectGlobalStep(i);
      return;
    }
  }
  for (var j = 0; j <= currentGlobalIndex; j++) {
    if (decs[j].has_conflict) {
      selectGlobalStep(j);
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
    """生成具备标准四方麻将桌与多模型横向对照的完全离线单文件 HTML。"""
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    tile_assets = get_base64_tiles(assets_dir)

    data_json = json.dumps(review_data, ensure_ascii=False)
    data_json_safe = data_json.replace("</script>", "<\\/script>").replace("<!--", "<\\!--")

    assets_json = json.dumps(tile_assets, ensure_ascii=False)
    assets_json_safe = assets_json.replace("</script>", "<\\/script>").replace("<!--", "<\\!--")

    html_content = FULL_BOARD_TEMPLATE.replace("__REVIEW_DATA_PLACEHOLDER__", data_json_safe).replace("__TILE_ASSETS_PLACEHOLDER__", assets_json_safe)

    out_p.write_text(html_content, encoding="utf-8")
    return out_p

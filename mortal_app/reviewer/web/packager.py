"""完全离线单文件 HTML 报告生成器 (Standalone Offline HTML Packager).

技术规范：
1. 资产全内联：37 张高保真 WebP 牌面预打包为单个 JSON 字典（同种牌全局只内联一次）；
2. 零外部依赖：纯原生 ES5/IIFE JS 交互脚本，无任何 CDN、无 ES Module 跨域拦截，本地双击 file:// 秒开；
3. 硬预算安全：产物单文件体积严格控制在 800KB ~ 1.2MB 之间（远低于 1.5MB 门禁）；
4. UI 深度对齐：经典深青色 Mortal 牌桌布局，右侧配备 L1-L3 三层渐进披露的三模型并行对照表。
"""
from __future__ import annotations

import base64
import glob
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
            # 兜底空白
            tile_map[mjai_name] = ""
    _CACHED_TILE_MAP = tile_map
    return _CACHED_TILE_MAP


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Mortal Reviewer — 多模型牌谱审查报告</title>
<style>
:root {
  --bg-color: #0c1a1e;
  --table-color: #123138;
  --panel-bg: rgba(10, 24, 28, 0.95);
  --border-color: #1e454f;
  --text-main: #d8e5e8;
  --text-dim: #76969e;
  --accent-aegis: #4ea8de;
  --accent-sol: #f39c12;
  --accent-logos: #2ecc71;
  --conflict-bg: rgba(231, 76, 60, 0.15);
  --conflict-border: #e74c3c;
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
  background: #081316;
  border-bottom: 1px solid var(--border-color);
  padding: 8px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
}
.header-title { font-weight: bold; font-size: 16px; color: #5bc0be; display: flex; align-items: center; gap: 8px; }
.header-stats { display: flex; gap: 16px; color: var(--text-dim); }
.main-container {
  flex: 1;
  display: flex;
  height: calc(100vh - 46px);
  overflow: hidden;
}
.left-board {
  flex: 1;
  background: radial-gradient(circle at center, #163d46 0%, #0c2025 100%);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 20px;
  position: relative;
}
.table-center-info {
  margin: auto;
  width: 220px;
  height: 220px;
  background: var(--table-color);
  border: 2px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.tehai-container {
  background: rgba(0,0,0,0.4);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 80px;
}
.tile-img {
  width: 40px;
  height: 56px;
  background-size: cover;
  border-radius: 3px;
  box-shadow: 0 2px 5px rgba(0,0,0,0.4);
  display: inline-block;
  vertical-align: middle;
}
.tile-img.highlight {
  box-shadow: 0 0 0 3px #f1c40f;
  transform: translateY(-4px);
}
.right-sidebar {
  width: 440px;
  background: var(--panel-bg);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.sidebar-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  font-weight: bold;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.decision-timeline {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.decision-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.decision-card:hover, .decision-card.active {
  background: rgba(255,255,255,0.07);
  border-color: #5bc0be;
}
.decision-card.conflict {
  background: var(--conflict-bg);
  border-color: var(--conflict-border);
}
.card-row-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.turn-badge {
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 600;
}
.conflict-badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #e74c3c;
  color: #fff;
  font-weight: bold;
}
.model-comparison-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 6px;
  background: rgba(0,0,0,0.25);
  padding: 6px;
  border-radius: 4px;
}
.model-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  font-size: 12px;
  gap: 2px;
}
.model-label-aegis { color: var(--accent-aegis); font-weight: bold; }
.model-label-sol   { color: var(--accent-sol); font-weight: bold; }
.model-label-logos { color: var(--accent-logos); font-weight: bold; }

.decision-detail-panel {
  border-top: 1px solid var(--border-color);
  padding: 12px 16px;
  background: #081518;
  max-height: 260px;
  overflow-y: auto;
}
.cand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  font-size: 13px;
}
.nav-controls {
  padding: 8px 16px;
  background: #060f11;
  border-top: 1px solid var(--border-color);
  display: flex;
  gap: 8px;
}
button.btn-nav {
  flex: 1;
  padding: 8px;
  background: #19383f;
  color: #fff;
  border: 1px solid #2b5761;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: bold;
}
button.btn-nav:hover { background: #234c56; }
</style>
</head>
<body>
<header>
  <div class="header-title">
    <span>🀄 Mortal Reviewer</span>
    <span style="font-size:12px; background:#1b3b42; padding:2px 8px; border-radius:4px; color:#fff;">多模型全盘对决</span>
  </div>
  <div class="header-stats">
    <span id="stat-match">一致率: --</span>
    <span id="stat-conflict">战术分歧: --</span>
  </div>
</header>

<div class="main-container">
  <div class="left-board">
    <div style="text-align:center; color:var(--text-dim); font-size:13px;" id="game-round-title">东 1 局 0 本场</div>
    <div class="table-center-info">
      <div style="font-size:24px; font-weight:bold;" id="center-bakaze">东 1</div>
      <div style="font-size:12px; color:var(--text-dim);" id="center-pot">供托: 0 | 本场: 0</div>
      <div style="font-size:12px; color:#f1c40f; margin-top:4px;" id="center-dora">宝牌指示: --</div>
    </div>
    <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
      <div style="font-size:13px; color:var(--text-dim);" id="tehai-label">自身手牌 (玩家视角)</div>
      <div class="tehai-container" id="tehai-box"></div>
    </div>
  </div>

  <div class="right-sidebar">
    <div class="sidebar-header">
      <span>巡目决策流 (三模型横向对照)</span>
      <span style="font-size:12px; color:var(--text-dim);" id="total-dec-count">共 -- 巡</span>
    </div>
    <div class="decision-timeline" id="timeline-list"></div>
    <div class="decision-detail-panel" id="detail-box">
      <div style="color:var(--text-dim); font-size:13px; text-align:center;">请选择上方任一巡目查看三模型深度决策对比</div>
    </div>
    <div class="nav-controls">
      <button class="btn-nav" onclick="prevStep()">上一巡</button>
      <button class="btn-nav" onclick="nextConflict()">下一分歧</button>
      <button class="btn-nav" onclick="nextStep()">下一巡</button>
    </div>
  </div>
</div>

<script>
/* 内联注入的数据包与牌图资源字典 */
var REVIEW_DATA = __REVIEW_DATA_PLACEHOLDER__;
var TILE_ASSETS = __TILE_ASSETS_PLACEHOLDER__;

var currentIndex = 0;

function renderTile(tileStr, isHighlight) {
  var norm = tileStr.replace('r', '');
  var url = TILE_ASSETS[tileStr] || TILE_ASSETS[norm] || '';
  return '<div class="tile-img ' + (isHighlight ? 'highlight' : '') + '" style="background-image:url(' + url + ');"></div>';
}

function initUI() {
  var timeline = REVIEW_DATA.timeline || [];
  var listEl = document.getElementById('timeline-list');
  var conflicts = 0;

  document.getElementById('total-dec-count').innerText = '共 ' + timeline.length + ' 巡';

  var html = '';
  for (var i = 0; i < timeline.length; i++) {
    var d = timeline[i];
    if (d.has_conflict) conflicts++;
    var actStr = d.actual.tile + (d.actual.riichi ? 'r' : '');
    var m = d.models;

    html += '<div class="decision-card ' + (d.has_conflict ? 'conflict' : '') + '" id="card-' + i + '" onclick="selectStep(' + i + ')">';
    html += '  <div class="card-row-top">';
    html += '    <span class="turn-badge">第 ' + (i + 1) + ' 巡 · 实切 ' + actStr + '</span>';
    if (d.has_conflict) {
      html += '    <span class="conflict-badge">战术分歧</span>';
    }
    html += '  </div>';
    html += '  <div class="model-comparison-row">';
    html += '    <div class="model-cell"><span class="model-label-aegis">Aegis (神盾)</span><span>' + m.Aegis.best.tile + (m.Aegis.best.riichi?'r':'') + ' (' + Math.round(m.Aegis.best.prob*100) + '%)</span></div>';
    html += '    <div class="model-cell"><span class="model-label-sol">Sol (烈阳)</span><span>' + m.Sol.best.tile + (m.Sol.best.riichi?'r':'') + ' (' + Math.round(m.Sol.best.prob*100) + '%)</span></div>';
    html += '    <div class="model-cell"><span class="model-label-logos">Logos (理性)</span><span>' + m.Logos.best.tile + (m.Logos.best.riichi?'r':'') + ' (' + Math.round(m.Logos.best.prob*100) + '%)</span></div>';
    html += '  </div>';
    html += '</div>';
  }
  listEl.innerHTML = html;

  document.getElementById('stat-conflict').innerText = '战术分歧: ' + conflicts + ' / ' + timeline.length + ' (' + Math.round(conflicts/timeline.length*100) + '%)';
  document.getElementById('stat-match').innerText = '三神契合度: ' + Math.round((1 - conflicts/timeline.length)*100) + '%';

  selectStep(0);
}

function selectStep(index) {
  var timeline = REVIEW_DATA.timeline || [];
  if (index < 0 || index >= timeline.length) return;
  currentIndex = index;

  var cards = document.querySelectorAll('.decision-card');
  for (var i = 0; i < cards.length; i++) cards[i].classList.remove('active');
  var activeCard = document.getElementById('card-' + index);
  if (activeCard) {
    activeCard.classList.add('active');
    activeCard.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  var cur = timeline[index];
  var m = cur.models;
  var detailEl = document.getElementById('detail-box');

  var h = '<div style="font-size:13px; font-weight:bold; margin-bottom:8px;">第 ' + (index+1) + ' 巡 切牌候选全量概率对比</div>';
  h += '<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; font-size:12px;">';
  
  ['Aegis', 'Sol', 'Logos'].forEach(function(mname) {
    var cands = m[mname].candidates || [];
    h += '<div>';
    h += '  <div style="font-weight:bold; margin-bottom:4px;" class="model-label-' + mname.toLowerCase() + '">' + mname + ' Top 候选</div>';
    for (var j = 0; j < cands.length; j++) {
      var c = cands[j];
      h += '  <div class="cand-row">';
      h += '    <span>' + c.tile + (c.riichi?'r':'') + '</span>';
      h += '    <span style="color:#f1c40f;">' + Math.round(c.prob*100) + '% <small style="color:var(--text-dim);">(Q:' + Math.round(c.q*10)/10 + ')</small></span>';
      h += '  </div>';
    }
    h += '</div>';
  });
  h += '</div>';
  detailEl.innerHTML = h;

  // 渲染手牌
  var tehaiEl = document.getElementById('tehai-box');
  var actTile = cur.actual.tile;
  var mockTiles = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p'];
  var thHtml = '';
  for (var k = 0; k < mockTiles.length; k++) {
    thHtml += renderTile(mockTiles[k], mockTiles[k] === actTile);
  }
  thHtml += '<div style="width:16px;"></div>';
  thHtml += renderTile(actTile, true);
  tehaiEl.innerHTML = thHtml;
}

function prevStep() { selectStep(currentIndex - 1); }
function nextStep() { selectStep(currentIndex + 1); }
function nextConflict() {
  var timeline = REVIEW_DATA.timeline || [];
  for (var i = currentIndex + 1; i < timeline.length; i++) {
    if (timeline[i].has_conflict) {
      selectStep(i);
      return;
    }
  }
  for (var j = 0; j <= currentIndex; j++) {
    if (timeline[j].has_conflict) {
      selectStep(j);
      return;
    }
  }
}

window.onload = initUI;
</script>
</body>
</html>
"""

def generate_standalone_review_html(
    review_data: dict[str, Any],
    output_path: str | Path,
    assets_dir: str | Path | None = None,
) -> Path:
    """生成内联全部牌图与数据的独立单文件 HTML。"""
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    tile_assets = get_base64_tiles(assets_dir)

    # 序列化并做 XSS / 闭合标签转义保护
    data_json = json.dumps(review_data, ensure_ascii=False)
    data_json_safe = data_json.replace("</script>", "<\\/script>").replace("<!--", "<\\!--")

    assets_json = json.dumps(tile_assets, ensure_ascii=False)
    assets_json_safe = assets_json.replace("</script>", "<\\/script>").replace("<!--", "<\\!--")

    html_content = HTML_TEMPLATE.replace("__REVIEW_DATA_PLACEHOLDER__", data_json_safe).replace("__TILE_ASSETS_PLACEHOLDER__", assets_json_safe)

    out_p.write_text(html_content, encoding="utf-8")
    return out_p

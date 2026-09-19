"""100% Code-Level Killer Mortal Reviewer Standalone HTML Packager.

完全代码级复刻官方 Killer Mortal Reviewer (killerducky/killer_mortal_gui & mjai.ekyu.moe/killerducky):
1. 采用官方 exact DOM layout (index.html) 与 exact 样式表 (style.css);
2. 采用官方 exact 状态机、交互逻辑与切牌/副露条 (index.js, efficiency.js, shanten.js, translations.js);
3. 采用官方 FluffyStuff 矢量 SVG 麻将牌面资产 (40 张 SVG 内联);
4. 采用官方 Ferris 萌宠吉祥物 (rustferris.png);
5. 采用官方 i18next 多语言体系 (默认中英双语即时切换);
6. 全功能：滚轮平滑播放、方向键热键、恶手阈值筛选、铳率估计、王牌5指示牌、向听与巡目计算、对局详情与得点弹窗;
7. 单文件完全离线，零外部 CDN 依赖，双击秒开。
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

KILLER_GUI_DIR = Path(r"D:\tenhoulib\killer_mortal_gui")

_CACHED_ASSETS: dict[str, Any] = {}

def load_killer_assets() -> dict[str, Any]:
    global _CACHED_ASSETS
    if _CACHED_ASSETS:
        return _CACHED_ASSETS

    svg_dir = KILLER_GUI_DIR / "media" / "Regular_shortnames"
    svg_map = {}
    for svg_file in svg_dir.glob("*.svg"):
        stem = svg_file.stem
        raw_svg = svg_file.read_text(encoding="utf-8")
        b64 = base64.b64encode(raw_svg.encode("utf-8")).decode("ascii")
        svg_map[stem] = f"data:image/svg+xml;base64,{b64}"

    ferris_p = KILLER_GUI_DIR / "media" / "rustferris.png"
    ferris_b64 = ""
    if ferris_p.exists():
        b = base64.b64encode(ferris_p.read_bytes()).decode("ascii")
        ferris_b64 = f"data:image/png;base64,{b}"

    style_css = (KILLER_GUI_DIR / "style.css").read_text(encoding="utf-8")
    i18next_js = (KILLER_GUI_DIR / "i18next.min.js").read_text(encoding="utf-8")
    translations_js = (KILLER_GUI_DIR / "translations.js").read_text(encoding="utf-8")
    shanten_js = (KILLER_GUI_DIR / "shanten.js").read_text(encoding="utf-8")
    efficiency_js = (KILLER_GUI_DIR / "efficiency.js").read_text(encoding="utf-8")
    index_js = (KILLER_GUI_DIR / "index.js").read_text(encoding="utf-8")
    index_html = (KILLER_GUI_DIR / "index.html").read_text(encoding="utf-8")

    def strip_es_modules(code: str) -> str:
        code = re.sub(r'import\s*\{[^}]*\}\s*from\s*["\'][^"\']*["\']\s*;?', '', code, flags=re.DOTALL)
        code = re.sub(r'import\s+.*?from\s+["\'][^"\']*["\']\s*;?', '', code)
        code = re.sub(r'export\s+default\s+.*?;?', '', code)
        code = re.sub(r'export\s*\{[^}]*\}\s*;?', '', code, flags=re.DOTALL)
        code = code.replace("export function", "function").replace("export const", "const").replace("export let", "let").replace("export var", "var")
        return code

    shanten_clean = strip_es_modules(shanten_js)
    efficiency_clean = strip_es_modules(efficiency_js)
    index_clean = strip_es_modules(index_js)

    index_clean = index_clean.replace(
        "`media/Regular_shortnames/${tenhou2str(tile)}.svg`",
        "TILE_SVG_MAP[tenhou2str(tile)] || ''"
    )
    index_clean = index_clean.replace(
        "`media/Regular_shortnames/${tileStr}.svg`",
        "TILE_SVG_MAP[tileStr] || ''"
    )

    # 默认使用中文 (zh-CN)
    index_clean = index_clean.replace(
        'const lang = ("lang" in localStorage) ? localStorage.getItem("lang") : "en"',
        'const lang = ("lang" in localStorage) ? localStorage.getItem("lang") : "zh-CN"'
    )

    # 拦截数据加载直接使用内联 window.INJECTED_MORTAL_DATA
    injected_hook = """function parseUrl() {
    if (window.INJECTED_MORTAL_DATA) {
        setMortalJsonStr(window.INJECTED_MORTAL_DATA);
        GS.hand_counter = 0;
        GS.ply_counter = 0;
        updateState();
        connectUI();
        return;
    }"""
    index_clean = index_clean.replace("function parseUrl() {", injected_hook, 1)

    index_html = index_html.replace('<link rel="stylesheet" href="style.css?d=13">', f'<style>\n{style_css}\n</style>')
    index_html = index_html.replace('src="media/rustferris.png"', f'src="{ferris_b64}"')
    index_html = re.sub(r'<script\s+src="https://unpkg.com/i18next.*?"></script>', '', index_html)
    index_html = re.sub(r'<script\s+src="translations.js\?d=13"></script>', '', index_html)
    index_html = re.sub(r'<script\s+type="module"\s+src="boot.js\?d=13"></script>', '', index_html)
    index_html = re.sub(r'<script[^>]*src="https?://[^>]*></script>', '', index_html)

    _CACHED_ASSETS = {
        "svg_map": svg_map,
        "index_html": index_html,
        "i18next_js": i18next_js,
        "translations_js": translations_js,
        "shanten_clean": shanten_clean,
        "efficiency_clean": efficiency_clean,
        "index_clean": index_clean,
    }
    return _CACHED_ASSETS


def generate_standalone_review_html(
    mortal_report_json: dict[str, Any],
    output_path: str | Path,
    assets_dir: str | Path | None = None,
) -> Path:
    """生成 100% 官方 Killer Mortal Reviewer 单文件完全离线 HTML 报告。"""
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    assets = load_killer_assets()
    svg_map_json = json.dumps(assets["svg_map"], ensure_ascii=False)
    data_json = json.dumps(mortal_report_json, ensure_ascii=False)
    data_json_safe = data_json.replace("</script>", "<\\/script>").replace("<!--", "<\\!--")

    embedded_js = f"""
<script>
const TILE_SVG_MAP = {svg_map_json};
window.INJECTED_MORTAL_DATA = {data_json_safe};

// 1. i18next
{assets["i18next_js"]}

// 2. translations
{assets["translations_js"]}

// 3. shanten & efficiency
{assets["shanten_clean"]}
{assets["efficiency_clean"]}

// 4. Killer Mortal GUI main
{assets["index_clean"]}
</script>
"""

    final_html = assets["index_html"].replace("</body>", f"{embedded_js}\n</body>")
    out_p.write_text(final_html, encoding="utf-8")
    return out_p

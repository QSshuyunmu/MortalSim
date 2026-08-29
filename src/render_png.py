"""MortalSim 4K 决策报表渲染引擎 (全简体中文、95%置信区间、微图表、浮起手牌与多主题支持)。"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont

TILE_NAMES = [
    "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
    "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
    "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
    "1z", "2z", "3z", "4z", "5z", "6z", "7z",
    "0m", "0p", "0s",
]

_TILE_CACHE: dict[tuple[str, str, int, int], Image.Image] = {}

WEBP_TILE_MAP = {
    "1m": "Man1.webp", "2m": "Man2.webp", "3m": "Man3.webp", "4m": "Man4.webp", "5m": "Man5.webp", "0m": "Man5-Dora.webp", "6m": "Man6.webp", "7m": "Man7.webp", "8m": "Man8.webp", "9m": "Man9.webp",
    "1p": "Pin1.webp", "2p": "Pin2.webp", "3p": "Pin3.webp", "4p": "Pin4.webp", "5p": "Pin5.webp", "0p": "Pin5-Dora.webp", "6p": "Pin6.webp", "7p": "Pin7.webp", "8p": "Pin8.webp", "9p": "Pin9.webp",
    "1s": "Sou1.webp", "2s": "Sou2.webp", "3s": "Sou3.webp", "4s": "Sou4.webp", "5s": "Sou5.webp", "0s": "Sou5-Dora.webp", "6s": "Sou6.webp", "7s": "Sou7.webp", "8s": "Sou8.webp", "9s": "Sou9.webp",
    "1z": "Ton.webp", "2z": "Nan.webp", "3z": "Shaa.webp", "4z": "Pei.webp", "5z": "Haku.svg", "6z": "Hatsu.webp", "7z": "Chun.webp",
    "e": "Ton.webp", "s": "Nan.webp", "w": "Shaa.webp", "n": "Pei.webp", "p": "Haku.svg", "f": "Hatsu.webp", "c": "Chun.webp",
}

YAKU_NAME_ZH = {
    "riichi": "立直", "double_riichi": "双立直", "ippatsu": "一发", "menzen_tsumo": "门清自摸",
    "tanyao": "断幺九", "pinfu": "平和", "iipeikou": "一平口",
    "seat_wind_east": "自风东", "seat_wind_south": "自风南", "seat_wind_west": "自风西", "seat_wind_north": "自风北",
    "round_wind_east": "场风东", "round_wind_south": "场风南", "round_wind_west": "场风西", "round_wind_north": "场风北",
    "haku": "役牌白", "hatsu": "役牌发", "chun": "役牌中",
    "rinshan": "岭上开花", "chankan": "抢杠", "haitei": "海底摸月", "houtei": "河底捞鱼",
    "sanshoku_doujun": "三色同顺", "ikkitsuukan": "一气通贯", "chanta": "混全带幺", "chiitoitsu": "七对子",
    "toitoi": "对对和", "sanankou": "三暗刻", "honroutou": "混老头", "sanshoku_doukou": "三色同刻",
    "sankantsu": "三杠子", "shousangen": "小三元", "honitsu": "混一色", "junchan": "纯全带幺",
    "ryanpeikou": "二平口", "chinitsu": "清一色", "kokushi": "国士无双", "suuankou": "四暗刻",
    "daisangen": "大三元", "shousuushii": "小四喜", "daisuushii": "大四喜", "tsuuiisou": "字一色",
    "chinroutou": "清老头", "ryuuiisou": "绿一色", "chuuren": "九莲宝灯", "suukantsu": "四杠子",
    "tenhou": "天和", "chiihou": "地和", "renhou": "人和", "nagashi_mangan": "流局满贯",
    "dora": "宝牌", "ura_dora": "里宝牌", "aka_dora": "赤宝牌",
}

KYOKU_FULL_NAME_ZH = {
    "E1": "东一局", "E2": "东二局", "E3": "东三局", "E4": "东四局",
    "S1": "南一局", "S2": "南二局", "S3": "南三局", "S4": "南四局",
    "W1": "西一局", "W2": "西二局", "W3": "西三局", "W4": "西四局",
}

THEME_CONFIGS = {
    "obsidian": {
        "title": "黑曜深空",
        "bg": (12, 16, 22, 255),
        "header_bg": (8, 11, 16, 255),
        "panel_bg": (18, 23, 31, 255),
        "panel_border": (38, 48, 62, 255),
        "table_mat": (14, 28, 38, 255),
        "table_frame": (30, 65, 88, 255),
        "center_box": (12, 18, 26, 255),
        "text_white": (240, 245, 250, 255),
        "text_accent": (75, 175, 255, 255),
        "text_gold": (245, 195, 68, 255),
        "text_muted": (135, 150, 168, 255),
        "rec_emerald": (40, 215, 140, 255),
        "rec_row_bg": (18, 48, 36, 255),
        "row_alt": (23, 29, 39, 255),
        "badge_bg": (25, 75, 140, 255),
        "dora_back": (120, 25, 30, 255),
        "tile_back": (18, 32, 55, 255),
    },
    "emerald": {
        "title": "翡翠雀神",
        "bg": (8, 22, 19, 255),
        "header_bg": (5, 15, 13, 255),
        "panel_bg": (14, 34, 30, 255),
        "panel_border": (30, 72, 64, 255),
        "table_mat": (4, 46, 38, 255),
        "table_frame": (18, 88, 76, 255),
        "center_box": (10, 26, 22, 255),
        "text_white": (245, 252, 250, 255),
        "text_accent": (0, 235, 155, 255),
        "text_gold": (245, 195, 68, 255),
        "text_muted": (145, 180, 172, 255),
        "rec_emerald": (0, 235, 155, 255),
        "rec_row_bg": (12, 65, 52, 255),
        "row_alt": (19, 44, 38, 255),
        "badge_bg": (16, 95, 75, 255),
        "dora_back": (130, 25, 25, 255),
        "tile_back": (16, 36, 32, 255),
    },
    "titanium": {
        "title": "钛金终端",
        "bg": (18, 18, 20, 255),
        "header_bg": (12, 12, 14, 255),
        "panel_bg": (26, 26, 30, 255),
        "panel_border": (52, 52, 58, 255),
        "table_mat": (22, 22, 26, 255),
        "table_frame": (70, 70, 80, 255),
        "center_box": (16, 16, 18, 255),
        "text_white": (245, 245, 248, 255),
        "text_accent": (245, 185, 45, 255),
        "text_gold": (245, 185, 45, 255),
        "text_muted": (155, 155, 165, 255),
        "rec_emerald": (245, 185, 45, 255),
        "rec_row_bg": (48, 42, 26, 255),
        "row_alt": (32, 32, 36, 255),
        "badge_bg": (95, 75, 25, 255),
        "dora_back": (110, 30, 30, 255),
        "tile_back": (30, 30, 34, 255),
    },
}

def _build_3d_acrylic_tile(asset_dir: Path, tile: str, target_w: int, target_h: int, tile_back_color: tuple) -> Image.Image:
    cache_key = (tile.strip().lower(), str(tile_back_color), target_w, target_h)
    if cache_key in _TILE_CACHE:
        return _TILE_CACHE[cache_key]

    t_clean = tile.strip().lower()
    tile_im = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile_im)

    bevel = max(2, int(target_h * 0.05))
    face_w = target_w - bevel
    face_h = target_h - bevel

    # 3D 牌背与倒角
    d.rounded_rectangle([0, 0, target_w - 1, target_h - 1], radius=max(3, int(target_w * 0.1)), fill=tile_back_color)

    # 象牙白正面
    d.rounded_rectangle([1, 1, face_w, face_h], radius=max(2, int(target_w * 0.08)), fill=(255, 253, 246, 255), outline=(185, 175, 155, 255), width=1)
    d.line([(3, 2), (face_w - 3, 2)], fill=(255, 255, 255, 180), width=1)

    if t_clean not in ("5z", "p", "haku"):
        fname = WEBP_TILE_MAP.get(t_clean, f"{t_clean}.webp")
        p = asset_dir / fname
        if p.exists() and p.suffix != ".svg":
            glyph = Image.open(p).convert("RGBA")
            glyph_w = int(face_w * 0.92)
            glyph_h = int(face_h * 0.92)
            glyph = glyph.resize((glyph_w, glyph_h), Image.Resampling.LANCZOS)
            offset_x = (face_w - glyph_w) // 2 + 1
            offset_y = (face_h - glyph_h) // 2 + 1
            tile_im.paste(glyph, (offset_x, offset_y), glyph)

    _TILE_CACHE[cache_key] = tile_im
    return tile_im


def _get_rendered_tile(tile_name: str, target_w: int, target_h: int, tile_back_color: tuple, asset_dir: str | Path = "D:/tenhoulib/MortalSim/apps/web/dist/tiles", is_tsumogiri: bool = False, rotate_angle: int = 0) -> Image.Image:
    asset_path = Path(asset_dir)
    tile_im = _build_3d_acrylic_tile(asset_path, tile_name, target_w, target_h, tile_back_color).copy()
    if is_tsumogiri:
        overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 85))
        tile_im = Image.alpha_composite(tile_im, overlay)
    if rotate_angle != 0:
        tile_im = tile_im.rotate(rotate_angle, expand=True, resample=Image.Resampling.BICUBIC)
    return tile_im


def _fmt_signed(v: float | None, prec: int = 0) -> str:
    if v is None: return "—"
    sign = "+" if v > 0 else ("-" if v < 0 else "")
    return f"{sign}{abs(v):.{prec}f}"

def _fmt_rate(v: float | None) -> str:
    if v is None: return "—"
    return f"{v * 100:.1f}%"

def _fmt_ci95(ci: list[float] | None, prec: int = 0) -> str:
    if not ci or len(ci) != 2: return "—"
    return f"[{_fmt_signed(ci[0], prec)}, {_fmt_signed(ci[1], prec)}]"

def _seat_zh(seat: int) -> str:
    return ["东", "南", "西", "北"][seat % 4]

def _label_zh(c: dict[str, Any]) -> str:
    if c.get("first_kyushu") or c.get("candidate") == "kyushu:kk":
        return "九种九牌"
    if c.get("first_tsumo") or c.get("candidate") == "tsumo":
        return "自摸和"
    if c.get("first_ron") or c.get("candidate") == "ron":
        return "荣和"
    if c.get("first_pass") or c.get("candidate") == "pass":
        return "见逃 (过)"
    cand_name = str(c.get("candidate") or c.get("discard") or "?")
    if cand_name.startswith("chi:"):
        return f"吃 {cand_name[4:]}"
    if cand_name.startswith("pon"):
        return f"碰 {cand_name[3:]}" if len(cand_name) > 3 else "碰"
    if cand_name == "daiminkan":
        return "大明杠"
    base = c.get("discard") or cand_name
    if c.get("first_kan"):
        return base + "杠"
    return "立直 " + base if c.get("first_riichi") else base


def render_png(
    result_data: dict[str, Any],
    asset_dir: str | Path,
    font_path: str | Path,
    output_path: str | Path,
    recommended_tile: str | None = None,
    theme: str = "obsidian", # 'obsidian' | 'emerald' | 'titanium'
) -> Path:
    font_path = Path(font_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    t_cfg = THEME_CONFIGS.get(theme, THEME_CONFIGS["obsidian"])

    # Fonts
    f_brand = ImageFont.truetype(str(font_path), 18)
    f_header_lg = ImageFont.truetype(str(font_path), 16)
    f_sub = ImageFont.truetype(str(font_path), 12)
    f_card_title = ImageFont.truetype(str(font_path), 13)
    f_tbl_head = ImageFont.truetype(str(font_path), 11)
    f_tbl_cell = ImageFont.truetype(str(font_path), 12)
    f_tbl_bold = ImageFont.truetype(str(font_path), 12)
    f_center_kyoku = ImageFont.truetype(str(font_path), 20)
    f_center_score = ImageFont.truetype(str(font_path), 13)
    f_center_info = ImageFont.truetype(str(font_path), 11)
    f_ci95 = ImageFont.truetype(str(font_path), 10)
    f_foot = ImageFont.truetype(str(font_path), 10)

    config = result_data.get("config", {})
    round_str = str(config.get("round", "E1")).upper()
    round_zh = KYOKU_FULL_NAME_ZH.get(round_str, round_str)
    honba = config.get("honba", 0)
    kyotaku = config.get("kyotaku", 0)
    runs = config.get("runs", 0)
    cands = result_data.get("candidates", [])
    hand_str = config.get("hand", "")
    dora_indicator = config.get("dora", "")
    target_seat = int(config.get("target_seat", 0) if config.get("target_seat") is not None else 0)
    x_turn = int(config.get("x", 1))

    scores_obj = config.get("scores", {})
    if isinstance(scores_obj, dict):
        rel_self = scores_obj.get("self", 25000)
        rel_shimo = scores_obj.get("shimocha", 25000)
        rel_toimen = scores_obj.get("toimen", 25000)
        rel_kami = 100000 - kyotaku * 1000 - rel_self - rel_shimo - rel_toimen
        rel_scores = [rel_self, rel_shimo, rel_toimen, rel_kami]
    else:
        rel_scores = [25000, 25000, 25000, 25000]

    W, H = 1120, 750
    img = Image.new("RGBA", (W, H), color=t_cfg["bg"])
    draw = ImageDraw.Draw(img)

    # 1. Header Bar
    draw.rectangle([0, 0, W, 72], fill=t_cfg["header_bg"])
    draw.rectangle([0, 71, W, 72], fill=t_cfg["panel_border"])

    # App Brand Badge
    draw.rounded_rectangle([24, 16, 128, 44], radius=4, fill=t_cfg["badge_bg"])
    b_txt = "MortalSim"
    b_bb = draw.textbbox((0, 0), b_txt, font=f_brand)
    draw.text((24 + (104 - (b_bb[2] - b_bb[0])) // 2, 19), b_txt, fill=(255, 255, 255, 255), font=f_brand)

    draw.text((140, 16), "日麻决策推演分析报告", fill=t_cfg["text_white"], font=f_header_lg)
    draw.text((140, 42), f"{round_zh} {honba}本场 | 巡目: 第 {x_turn} 巡 | 视角: {_seat_zh(target_seat)}家", fill=t_cfg["text_muted"], font=f_sub)

    meta_right = f"蒙特卡洛物理仿真 · {runs} 局/候选"
    m_bb = draw.textbbox((0, 0), meta_right, font=f_sub)
    draw.text((W - 24 - (m_bb[2] - m_bb[0]), 18), meta_right, fill=t_cfg["text_gold"], font=f_sub)
    kyotaku_str = f"场存供托: {kyotaku * 1000} 点"
    k_bb = draw.textbbox((0, 0), kyotaku_str, font=f_sub)
    draw.text((W - 24 - (k_bb[2] - k_bb[0]), 42), kyotaku_str, fill=t_cfg["text_muted"], font=f_sub)

    # 2. Left Side: Full-Scale Table & Rivers (四家牌桌态势与立体牌河)
    left_x, left_y, left_w, left_h = 24, 86, 380, 520
    draw.rounded_rectangle([left_x, left_y, left_x + left_w, left_y + left_h], radius=6, fill=t_cfg["panel_bg"], outline=t_cfg["panel_border"], width=1)
    draw.text((left_x + 14, left_y + 10), "◆ 牌桌实时态势 · 牌河", fill=t_cfg["text_gold"], font=f_card_title)

    mat_x, mat_y, mat_w, mat_h = left_x + 12, left_y + 32, 356, 476
    draw.rounded_rectangle([mat_x, mat_y, mat_x + mat_w, mat_y + mat_h], radius=4, fill=t_cfg["table_mat"], outline=t_cfg["table_frame"], width=2)

    cw, ch = 186, 156
    cx = mat_x + (mat_w - cw) // 2
    cy = mat_y + (mat_h - ch) // 2
    draw.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=4, fill=t_cfg["center_box"], outline=t_cfg["table_frame"], width=1)

    p2_seat_k = _seat_zh((target_seat + 2) % 4)
    p2_score_str = f"{p2_seat_k} {rel_scores[2]}"
    p2_bb = draw.textbbox((0, 0), p2_score_str, font=f_center_score)
    draw.text((cx + (cw - (p2_bb[2] - p2_bb[0])) // 2, cy + 6), p2_score_str, fill=t_cfg["text_muted"], font=f_center_score)

    box_w, box_h = 148, 86
    bx = cx + (cw - box_w) // 2
    by = cy + 26
    draw.rounded_rectangle([bx, by, bx + box_w, by + box_h], radius=3, fill=(10, 14, 20, 255), outline=t_cfg["panel_border"], width=1)

    draw.text((bx + 10, by + 4), round_zh, fill=t_cfg["text_white"], font=f_center_kyoku)
    tiles_left = max(0, 70 - (x_turn - 1) * 4)
    draw.text((bx + box_w - 50, by + 9), f"余{tiles_left}", fill=t_cfg["text_gold"], font=f_center_info)

    dora_w, dora_h = 18, 25
    d_start_x = bx + (box_w - dora_w * 5 - 4 * 2) // 2
    d_start_y = by + 37
    if dora_indicator:
        t_dora = _get_rendered_tile(dora_indicator, dora_w, dora_h, t_cfg["tile_back"], asset_dir=asset_dir)
        img.paste(t_dora, (d_start_x, d_start_y), t_dora)
    for i in range(1, 5):
        kx = d_start_x + i * (dora_w + 2)
        draw.rectangle([kx, d_start_y, kx + dora_w, d_start_y + dora_h], fill=t_cfg["dora_back"], outline=(50, 15, 15, 255), width=1)
    draw.text((bx + (box_w - 60) // 2, by + 66), "宝牌指示牌", fill=t_cfg["text_muted"], font=f_foot)

    p0_seat_k = _seat_zh(target_seat)
    p0_score_str = f"{p0_seat_k} {rel_scores[0]}"
    p0_bb = draw.textbbox((0, 0), p0_score_str, font=f_center_score)
    draw.text((cx + (cw - (p0_bb[2] - p0_bb[0])) // 2, cy + ch - 18), p0_score_str, fill=t_cfg["rec_emerald"], font=f_center_score)

    def _rotate_text(text: str, angle: int, color: tuple) -> Image.Image:
        tb = draw.textbbox((0, 0), text, font=f_center_score)
        im = Image.new("RGBA", (tb[2] - tb[0] + 4, tb[3] - tb[1] + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.text((0, 0), text, fill=color, font=f_center_score)
        return im.rotate(angle, expand=True)

    p1_seat_k = _seat_zh((target_seat + 1) % 4)
    rot_p1 = _rotate_text(f"{p1_seat_k} {rel_scores[1]}", 90, t_cfg["text_muted"])
    img.paste(rot_p1, (cx + cw - 16, cy + (ch - rot_p1.height) // 2), rot_p1)

    p3_seat_k = _seat_zh((target_seat + 3) % 4)
    rot_p3 = _rotate_text(f"{p3_seat_k} {rel_scores[3]}", 270, t_cfg["text_muted"])
    img.paste(rot_p3, (cx + 3, cy + (ch - rot_p3.height) // 2), rot_p3)

    # Rivers
    def _parse_river_entries(river_raw) -> list[tuple[str, bool, bool]]:
        out = []
        if not river_raw: return out
        for item in river_raw:
            if isinstance(item, (list, tuple)):
                tile_s, ts, is_r = str(item[0]), bool(item[1]) if len(item) > 1 else False, bool(item[2]) if len(item) > 2 else False
            else:
                tile_s = str(item.get("tile", "1m"))
                ts = bool(item.get("tsumogiri", False))
                is_r = bool(item.get("is_riichi", False)) or bool(item.get("riichi", False))
            out.append((tile_s, ts, is_r))
        return out

    all_rivers = [[], [], [], []]
    all_rivers[target_seat] = _parse_river_entries(config.get("target_past_discards"))
    opp_rivers_cfg = config.get("opponent_rivers") or []
    for p, r in enumerate(opp_rivers_cfg):
        if p != target_seat:
            all_rivers[p] = _parse_river_entries(r)

    rel_rivers = [
        all_rivers[target_seat],
        all_rivers[(target_seat + 1) % 4],
        all_rivers[(target_seat + 2) % 4],
        all_rivers[(target_seat + 3) % 4],
    ]

    rw_w, rw_h = 15, 21
    self_start_x = cx + 16
    self_start_y = cy + ch + 10
    for i, item in enumerate(rel_rivers[0]):
        t_val, is_tsumo, is_r = item
        row, col = i // 6, i % 6
        angle = 90 if is_r else 0
        t_img = _get_rendered_tile(t_val, rw_w, rw_h, t_cfg["tile_back"], asset_dir=asset_dir, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (self_start_x + col * (rw_w + 3), self_start_y + row * (rw_h + 3)), t_img)

    toimen_start_x = cx + cw - 16 - rw_w
    toimen_start_y = cy - 10 - rw_h
    for i, item in enumerate(rel_rivers[2]):
        t_val, is_tsumo, is_r = item
        row, col = i // 6, i % 6
        angle = 270 if is_r else 180
        t_img = _get_rendered_tile(t_val, rw_w, rw_h, t_cfg["tile_back"], asset_dir=asset_dir, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (toimen_start_x - col * (rw_w + 3), toimen_start_y - row * (rw_h + 3)), t_img)

    shimo_start_x = cx + cw + 10
    shimo_start_y = cy + ch - 16 - rw_h
    for i, item in enumerate(rel_rivers[1]):
        t_val, is_tsumo, is_r = item
        row, col = i // 6, i % 6
        angle = 180 if is_r else 90
        t_img = _get_rendered_tile(t_val, rw_w, rw_h, t_cfg["tile_back"], asset_dir=asset_dir, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (shimo_start_x + row * (rw_w + 3), shimo_start_y - col * (rw_w + 3)), t_img)

    kami_start_x = cx - 10 - rw_h
    kami_start_y = cy + 16
    for i, item in enumerate(rel_rivers[3]):
        t_val, is_tsumo, is_r = item
        row, col = i // 6, i % 6
        angle = 0 if is_r else 270
        t_img = _get_rendered_tile(t_val, rw_w, rw_h, t_cfg["tile_back"], asset_dir=asset_dir, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (kami_start_x - row * (rw_w + 3), kami_start_y + col * (rw_w + 3)), t_img)

    # 3. Right Side: Unified Analytical Decision Suite with CI95 Precision
    right_x, right_y, right_w, right_h = 418, 86, W - 418 - 24, 520
    draw.rounded_rectangle([right_x, right_y, right_x + right_w, right_y + right_h], radius=6, fill=t_cfg["panel_bg"], outline=t_cfg["panel_border"], width=1)

    p_inner_x = right_x + 14
    p_inner_w = right_w - 28
    cur_y = right_y + 12

    # Section 1: Physical Outcomes & Expectation Bars + CI95
    draw.text((p_inner_x, cur_y), "◆ 局收支与期望值对比 (含 95% 置信区间)", fill=t_cfg["text_gold"], font=f_card_title)
    cur_y += 22

    h1 = ["候选动作", "局收支 / 95% CI", "和牌率", "平均打点", "自摸率", "放铳率", "立直率", "副露率"]
    w1 = [95, 175, 55, 68, 52, 52, 52, 52]

    draw.rectangle([p_inner_x, cur_y, p_inner_x + p_inner_w, cur_y + 24], fill=(10, 14, 20, 255))
    draw.line([(p_inner_x, cur_y + 24), (p_inner_x + p_inner_w, cur_y + 24)], fill=t_cfg["panel_border"], width=1)
    tx = p_inner_x + 6
    for title, col_w in zip(h1, w1):
        draw.text((tx, cur_y + 5), title, fill=t_cfg["text_muted"], font=f_tbl_head)
        tx += col_w
    cur_y += 24

    max_pt = max([abs((c.get("value") or {}).get("point", {}).get("value") or 1) for c in cands] + [10000])

    for idx, c in enumerate(cands):
        c_lbl = _label_zh(c)
        is_rec = (c.get("candidate") == recommended_tile or c_lbl == recommended_tile)
        row_bg = t_cfg["rec_row_bg"] if is_rec else (t_cfg["row_alt"] if idx % 2 == 1 else t_cfg["panel_bg"])
        draw.rectangle([p_inner_x, cur_y, p_inner_x + p_inner_w, cur_y + 32], fill=row_bg)

        pt_obj = (c.get("value") or {}).get("point", {}) if isinstance(c.get("value"), dict) else {}
        pt_val = pt_obj.get("value")
        pt_ci = pt_obj.get("ci95")
        agari_r = c.get("agari_rate") or ((c.get("win") or {}).get("rate", {}).get("rate") if isinstance(c.get("win"), dict) else None)
        avg_pt = (c.get("win") or {}).get("average_point") if isinstance(c.get("win"), dict) else c.get("avg_point")
        tsumo_r = (c.get("outcome") or {}).get("self_tsumo", {}).get("rate") if isinstance(c.get("outcome"), dict) else None
        houjuu_r = c.get("houjuu_rate") or ((c.get("defense") or {}).get("deal_in_rate", {}).get("rate") if isinstance(c.get("defense"), dict) else None)
        riichi_r = c.get("riichi_rate") or ((c.get("riichi") or {}).get("rate", {}).get("rate") if isinstance(c.get("riichi"), dict) else None)
        fuuro_r = c.get("fuuro_rate") or ((c.get("call") or {}).get("rate", {}).get("rate") if isinstance(c.get("call"), dict) else None)

        tx = p_inner_x + 6
        # Col 0: Candidate Name
        draw.text((tx, cur_y + 8), c_lbl + (" ★" if is_rec else ""), fill=t_cfg["rec_emerald"] if is_rec else t_cfg["text_white"], font=f_tbl_bold if is_rec else f_tbl_cell)
        tx += w1[0]

        # Col 1: Point Value + CI95 subtitle + Mini Bar
        draw.text((tx, cur_y + 2), _fmt_signed(pt_val, 0), fill=t_cfg["rec_emerald"] if is_rec else t_cfg["text_white"], font=f_tbl_bold if is_rec else f_tbl_cell)
        ci_str = f"CI {_fmt_ci95(pt_ci, 0)}"
        draw.text((tx, cur_y + 17), ci_str, fill=t_cfg["text_muted"], font=f_ci95)

        # Bar on right of Col 1
        bar_w = 48
        bar_h = 7
        bar_x = tx + 120
        bar_y = cur_y + 12
        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=2, fill=(20, 30, 30, 255))
        if pt_val is not None and pt_val > 0:
            fill_len = max(3, int(min(1.0, pt_val / max_pt) * bar_w))
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_len, bar_y + bar_h], radius=2, fill=t_cfg["rec_emerald"] if is_rec else t_cfg["text_gold"])
        elif pt_val is not None and pt_val < 0:
            fill_len = max(3, int(min(1.0, abs(pt_val) / max_pt) * bar_w))
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_len, bar_y + bar_h], radius=2, fill=(230, 70, 70, 255))
        tx += w1[1]

        # Other physical stats
        other_vals = [
            _fmt_rate(agari_r),
            f"{avg_pt:.0f}" if isinstance(avg_pt, (int, float)) else "—",
            _fmt_rate(tsumo_r),
            _fmt_rate(houjuu_r),
            _fmt_rate(riichi_r),
            _fmt_rate(fuuro_r),
        ]
        for v_txt, col_w in zip(other_vals, w1[2:]):
            draw.text((tx, cur_y + 8), v_txt, fill=t_cfg["rec_emerald"] if is_rec else t_cfg["text_white"], font=f_tbl_cell)
            tx += col_w

        draw.line([(p_inner_x, cur_y + 32), (p_inner_x + p_inner_w, cur_y + 32)], fill=(30, 40, 50, 255), width=1)
        cur_y += 32

    # Section 2: Rank Probabilities with Stacked Bar Charts + PT EV with CI95
    cur_y += 12
    draw.text((p_inner_x, cur_y), "◆ 段位期待值 (含 95% CI) 与顺位分布堆叠图", fill=t_cfg["text_gold"], font=f_card_title)
    cur_y += 22

    h2 = ["候选动作", "预期顺位", "凤七 pt EV / 95% CI", "1位~4位 顺位分布堆叠图 (1位/2位/3位/4位)"]
    w2 = [95, 75, 175, 290]

    draw.rectangle([p_inner_x, cur_y, p_inner_x + p_inner_w, cur_y + 24], fill=(10, 14, 20, 255))
    draw.line([(p_inner_x, cur_y + 24), (p_inner_x + p_inner_w, cur_y + 24)], fill=t_cfg["panel_border"], width=1)
    tx = p_inner_x + 6
    for title, col_w in zip(h2, w2):
        draw.text((tx, cur_y + 5), title, fill=t_cfg["text_muted"], font=f_tbl_head)
        tx += col_w
    cur_y += 24

    C_R1 = (46, 204, 113, 255)
    C_R2 = (52, 152, 219, 255)
    C_R3 = (241, 196, 15, 255)
    C_R4 = (231, 76, 60, 255)

    for idx, c in enumerate(cands):
        c_lbl = _label_zh(c)
        is_rec = (c.get("candidate") == recommended_tile or c_lbl == recommended_tile)
        row_bg = t_cfg["rec_row_bg"] if is_rec else (t_cfg["row_alt"] if idx % 2 == 1 else t_cfg["panel_bg"])
        draw.rectangle([p_inner_x, cur_y, p_inner_x + p_inner_w, cur_y + 32], fill=row_bg)

        han = c.get("hanchan") or {}
        rr = han.get("rank_rates", [])
        er = han.get("expected_rank", {}).get("value")
        pt7_obj = (han.get("dan_pt_ev") or {}).get("houou_7", {})
        pt7 = pt7_obj.get("value")
        pt7_ci = pt7_obj.get("ci95")
        r1 = rr[0].get("rate") or 0.0 if len(rr) > 0 else 0.0
        r2 = rr[1].get("rate") or 0.0 if len(rr) > 1 else 0.0
        r3 = rr[2].get("rate") or 0.0 if len(rr) > 2 else 0.0
        r4 = rr[3].get("rate") or 0.0 if len(rr) > 3 else 0.0

        tx = p_inner_x + 6
        draw.text((tx, cur_y + 8), c_lbl + (" ★" if is_rec else ""), fill=t_cfg["rec_emerald"] if is_rec else t_cfg["text_white"], font=f_tbl_bold if is_rec else f_tbl_cell)
        tx += w2[0]

        draw.text((tx, cur_y + 8), f"{er:.3f} 位" if er is not None else "—", fill=t_cfg["rec_emerald"] if is_rec else t_cfg["text_white"], font=f_tbl_cell)
        tx += w2[1]

        # PT EV with CI
        draw.text((tx, cur_y + 2), _fmt_signed(pt7, 1) + " pt", fill=t_cfg["text_gold"] if pt7 and pt7 > 0 else (t_cfg["rec_emerald"] if is_rec else t_cfg["text_white"]), font=f_tbl_bold if is_rec else f_tbl_cell)
        pt7_ci_str = f"CI {_fmt_ci95(pt7_ci, 1)}"
        draw.text((tx, cur_y + 17), pt7_ci_str, fill=t_cfg["text_muted"], font=f_ci95)
        tx += w2[2]

        # Stacked bar
        sbar_w = 175
        sbar_h = 12
        sbar_x = tx
        sbar_y = cur_y + 10

        total_r = r1 + r2 + r3 + r4
        if total_r > 0:
            w_r1 = int((r1 / total_r) * sbar_w)
            w_r2 = int((r2 / total_r) * sbar_w)
            w_r3 = int((r3 / total_r) * sbar_w)
            w_r4 = sbar_w - w_r1 - w_r2 - w_r3

            curr_bx = sbar_x
            if w_r1 > 0: draw.rectangle([curr_bx, sbar_y, curr_bx + w_r1, sbar_y + sbar_h], fill=C_R1); curr_bx += w_r1
            if w_r2 > 0: draw.rectangle([curr_bx, sbar_y, curr_bx + w_r2, sbar_y + sbar_h], fill=C_R2); curr_bx += w_r2
            if w_r3 > 0: draw.rectangle([curr_bx, sbar_y, curr_bx + w_r3, sbar_y + sbar_h], fill=C_R3); curr_bx += w_r3
            if w_r4 > 0: draw.rectangle([curr_bx, sbar_y, curr_bx + w_r4, sbar_y + sbar_h], fill=C_R4)

        r1_val = (r1 * 100) if isinstance(r1, (int, float)) else 0.0
        r4_val = (r4 * 100) if isinstance(r4, (int, float)) else 0.0
        pct_text = f"1位{r1_val:.0f}% / 4位{r4_val:.0f}%"
        draw.text((sbar_x + sbar_w + 10, cur_y + 9), pct_text, fill=t_cfg["text_muted"], font=f_foot)

        draw.line([(p_inner_x, cur_y + 32), (p_inner_x + p_inner_w, cur_y + 32)], fill=(30, 40, 50, 255), width=1)
        cur_y += 32

    # Section 3: Distinct Yaku Breakdown
    cur_y += 12
    draw.text((p_inner_x, cur_y), "◆ 主要和牌役种构成 (Yaku Breakdown)", fill=t_cfg["text_gold"], font=f_card_title)
    cur_y += 20

    candidate_yaku_maps: list[tuple[str, dict[str, float]]] = []
    all_yaku_names: set[str] = set()
    for c in cands:
        c_lbl = _label_zh(c)
        y_list = c.get("yaku", [])
        c_map = {}
        if isinstance(y_list, list):
            for y_item in y_list:
                y_id = y_item.get("id")
                y_rate = y_item.get("rate", 0.0)
                if y_id and isinstance(y_rate, (int, float)) and y_rate > 0.01:
                    c_map[y_id] = y_rate
                    all_yaku_names.add(y_id)
        candidate_yaku_maps.append((c_lbl, c_map))

    distinctive_yaku = []
    for y_id in all_yaku_names:
        rates = [c_map.get(y_id, 0.0) for _, c_map in candidate_yaku_maps]
        max_r, min_r = max(rates), min(rates)
        if (max_r - min_r >= 0.04) or (len(all_yaku_names) <= 6 and max_r >= 0.04):
            distinctive_yaku.append((y_id, max_r, rates))

    distinctive_yaku.sort(key=lambda x: -x[1])

    if distinctive_yaku:
        hy = ["役种名称"] + [lbl for lbl, _ in candidate_yaku_maps]
        wy = [100] + [75] * len(candidate_yaku_maps)
        draw.rectangle([p_inner_x, cur_y, p_inner_x + p_inner_w, cur_y + 22], fill=(10, 14, 20, 255))
        tx = p_inner_x + 6
        for title, col_w in zip(hy, wy):
            draw.text((tx, cur_y + 4), title, fill=t_cfg["text_muted"], font=f_tbl_head)
            tx += col_w
        cur_y += 22

        for y_id, _, rates in distinctive_yaku[:3]:
            y_zh = YAKU_NAME_ZH.get(y_id, y_id)
            row_txts = [y_zh] + [_fmt_rate(r) for r in rates]
            tx = p_inner_x + 6
            for val_txt, col_w in zip(row_txts, wy):
                draw.text((tx, cur_y + 3), val_txt, fill=t_cfg["text_muted"], font=f_tbl_cell)
                tx += col_w
            cur_y += 18
    else:
        draw.text((p_inner_x + 6, cur_y + 4), "• 各候选和牌役种构成相近，无显著差异。", fill=t_cfg["text_muted"], font=f_tbl_cell)

    # 4. Bottom Hand Bar with 3D Elevated Recommended Tile
    hand_bar_y = 625
    hand_bar_h = 95
    draw.rounded_rectangle([24, hand_bar_y, W - 24, hand_bar_y + hand_bar_h], radius=6, fill=t_cfg["panel_bg"], outline=t_cfg["panel_border"], width=1)

    draw.text((38, hand_bar_y + 28), f"◆ 自家手牌\n  ({_seat_zh(target_seat)}家)", fill=t_cfg["text_gold"], font=f_card_title)

    hand_tiles = [hand_str[i:i+2] for i in range(0, len(hand_str), 2)]
    tile_w, tile_h = 36, 50
    hand_start_px = 145

    rec_pure_tile = recommended_tile.replace("riichi:", "").replace("立直 ", "").replace("k", "").strip() if recommended_tile else None

    elevated_drawn = False
    for idx, t_str in enumerate(hand_tiles):
        is_rec_hand_tile = (not elevated_drawn and rec_pure_tile and t_str.lower() == rec_pure_tile.lower())
        elevate_offset = 8 if is_rec_hand_tile else 0
        if is_rec_hand_tile:
            elevated_drawn = True

        t_im = _get_rendered_tile(t_str, tile_w, tile_h, t_cfg["tile_back"], asset_dir=asset_dir)
        px = hand_start_px + idx * (tile_w + 4)
        if idx == len(hand_tiles) - 1 and len(hand_tiles) == 14:
            px += 10

        py = hand_bar_y + 26 - elevate_offset

        if is_rec_hand_tile:
            draw.rounded_rectangle([px - 2, py - 2, px + tile_w + 2, py + tile_h + 2], radius=4, fill=(0, 0, 0, 100), outline=t_cfg["rec_emerald"], width=2)
            draw.text((px + 2, py - 14), "★ 最优", fill=t_cfg["rec_emerald"], font=f_foot)

        img.paste(t_im, (px, py), t_im)

    # Footer
    foot_str = "MortalSim 日麻对局决策推演 · 基于早巡物理对局引擎与半庄段位顺位模型 (95% Confidence Interval)"
    draw.text((28, H - 16), foot_str, fill=t_cfg["text_muted"], font=f_foot)

    img.save(str(output_path), "PNG")
    return output_path

"""Tenhou 4K 牌桌风格 PNG 渲染器：支持自适应巡目、四家牌河视角正序、立直宣言牌90度横置。"""
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

_TILE_CACHE: dict[str, Image.Image] = {}


WEBP_TILE_MAP = {
    "1m": "Man1.webp", "2m": "Man2.webp", "3m": "Man3.webp", "4m": "Man4.webp", "5m": "Man5.webp", "0m": "Man5-Dora.webp", "6m": "Man6.webp", "7m": "Man7.webp", "8m": "Man8.webp", "9m": "Man9.webp",
    "1p": "Pin1.webp", "2p": "Pin2.webp", "3p": "Pin3.webp", "4p": "Pin4.webp", "5p": "Pin5.webp", "0p": "Pin5-Dora.webp", "6p": "Pin6.webp", "7p": "Pin7.webp", "8p": "Pin8.webp", "9p": "Pin9.webp",
    "1s": "Sou1.webp", "2s": "Sou2.webp", "3s": "Sou3.webp", "4s": "Sou4.webp", "5s": "Sou5.webp", "0s": "Sou5-Dora.webp", "6s": "Sou6.webp", "7s": "Sou7.webp", "8s": "Sou8.webp", "9s": "Sou9.webp",
    "1z": "Ton.webp", "2z": "Nan.webp", "3z": "Shaa.webp", "4z": "Pei.webp", "5z": "Haku.svg", "6z": "Hatsu.webp", "7z": "Chun.webp",
    "e": "Ton.webp", "s": "Nan.webp", "w": "Shaa.webp", "n": "Pei.webp", "p": "Haku.svg", "f": "Hatsu.webp", "c": "Chun.webp",
}

def _load_tile_image(asset_dir: Path, tile: str) -> Image.Image:
    t_clean = tile.strip().lower()
    if t_clean in _TILE_CACHE:
        return _TILE_CACHE[t_clean]

    # Standard Tenhou/Riichi Mahjong Tile Dimensions (150x200) with rounded ivory background & border
    tile_w, tile_h = 150, 200
    # Ivory front face with slight 3D gradient/border
    tile_base = Image.new("RGBA", (tile_w, tile_h), color=(248, 246, 238, 255))
    d_base = ImageDraw.Draw(tile_base)
    # Beveled card edge outline
    d_base.rounded_rectangle([2, 2, tile_w - 3, tile_h - 3], radius=10, fill=(250, 248, 242, 255), outline=(185, 180, 165, 255), width=3)
    d_base.rounded_rectangle([6, 6, tile_w - 7, tile_h - 7], radius=6, outline=(225, 220, 205, 255), width=1)

    if t_clean in ("5z", "p", "haku"):
        # 白板: 纯白/象牙色净面
        _TILE_CACHE[t_clean] = tile_base
        return tile_base

    fname = WEBP_TILE_MAP.get(t_clean, f"{t_clean}.webp")
    p = asset_dir / fname
    if p.exists() and p.suffix != ".svg":
        glyph = Image.open(p).convert("RGBA")
        if glyph.size != (tile_w, tile_h):
            glyph = glyph.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        # Composite the sharp vector glyph onto the ivory tile base
        composite_tile = Image.alpha_composite(tile_base, glyph)
        _TILE_CACHE[t_clean] = composite_tile
        return composite_tile

    # Fallback
    d_base.text((40, 70), tile, fill=(30, 30, 30, 255))
    _TILE_CACHE[t_clean] = tile_base
    return tile_base


def _get_rendered_tile_image(tile_name: str, target_w: int, target_h: int, is_tsumogiri: bool = False, rotate_angle: int = 0) -> Image.Image:
    asset_dir = Path("D:/tenhoulib/MortalSim/apps/web/dist/tiles")
    base_tile = _load_tile_image(asset_dir, tile_name)
    resized = base_tile.resize((target_w, target_h), Image.Resampling.LANCZOS)
    if is_tsumogiri:
        overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 85))
        resized = Image.alpha_composite(resized, overlay)
    if rotate_angle != 0:
        resized = resized.rotate(rotate_angle, expand=True, resample=Image.Resampling.BICUBIC)
    return resized


def _fmt_signed(v: float | None, prec: int = 1) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ("-" if v < 0 else "")
    return f"{sign}{abs(v):.{prec}f}"


def _fmt_rate(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


def _fmt_ci(ci: list[float] | None) -> str:
    if not ci or len(ci) != 2:
        return "—"
    return f"{_fmt_signed(ci[0], 1)} ~ {_fmt_signed(ci[1], 1)}"


def render_png(
    result_data: dict[str, Any],
    asset_dir: str | Path,
    font_path: str | Path,
    output_path: str | Path,
    recommended_tile: str | None = None,
) -> Path:
    asset_dir = Path(asset_dir)
    font_path = Path(font_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    f_title = ImageFont.truetype(str(font_path), 26)
    f_sub = ImageFont.truetype(str(font_path), 16)
    f_tbl_head = ImageFont.truetype(str(font_path), 15)
    f_tbl_cell = ImageFont.truetype(str(font_path), 15)
    f_center_lg = ImageFont.truetype(str(font_path), 22)
    f_center_sm = ImageFont.truetype(str(font_path), 13)
    f_foot = ImageFont.truetype(str(font_path), 12)

    config = result_data.get("config", {})
    round_str = str(config.get("round", "E1"))
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
        rel_kami = scores_obj.get("kamicha", 100000 - kyotaku * 1000 - rel_self - rel_shimo - rel_toimen)
        rel_scores = [rel_self, rel_shimo, rel_toimen, rel_kami]
    else:
        rel_scores = [25000, 25000, 25000, 25000]

    seat_names = ["东", "南", "西", "北"]
    my_seat_name = seat_names[target_seat]

    round_name_map = {"E1": "东1", "E2": "东2", "E3": "东3", "E4": "东4", "S1": "南1", "S2": "南2", "S3": "南3", "S4": "南4"}
    round_zh = round_name_map.get(round_str, round_str)

    W = 1260
    cands_count = max(len(cands), 1)
    H = 816

    C_BG = (1, 36, 33, 255)
    C_DESK_BG = (0, 48, 44, 255)
    C_DESK_BORDER = (20, 110, 100, 255)
    C_BOX_BORDER = (20, 95, 85, 255)
    C_TEXT_WHITE = (240, 245, 245, 255)
    C_TEXT_MUTED = (140, 185, 175, 255)
    C_REC = (0, 235, 175, 255)
    C_DORA_BG = (100, 20, 20, 255)
    C_TBL_BORDER = (15, 80, 75, 255)

    img = Image.new("RGBA", (W, H), color=C_BG)
    draw = ImageDraw.Draw(img)

    # 1. 顶部 Header
    top_band = Image.new("RGBA", (W, 6), (0, 220, 160, 255))
    img.paste(top_band, (0, 0))

    title_text = f"MortalSim 早巡模拟器 · 第 {x_turn} 打决策"
    draw.text((40, 28), title_text, fill=C_TEXT_WHITE, font=f_title)
    rec_disp = recommended_tile or "—"
    draw.text((40, 68), f"推荐舍牌: {rec_disp} ({my_seat_name}家视角)", fill=C_REC, font=f_sub)

    meta_str = f"{round_str}  {honba}本场  {kyotaku}供托  ·  {runs} 局/候选"
    bbox = draw.textbbox((0, 0), meta_str, font=f_sub)
    draw.text((W - 40 - (bbox[2] - bbox[0]), 32), meta_str, fill=C_TEXT_MUTED, font=f_sub)

    # 2. 中间紧凑型麻将桌 (Tenhou / Mortal Desk)
    table_w = 460
    table_h = 390
    table_x = (W - table_w) // 2
    table_y = 115

    draw.rectangle([table_x, table_y, table_x + table_w, table_y + table_h], fill=C_DESK_BG, outline=C_DESK_BORDER, width=2)

    cw = 200
    ch = 180
    cx = table_x + (table_w - cw) // 2
    cy = table_y + (table_h - ch) // 2
    draw.rectangle([cx, cy, cx + cw, cy + ch], fill=C_DESK_BG, outline=C_BOX_BORDER, width=1)

    # 中心小方框信息
    round_box_w = 140
    round_box_h = 56
    round_box_x = cx + (cw - round_box_w) // 2
    round_box_y = cy + 22
    draw.rectangle([round_box_x, round_box_y, round_box_x + round_box_w, round_box_y + round_box_h], outline=C_BOX_BORDER, width=1)

    r_bb = draw.textbbox((0, 0), round_zh, font=f_center_lg)
    draw.text((round_box_x + (round_box_w - (r_bb[2] - r_bb[0])) // 2, round_box_y + 4), round_zh, fill=C_TEXT_WHITE, font=f_center_lg)

    tiles_left = max(0, 70 - (x_turn - 1) * 4)
    tl_str = f"x{tiles_left}"
    tl_bb = draw.textbbox((0, 0), tl_str, font=f_center_sm)
    draw.text((round_box_x + (round_box_w - (tl_bb[2] - tl_bb[0])) // 2, round_box_y + 32), tl_str, fill=C_TEXT_MUTED, font=f_center_sm)

    # 宝牌指示牌
    dora_w, dora_h = 20, 27
    dora_start_x = cx + (cw - dora_w * 5 - 4 * 2) // 2
    dora_start_y = cy + 86

    if dora_indicator:
        t_dora = _get_rendered_tile_image(dora_indicator, dora_w, dora_h)
        img.paste(t_dora, (dora_start_x, dora_start_y), t_dora)

    for i in range(1, 5):
        bx = dora_start_x + i * (dora_w + 2)
        draw.rectangle([bx, dora_start_y, bx + dora_w, dora_start_y + dora_h], fill=C_DORA_BG, outline=(50, 10, 10, 255), width=1)

    # 四边玩家座次与点数
    p0_score = f"{seat_names[target_seat]} {rel_scores[0]}"
    p0_bb = draw.textbbox((0, 0), p0_score, font=f_center_sm)
    draw.text((cx + (cw - (p0_bb[2] - p0_bb[0])) // 2, cy + ch - 22), p0_score, fill=C_TEXT_MUTED, font=f_center_sm)

    p2_seat = seat_names[(target_seat + 2) % 4]
    p2_score = f"{p2_seat} {rel_scores[2]}"
    p2_bb = draw.textbbox((0, 0), p2_score, font=f_center_sm)
    draw.text((cx + (cw - (p2_bb[2] - p2_bb[0])) // 2, cy + 6), p2_score, fill=C_TEXT_MUTED, font=f_center_sm)

    p1_seat = seat_names[(target_seat + 1) % 4]
    p1_score = f"{p1_seat} {rel_scores[1]}"
    p1_bb = draw.textbbox((0, 0), p1_score, font=f_center_sm)
    txt_im1 = Image.new("RGBA", (p1_bb[2] - p1_bb[0] + 4, p1_bb[3] - p1_bb[1] + 4), (0, 0, 0, 0))
    txt_draw1 = ImageDraw.Draw(txt_im1)
    txt_draw1.text((0, 0), p1_score, fill=C_TEXT_MUTED, font=f_center_sm)
    rot_p1 = txt_im1.rotate(90, expand=True)
    img.paste(rot_p1, (cx + cw - 20, cy + (ch - rot_p1.height) // 2), rot_p1)

    p3_seat = seat_names[(target_seat + 3) % 4]
    p3_score = f"{p3_seat} {rel_scores[3]}"
    p3_bb = draw.textbbox((0, 0), p3_score, font=f_center_sm)
    txt_im3 = Image.new("RGBA", (p3_bb[2] - p3_bb[0] + 4, p3_bb[3] - p3_bb[1] + 4), (0, 0, 0, 0))
    txt_draw3 = ImageDraw.Draw(txt_im3)
    txt_draw3.text((0, 0), p3_score, fill=C_TEXT_MUTED, font=f_center_sm)
    rot_p3 = txt_im3.rotate(270, expand=True)
    img.paste(rot_p3, (cx + 6, cy + (ch - rot_p3.height) // 2), rot_p3)

    # 3. 四家真实牌河渲染
    all_rivers: list[list[tuple[str, bool, bool]]] = [[], [], [], []]
    past_target = config.get("target_past_discards") or []
    for item in past_target:
        if isinstance(item, (list, tuple)):
            tile_s = str(item[0])
            ts = bool(item[1]) if len(item) > 1 else False
            is_r = bool(item[2]) if len(item) > 2 else False
        else:
            tile_s = str(item.get("tile", "1m"))
            ts = bool(item.get("tsumogiri", False))
            is_r = bool(item.get("is_riichi", False)) or bool(item.get("riichi", False))
        all_rivers[target_seat].append((tile_s, ts, is_r))

    opp_rivers_cfg = config.get("opponent_rivers") or []
    for p, r in enumerate(opp_rivers_cfg):
        if p != target_seat and r:
            for item in r:
                if isinstance(item, (list, tuple)):
                    tile_s = str(item[0])
                    ts = bool(item[1]) if len(item) > 1 else False
                    is_r = bool(item[2]) if len(item) > 2 else False
                else:
                    tile_s = str(item.get("tile", "1m"))
                    ts = bool(item.get("tsumogiri", False))
                    is_r = bool(item.get("is_riichi", False)) or bool(item.get("riichi", False))
                all_rivers[p].append((tile_s, ts, is_r))

    rel_rivers = [
        all_rivers[target_seat],
        all_rivers[(target_seat + 1) % 4],
        all_rivers[(target_seat + 2) % 4],
        all_rivers[(target_seat + 3) % 4],
    ]

    rw_w, rw_h = 16, 22

    # (1) 自家牌河 (下, 0 deg)
    self_start_x = cx + 18
    self_start_y = cy + ch + 8
    for i, item in enumerate(rel_rivers[0]):
        t_val = item[0]
        is_tsumo = item[1] if len(item) > 1 else False
        is_r = item[2] if len(item) > 2 else False
        row, col = i // 6, i % 6
        angle = 90 if is_r else 0
        t_img = _get_rendered_tile_image(t_val, rw_w, rw_h, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (self_start_x + col * (rw_w + 3), self_start_y + row * (rw_h + 3)), t_img)

    # (2) 对面牌河 (上, 180 deg)
    toimen_start_x = cx + cw - 18 - rw_w
    toimen_start_y = cy - 8 - rw_h
    for i, item in enumerate(rel_rivers[2]):
        t_val = item[0]
        is_tsumo = item[1] if len(item) > 1 else False
        is_r = item[2] if len(item) > 2 else False
        row, col = i // 6, i % 6
        angle = 270 if is_r else 180
        t_img = _get_rendered_tile_image(t_val, rw_w, rw_h, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (toimen_start_x - col * (rw_w + 3), toimen_start_y - row * (rw_h + 3)), t_img)

    # (3) 下家牌河 (右, 90 deg)
    shimo_start_x = cx + cw + 8
    shimo_start_y = cy + ch - 18 - rw_h
    for i, item in enumerate(rel_rivers[1]):
        t_val = item[0]
        is_tsumo = item[1] if len(item) > 1 else False
        is_r = item[2] if len(item) > 2 else False
        row, col = i // 6, i % 6
        angle = 180 if is_r else 90
        t_img = _get_rendered_tile_image(t_val, rw_w, rw_h, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (shimo_start_x + row * (rw_h + 3), shimo_start_y - col * (rw_w + 3)), t_img)

    # (4) 上家牌河 (左, 270 deg)
    kami_start_x = cx - 8 - rw_h
    kami_start_y = cy + 18
    for i, item in enumerate(rel_rivers[3]):
        t_val = item[0]
        is_tsumo = item[1] if len(item) > 1 else False
        is_r = item[2] if len(item) > 2 else False
        row, col = i // 6, i % 6
        angle = 0 if is_r else 270
        t_img = _get_rendered_tile_image(t_val, rw_w, rw_h, is_tsumogiri=is_tsumo, rotate_angle=angle)
        img.paste(t_img, (kami_start_x - row * (rw_h + 3), kami_start_y + col * (rw_w + 3)), t_img)

    # 4. 自家当前手牌区
    hand_y = 525
    hand_tiles = [hand_str[i:i+2] for i in range(0, len(hand_str), 2)]
    tile_w, tile_h = 36, 50

    hand_title = f"{my_seat_name}家当前手牌"
    ht_bb = draw.textbbox((0, 0), hand_title, font=f_tbl_head)
    draw.text((200, hand_y + 14), hand_title, fill=C_REC, font=f_tbl_head)

    hand_start_x = 325
    for idx, t_str in enumerate(hand_tiles):
        t_im = _get_rendered_tile_image(t_str, tile_w, tile_h)
        px = hand_start_x + idx * (tile_w + 3)
        if idx == len(hand_tiles) - 1 and len(hand_tiles) == 14:
            px += 8
        img.paste(t_im, (px, hand_y), t_im)

    # 5. 候选动作决策统计表
    table_y_top = 590
    draw.line([(40, table_y_top), (W - 40, table_y_top)], fill=C_TBL_BORDER, width=1)

    headers = ["候选", "平均局收支", "局收支 CI", "予想顺位", "1位率", "2位率", "3位率", "4位率", "鳳七pt", "鳳八pt", "鳳九pt", "鳳十pt"]
    col_widths = [135, 125, 175, 90, 65, 65, 65, 65, 80, 80, 80, 80]

    x_cur = 40
    for h_txt, cw_val in zip(headers, col_widths):
        draw.text((x_cur, table_y_top + 10), h_txt, fill=C_TEXT_WHITE, font=f_tbl_head)
        x_cur += cw_val

    draw.line([(40, table_y_top + 38), (W - 40, table_y_top + 38)], fill=C_TBL_BORDER, width=1)

    row_y = table_y_top + 46
    for cand in cands:
        c_name = str(cand.get("candidate") or cand.get("discard") or "?")
        if c_name == "tsumo" or cand.get("first_tsumo"):
            discard_display = "自摸 (Tsumo)"
        elif c_name == "ron" or cand.get("first_ron"):
            discard_display = "荣和 (Ron)"
        elif c_name == "pass" or cand.get("first_pass"):
            discard_display = "见逃 (Pass)"
        elif c_name.startswith("chi:") or cand.get("first_chi"):
            discard_display = f"吃 {c_name.replace('chi:', '')}"
        elif c_name.startswith("pon") or cand.get("first_pon"):
            fu = c_name.replace("pon", "")
            discard_display = f"碰 {fu}" if fu else "碰 (Pon)"
        elif c_name == "daiminkan" or cand.get("first_daiminkan"):
            discard_display = "大明杠"
        elif cand.get("first_kyushu") or c_name == "kyushu:kk":
            discard_display = "九種九牌"
        else:
            discard_display = (cand.get("discard") or "?")
            if cand.get("first_kan"):
                discard_display = f"暗杠 {discard_display}"
            elif cand.get("first_riichi"):
                discard_display = f"立直打 {discard_display}"
            else:
                discard_display = f"打 {discard_display}"

        pt = (cand.get("hanchan") or {}).get("dan_pt_ev", {})
        er = (cand.get("hanchan") or {}).get("expected_rank", {}).get("value")
        rr = (cand.get("hanchan") or {}).get("rank_rates", [])

        values = [
            discard_display,
            _fmt_signed((cand.get("value") or {}).get("point", {}).get("value"), 0),
            _fmt_ci((cand.get("value") or {}).get("point", {}).get("ci95")),
            f"{er:.2f}" if er is not None else "—",
            _fmt_rate(rr[0].get("rate") if len(rr) > 0 else None),
            _fmt_rate(rr[1].get("rate") if len(rr) > 1 else None),
            _fmt_rate(rr[2].get("rate") if len(rr) > 2 else None),
            _fmt_rate(rr[3].get("rate") if len(rr) > 3 else None),
            _fmt_signed((pt.get("houou_7") or {}).get("value")),
            _fmt_signed((pt.get("houou_8") or {}).get("value")),
            _fmt_signed((pt.get("houou_9") or {}).get("value")),
            _fmt_signed((pt.get("houou_10") or {}).get("value")),
        ]

        cx_tbl = 40
        is_best = (c_name == recommended_tile) or (cand.get("discard") == recommended_tile)
        c_color = C_REC if is_best else C_TEXT_WHITE

        for val_txt, cw_val in zip(values, col_widths):
            draw.text((cx_tbl, row_y), val_txt, fill=c_color, font=f_tbl_cell)
            cx_tbl += cw_val

        row_y += 34

    draw.text((40, H - 24), "由 MortalSim 早巡模拟器生成 · 牌桌视角参考 Mortal Review / Tenhou", fill=C_TEXT_MUTED, font=f_foot)

    img.save(str(output_path), "PNG")
    return output_path

from __future__ import annotations

import json
from html import escape
from io import BytesIO
from typing import Any, Callable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


YAKU_NAMES = {
    "riichi": "立直",
    "double_riichi": "两立直",
    "ippatsu": "一发",
    "menzen_tsumo": "门前清自摸和",
    "tanyao": "断幺九",
    "pinfu": "平和",
    "iipeikou": "一杯口",
    "seat_wind_east": "自风东",
    "seat_wind_south": "自风南",
    "seat_wind_west": "自风西",
    "seat_wind_north": "自风北",
    "round_wind_east": "场风东",
    "round_wind_south": "场风南",
    "round_wind_west": "场风西",
    "round_wind_north": "场风北",
    "haku": "白",
    "hatsu": "发",
    "chun": "中",
    "rinshan": "岭上开花",
    "chankan": "抢杠",
    "haitei": "海底摸月",
    "houtei": "河底捞鱼",
    "sanshoku_doujun": "三色同顺",
    "ikkitsuukan": "一气通贯",
    "chanta": "混全带幺九",
    "chiitoitsu": "七对子",
    "toitoi": "对对和",
    "sanankou": "三暗刻",
    "honroutou": "混老头",
    "sanshoku_doukou": "三色同刻",
    "sankantsu": "三杠子",
    "shousangen": "小三元",
    "honitsu": "混一色",
    "junchan": "纯全带幺九",
    "ryanpeikou": "二杯口",
    "chinitsu": "清一色",
    "kokushi": "国士无双",
    "suuankou": "四暗刻",
    "daisangen": "大三元",
    "shousuushii": "小四喜",
    "daisuushii": "大四喜",
    "tsuuiisou": "字一色",
    "chinroutou": "清老头",
    "ryuuiisou": "绿一色",
    "chuuren": "九莲宝灯",
    "suukantsu": "四杠子",
    "tenhou": "天和",
    "chiihou": "地和",
    "renhou": "人和",
    "nagashi_mangan": "流局满贯",
    "dora": "宝牌",
    "ura_dora": "里宝牌",
    "aka_dora": "赤宝牌",
    "kita": "拔北",
    "double_yakuman": "双倍役满",
}


def _candidate_label(candidate: dict[str, Any]) -> str:
    prefix = "立直打 " if candidate.get("first_riichi") else "打 "
    return prefix + str(candidate.get("discard", ""))


def _get(value: Any, path: str) -> Any:
    for key in path.split("."):
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def _number(candidate: dict[str, Any], path: str) -> Any:
    value = _get(candidate, path)
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _ci(candidate: dict[str, Any], path: str) -> str:
    value = _get(candidate, path)
    ci95 = value.get("ci95") if isinstance(value, dict) else None
    if not ci95:
        return "样本不足"
    return f"{ci95[0]:+.2f} 至 {ci95[1]:+.2f}"


def _rate(candidate: dict[str, Any], path: str) -> str:
    value = _get(candidate, path)
    if not isinstance(value, dict) or value.get("rate") is None:
        return "不可用"
    return f"{value['rate']:.2%} ({value.get('count', 0)}/{value.get('total', 0)})"


def _pair(candidate: dict[str, Any], left: str, right: str) -> str:
    left_value = _get(candidate, left)
    right_value = _get(candidate, right)
    if not isinstance(left_value, dict) or not isinstance(right_value, dict):
        return "不可用"
    if left_value.get("rate") is None or right_value.get("rate") is None:
        return "不可用"
    return f"{left_value['rate']:.2%} / {right_value['rate']:.2%}"


def _flatten(prefix: str, value: Any, output: list[tuple[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), child, output)
    elif isinstance(value, list):
        output.append((prefix, json.dumps(value, ensure_ascii=False)))
    elif value is not None:
        output.append((prefix, value))


def _autosize(sheet: Any, maximum: int = 60) -> None:
    for index, column in enumerate(sheet.columns, 1):
        width = max((len(str(cell.value)) for cell in column if cell.value is not None), default=8)
        sheet.column_dimensions[get_column_letter(index)].width = min(maximum, max(10, width + 2))


def _excel_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _append(sheet: Any, values: list[Any]) -> None:
    sheet.append([_excel_safe(value) for value in values])


def _style_header(cells: Any) -> None:
    for cell in cells:
        cell.fill = PatternFill("solid", fgColor="0B5D50")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center")


def _metric_rows(
    candidates: list[dict[str, Any]],
    *,
    point_available: bool = True,
) -> list[tuple[str, str, Callable[[dict[str, Any]], Any]]]:
    rows: list[tuple[str, str, Callable[[dict[str, Any]], Any]]] = [
        ("价值与顺位", "平均局收支（NAGA 口径）", lambda c: _number(c, "value.point") if point_available else "不可用"),
        ("价值与顺位", "局收支 95% CI", lambda c: _ci(c, "value.point") if point_available else "不可用"),
        ("价值与顺位", "平均终局顺位", lambda c: _number(c, "rank.average")),
    ]
    rows.extend(
        ("价值与顺位", f"{rank} 位率", lambda c, index=rank - 1: _rate(c, f"rank.positions.{index}"))
        for rank in range(1, 5)
    )
    rows.extend([
        ("五类终局", "自家和牌", lambda c: _rate(c, "outcome.self_win")),
        ("五类终局", "自家放铳", lambda c: _rate(c, "outcome.self_deal_in")),
        ("五类终局", "流局", lambda c: _rate(c, "outcome.draw")),
        ("五类终局", "横移动", lambda c: _rate(c, "outcome.sideways")),
        ("五类终局", "他家自摸", lambda c: _rate(c, "outcome.other_tsumo")),
        ("五类终局", "其中：自家荣和", lambda c: _rate(c, "outcome.self_ron")),
        ("五类终局", "其中：自家自摸", lambda c: _rate(c, "outcome.self_tsumo")),
        ("和牌构成", "立直和牌占比", lambda c: _rate(c, "win.riichi_share")),
        ("和牌构成", "副露和牌占比", lambda c: _rate(c, "win.open_share")),
        ("和牌构成", "默听和牌占比", lambda c: _rate(c, "win.dama_share")),
        ("和牌构成", "自摸 / 荣和", lambda c: _pair(c, "win.tsumo_share", "win.ron_share")),
        ("和牌构成", "平均和牌点", lambda c: _number(c, "win.average_point")),
        ("和牌构成", "平均和牌素点", lambda c: _number(c, "win.average_raw_point")),
        ("和牌构成", "平均翻数", lambda c: _number(c, "win.average_han")),
        ("和牌构成", "平均符数", lambda c: _number(c, "win.average_fu")),
        ("防守", "放铳率", lambda c: _rate(c, "defense.deal_in_rate")),
        ("防守", "被自摸率", lambda c: _rate(c, "defense.other_tsumo_rate")),
        ("防守", "横移动率", lambda c: _rate(c, "defense.sideways_rate")),
        ("防守", "平均放铳损失", lambda c: _number(c, "defense.average_deal_in_loss")),
        ("防守", "平均放铳巡目", lambda c: _number(c, "defense.average_deal_in_turn")),
        ("立直、听牌与副露", "立直率", lambda c: _rate(c, "riichi.rate")),
        ("立直、听牌与副露", "先制 / 追立占比", lambda c: _pair(c, "riichi.first_rate", "riichi.chase_rate")),
        ("立直、听牌与副露", "立直后和牌率", lambda c: _rate(c, "riichi.win_after_rate")),
        ("立直、听牌与副露", "平均立直巡目", lambda c: _number(c, "riichi.average_turn")),
        ("立直、听牌与副露", "听牌率", lambda c: _rate(c, "tenpai.rate")),
        ("立直、听牌与副露", "平均首次听牌巡目", lambda c: _number(c, "tenpai.average_first_turn")),
        ("立直、听牌与副露", "副露率", lambda c: _rate(c, "call.rate")),
        ("立直、听牌与副露", "平均副露数", lambda c: _number(c, "call.average_count")),
        ("立直、听牌与副露", "副露后和牌率", lambda c: _rate(c, "call.win_after_rate")),
    ])
    yaku_ids = list(dict.fromkeys(item.get("id") for candidate in candidates for item in candidate.get("yaku", [])))
    for yaku_id in yaku_ids:
        def yaku_value(candidate: dict[str, Any], identifier: str = str(yaku_id)) -> str:
            item = next((entry for entry in candidate.get("yaku", []) if entry.get("id") == identifier), None)
            if not item or not item.get("available") or item.get("rate") is None:
                return "不可用"
            suffix = f" · 总枚数 {item['total_tiles']}" if item.get("total_tiles") is not None else ""
            return f"{item.get('count', 0)} 局 · {item['rate']:.2%}{suffix}"

        rows.append(("役种频率", f"{YAKU_NAMES.get(str(yaku_id), str(yaku_id))} [{yaku_id}]", yaku_value))
    return rows


def build_xlsx(result: dict[str, Any]) -> bytes:
    candidates = list(result.get("candidates") or result.get("summaries") or [])
    point_available = result.get("metrics_version") == 2
    workbook = Workbook()
    metrics = workbook.active
    metrics.title = "指标总表"
    metrics.freeze_panes = "C2"
    _append(metrics, ["分组", "指标", *(_candidate_label(candidate) for candidate in candidates)])
    _style_header(metrics[1])
    last_section = None
    for section, label, getter in _metric_rows(candidates, point_available=point_available):
        _append(metrics, [section if section != last_section else "", label, *(getter(candidate) for candidate in candidates)])
        last_section = section
    metrics.auto_filter.ref = metrics.dimensions
    _autosize(metrics)

    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def build_html(result: dict[str, Any], run_id: str) -> str:
    candidates = list(result.get("candidates") or result.get("summaries") or [])
    headers = "".join(f"<th>{escape(_candidate_label(candidate))}</th>" for candidate in candidates)
    rows: list[str] = []
    last_section = None
    for section, label, getter in _metric_rows(candidates, point_available=result.get("metrics_version") == 2):
        if section != last_section:
            rows.append(f"<tr class='section'><th colspan='{len(candidates) + 1}'>{escape(section)}</th></tr>")
            last_section = section
        cells = []
        for candidate in candidates:
            value = getter(candidate)
            cells.append(f"<td>{escape(str(value if value is not None else '不可用'))}</td>")
        values = "".join(cells)
        rows.append(f"<tr><th>{escape(label)}</th>{values}</tr>")

    facts: list[tuple[str, Any]] = []
    for key in ("schema_version", "metrics_version", "created_at", "runs", "total_runs", "seed", "elapsed"):
        if result.get(key) is not None:
            facts.append((key, result[key]))
    for section in ("config", "engine", "model", "hardware", "resolved_context", "resolved_input"):
        _flatten(section, result.get(section), facts)
    fact_rows = "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in facts
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>MortalSim {escape(run_id)}</title>
<style>
body{{font:14px system-ui;margin:32px auto;max-width:1440px;padding:0 20px;color:#1d282d;background:#f4f7f6}}
h1,h2{{color:#123e36}}p{{color:#647276}}.table-wrap{{overflow:auto;background:#fff;border:1px solid #d9e1de}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:9px 12px;border-bottom:1px solid #e4e9e7;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left;position:sticky;left:0;background:#fff}}thead th{{background:#123e36;color:#fff;position:sticky;top:0}}
.section th{{position:static!important;background:#e7f0ed!important;color:#264942!important;text-align:left!important}}
.facts{{max-width:900px}}.facts th{{width:260px}}code{{font-family:ui-monospace,monospace}}
</style></head><body>
<h1>MortalSim 分析结果</h1><p>Run <code>{escape(run_id)}</code></p>
<h2>候选指标总表</h2><div class="table-wrap"><table><thead><tr><th>指标</th>{headers}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>运行信息</h2><div class="table-wrap facts"><table><tbody>{fact_rows}</tbody></table></div>
</body></html>"""

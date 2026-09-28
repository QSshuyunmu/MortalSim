#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天梯榜单 API 服务器（轻量版，为 keqing1-workbench React 前端服务）。

背景：合作仓库原版 workbench/replay/server.py 的 import 链依赖私有包 keqing_core
（来自未公开的 keqing-mortal 仓库），无法独立部署。本服务器按其**完全相同的
HTTP 契约与 enrichment 语义**（排序键、模型聚合、快照元数据、readiness）实现
前端所需的 4 个只读端点，数据直接读转换器产出的 JSON 三件套 + 赛季注册表。
前端 build 产物原样复用，未来 keqing_core 可用时可直接换回原版 server.py。

端点（与 ladderApi.ts 对齐）：
  GET /api/ladder/seasons
  GET /api/ladder/seasons/{sid}?sort=rank|pt|rating|avg_rank|games
  GET /api/ladder/seasons/{sid}/accounts/{aid}?recent_games=50&curve_points=240
  GET /api/ladder/seasons/{sid}/models/{mid}
  其余非 /api 路径 → SPA fallback（dist/index.html）

启动：
  python ladder_api_server.py --data-root C:/arena/ladder_ui_data \
      --dist C:/arena/ladder_ui/dist --port 50721
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

LADDER_SORTS = ("rank", "pt", "rating", "avg_rank", "games")
RANK_NAMES_CN = {1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段",
                 6: "六段", 7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位"}


def rank_id_of(dan: int) -> str:
    return "tenhou" if dan >= 11 else f"{int(dan)}dan"


def rank_ordinal_of(dan: int) -> int:
    return 21 if dan >= 11 else 10 + int(dan)


class LadderStore:
    """读取转换器产出的注册表 + 三件套，进程内缓存按 mtime 失效。"""

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self._cache: dict[str, tuple[float, dict]] = {}

    def _registry_path(self, season_id: str) -> Path:
        return self.data_root / "ladder" / "registries" / f"{season_id}.json"

    def _snapshot_dir(self, season_id: str) -> Path:
        return self.data_root / "ladder" / "seasons" / season_id / "snapshots" / "latest"

    def load_season(self, season_id: str) -> dict:
        """返回 {registry, summary, ledger_by_aid, curve_by_aid, snapshot_meta}，带 mtime 缓存。"""
        reg_path = self._registry_path(season_id)
        snap = self._snapshot_dir(season_id)
        summary_path = snap / "account_summary.json"
        matchups_path = snap / "model_matchups.json"
        if not reg_path.is_file() or not summary_path.is_file():
            raise FileNotFoundError(season_id)
        m_mtime = matchups_path.stat().st_mtime if matchups_path.is_file() else 0.0
        stamp = max(reg_path.stat().st_mtime, summary_path.stat().st_mtime, m_mtime)
        cached = self._cache.get(season_id)
        if cached and cached[0] == stamp:
            return cached[1]

        registry = json.loads(reg_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if registry.get("schema") != "keqing.ladder.season.v1":
            raise ValueError(f"registry schema 不支持: {registry.get('schema')}")
        if summary.get("schema") not in ("keqing.mortal.platform_account_report.v1",
                                         "keqing.mortal.platform_account_report.v2"):
            raise ValueError(f"report schema 不支持: {summary.get('schema')}")

        reg_index = {}
        for m in registry.get("models", []):
            for acc in m.get("accounts", []):
                reg_index[acc["account_id"]] = {
                    "model_id": m["model_id"],
                    "checkpoint": m.get("checkpoint"),
                    "display_name": acc.get("display_name") or acc["account_id"],
                }

        ledger_by_aid: dict[str, list[dict]] = {}
        ledger_path = snap / "account_ledger.jsonl"
        if ledger_path.is_file():
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                ledger_by_aid.setdefault(row.get("account_id"), []).append(row)

        curve_by_aid: dict[str, list[dict]] = {}
        curve_path = snap / "rating_curve.csv"
        if curve_path.is_file():
            import csv as _csv
            with open(curve_path, "r", encoding="utf-8", newline="") as f:
                for row in _csv.DictReader(f):
                    try:
                        point = {"games": int(float(row["games"])),
                                 "rating": float(row["rating"]),
                                 "pt": int(float(row["pt"]))}
                    except Exception:
                        continue
                    for k in ("rank_id", "rank_name", "pt_target", "rank_before",
                              "rank_after", "transition"):
                        v = row.get(k)
                        if v not in (None, ""):
                            point[k] = int(v) if k == "pt_target" else v
                    curve_by_aid.setdefault(row.get("account_id"), []).append(point)

        matchups = {}
        matchups_path = snap / "model_matchups.json"
        if matchups_path.is_file():
            try:
                matchups = json.loads(matchups_path.read_text(encoding="utf-8"))
            except Exception:
                matchups = {}

        data = {"registry": registry, "summary": summary,
                "reg_index": reg_index, "ledger": ledger_by_aid,
                "curve": curve_by_aid, "matchups": matchups,
                "snapshot_meta": {"snapshot_id": snap.name,
                                  "updated_at": int(summary_path.stat().st_mtime)}}
        self._cache[season_id] = (stamp, data)
        return data

    def season_ids(self) -> list[str]:
        reg_dir = self.data_root / "ladder" / "registries"
        if not reg_dir.is_dir():
            return []
        return sorted(p.stem for p in reg_dir.glob("*.json"))


def enrich_rows(store: LadderStore, season_id: str) -> list[dict]:
    data = store.load_season(season_id)
    reg_index, summary = data["reg_index"], data["summary"]
    rows = []
    for raw in summary.get("accounts", []):
        aid = raw.get("account_id")
        meta = reg_index.get(aid)
        if meta is None:
            raise HTTPException(status_code=409, detail={
                "reason": {"state": "invalid", "code": "account_not_in_registry",
                           "message": f"账号 {aid} 未在注册表声明", "retryable": False}})
        games = int(raw.get("games") or 0)
        r1, r2, r3, r4 = (int(raw.get(k) or 0) for k in ("rank_1", "rank_2", "rank_3", "rank_4"))
        target = raw.get("pt_target")
        current = float(raw.get("pt_current") or 0.0)
        avg_rank_raw = raw.get("avg_rank")
        row = dict(raw)
        row.update({
            "display_name": meta["display_name"],
            "model_id": meta["model_id"],
            "checkpoint": meta["checkpoint"],
            "games": games,
            "pt_current": current,
            "rating": float(raw.get("rating") or 0.0),
            "rank_1": r1, "rank_2": r2, "rank_3": r3, "rank_4": r4,
            "rank_1_rate": (r1 / games if games else None),
            "rank_4_rate": (r4 / games if games else None),
            "pt_gap": (float(target) - current if target is not None else None),
            "avg_rank": (float(avg_rank_raw) if avg_rank_raw is not None else None),
        })
        rows.append(row)
    return rows


def sorted_rows(rows: list[dict], sort: str) -> list[dict]:
    if sort not in LADDER_SORTS:
        sort = "rank"
    if sort == "rank":
        rows.sort(key=lambda r: (-int(r.get("rank_ordinal") or 0),
                                 -float(r.get("pt_current") or 0.0),
                                 -float(r.get("rating") or 0.0),
                                 str(r.get("account_id"))))
    elif sort == "pt":
        rows.sort(key=lambda r: float(r.get("pt_current") or 0.0), reverse=True)
    elif sort == "rating":
        rows.sort(key=lambda r: float(r.get("rating") or 0.0), reverse=True)
    elif sort == "avg_rank":
        rows.sort(key=lambda r: (r.get("avg_rank") is None,
                                 float(r["avg_rank"]) if r.get("avg_rank") is not None else 0.0))
    else:  # games
        rows.sort(key=lambda r: int(r.get("games") or 0), reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank_position"] = i
    return rows


def summarize_models(rows: list[dict]) -> list[dict]:
    by_model: dict[str, list[dict]] = {}
    for r in rows:
        by_model.setdefault(str(r.get("model_id")), []).append(r)

    def _weighted(items: list[dict], key: str):
        values = [(float(i[key]), int(i["games"])) for i in items
                  if i.get(key) is not None and int(i["games"]) > 0]
        total = sum(c for _, c in values)
        if not values or total == 0:
            return None
        return sum(v * c for v, c in values) / total

    def _median(values: list[int]):
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[mid])
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    def _rank_name_for_ordinal(ordinal):
        if ordinal is None:
            return None
        if ordinal >= 21:
            return "天凤位"
        if ordinal >= 11:
            return RANK_NAMES_CN.get(ordinal - 10, None)
        return None

    summaries = []
    for model_id, items in by_model.items():
        games = sum(int(i.get("games") or 0) for i in items)
        distinct = {i.get("rank_id") for i in items}
        rank_names = [str(i.get("rank_name") or i.get("rank_id") or "?") for i in items]
        ordinals = [int(i.get("rank_ordinal") or 0) for i in items]
        highest = max(items, key=lambda i: int(i.get("rank_ordinal") or 0))
        summaries.append({
            "model_id": model_id,
            "accounts": len(items),
            "games": games,
            "avg_pt": (_weighted(items, "pt_current") if len(distinct) <= 1 else None),
            "avg_rating": _weighted(items, "rating"),
            "avg_rank": _weighted(items, "avg_rank"),
            "avg_rank_pt": _weighted(items, "avg_rank_pt"),
            "rank_distribution": {name: rank_names.count(name)
                                  for name in sorted(set(rank_names))},
            "highest_rank_id": highest.get("rank_id"),
            "highest_rank_name": highest.get("rank_name"),
            "highest_rank_ordinal": int(highest.get("rank_ordinal") or 0),
            "median_rank_ordinal": _median(ordinals),
            "median_rank_name": _rank_name_for_ordinal(_median(ordinals)),
        })
    summaries.sort(key=lambda s: (-(s.get("highest_rank_ordinal") or 0),
                                  s.get("avg_rating") is None,
                                  -(s.get("avg_rating") or 0.0)))
    return summaries


def season_public(store: LadderStore, season_id: str, is_default: bool = True) -> dict:
    data = store.load_season(season_id)
    reg, summary = data["registry"], data["summary"]
    return {
        "season_id": season_id,
        "title": reg.get("title"),
        "status": reg.get("status", "draft"),
        "games_expected": reg.get("games_expected"),
        "notes": reg.get("notes"),
        "models": [m.get("model_id") for m in reg.get("models", [])],
        "accounts": len(summary.get("accounts", [])),
        "games": summary.get("games"),
        "data_ready": True,
        "report_schema": summary.get("schema"),
        "scoring": reg.get("scoring"),
        "is_default": is_default,
        "readiness": {"state": "ready", "code": "ready",
                      "message": "赛季数据已就绪", "retryable": False},
        **data["snapshot_meta"],
    }


def downsample_curve(points: list[dict], max_points: int) -> list[dict]:
    """等距降采样，但**必须包含真末点**。

    这里踩过一个坑：原先写成 `step = len/max`、`points[int(i*step)]`，
    最后一个 i=max-1 的索引是 `int((max-1)*step)`，永远取不到 len-1。
    实测 896 局时末点停在第 892 号索引（第 893 局，pt 860），而当前 PT 是
    第 896 局的 815 —— 前端图表徽标取 `points[length-1]`，于是"曲线末值"
    比页头"当前 PT"落后几局，表现为"pt 曲线和实际当前 pt 对不上"
    （截图里 768 局时为 pt 1515 vs 页头 1440，正是第 765 局 vs 第 768 局）。
    口径与前端加载器一致：抽 max_points-1 个，再强制追加真末点。
    """
    if max_points <= 0:
        return []
    if max_points == 1:
        return points[-1:] if points else []
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    picked: list[dict] = []
    seen: set = set()
    for i in range(max_points - 1):
        p = points[min(int(round(i * step)), len(points) - 1)]
        if p["games"] not in seen:
            seen.add(p["games"])
            picked.append(p)
    last = points[-1]
    if not picked or picked[-1]["games"] != last["games"]:
        picked.append(last)          # 真末点无条件保留
    return picked


def create_app(data_root: Path, dist_dir: Path | None) -> FastAPI:
    app = FastAPI(title="Atozuke Ladder API", docs_url=None, redoc_url=None)
    store = LadderStore(data_root)

    @app.middleware("http")
    async def _no_store_api(request: Request, call_next):
        """API 响应一律禁缓存。

        踩过的坑：GET 且不带 Cache-Control 时浏览器可启发式缓存，于是同一页上
        「头部当前 PT」和「曲线末点」可能来自相差一次导出的两版数据——实测
        LuckyJ2-分身 截图里头部 pt=1440（第 768 局）而曲线末点 pt=1515（第 765 局），
        相差 3 局，正是图表的 payload 被浏览器缓存住旧版所致。数据本身没错，
        错在两块 UI 读到了不同版本，所以从源头掐掉缓存。
        """
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    def _season_or_404(season_id: str) -> dict:
        try:
            return season_public(store, season_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail={
                "reason": {"state": "not_published", "code": "season_not_found",
                           "message": f"赛季 {season_id} 不存在", "retryable": False}})
        except ValueError as e:
            raise HTTPException(status_code=409, detail={
                "reason": {"state": "invalid", "code": "bad_schema",
                           "message": str(e), "retryable": False}})

    @app.get("/api/ladder/seasons")
    def list_seasons():
        ids = store.season_ids()
        seasons, default_id = [], None
        for sid in ids:
            try:
                entry = season_public(store, sid, is_default=(default_id is None))
            except Exception:
                entry = {"season_id": sid, "data_ready": False,
                         "readiness": {"state": "invalid", "code": "unreadable",
                                       "message": "数据读取失败", "retryable": True}}
            else:
                if default_id is None and entry.get("status") == "running":
                    default_id = sid
            seasons.append(entry)
        return {"schema": "keqing.ladder.seasons.v1",
                "default_season_id": default_id,
                "default_source": ("registry" if default_id else None),
                "seasons": seasons}

    @app.get("/api/ladder/seasons/{season_id}")
    def get_ladder(season_id: str, request: Request):
        sort = request.query_params.get("sort", "pt")
        sp = _season_or_404(season_id)
        rows = sorted_rows(enrich_rows(store, season_id), sort)
        return {"season": sp, "sort": sort, "accounts": rows,
                "models": summarize_models(rows)}

    @app.get("/api/ladder/seasons/{season_id}/matchups")
    def get_matchups(season_id: str):
        sp = _season_or_404(season_id)
        data = store.load_season(season_id)
        matchups = data.get("matchups") or {"schema": "keqing.ladder.matchups.v1", "models": [], "matrix": {}}
        return {"season": sp, "matchups": matchups}

    @app.get("/api/ladder/seasons/{season_id}/accounts/{account_id}")
    def get_account(season_id: str, account_id: str, request: Request):
        try:
            recent_n = max(0, min(int(request.query_params.get("recent_games", "50")), 200))
            curve_n = max(0, min(int(request.query_params.get("curve_points", "240")), 1000))
        except ValueError:
            recent_n, curve_n = 50, 240
        sp = _season_or_404(season_id)
        data = store.load_season(season_id)
        rows = sorted_rows(enrich_rows(store, season_id), "rank")
        row = next((r for r in rows if r.get("account_id") == account_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail={
                "reason": {"state": "invalid", "code": "account_not_found",
                           "message": f"账号 {account_id} 不存在", "retryable": False}})
        ledger = data["ledger"].get(account_id, [])
        recent = []
        for r in ledger[-recent_n:]:
            r = dict(r)
            if r.get("score_delta") is None:
                r["score_delta"] = int(r.get("final_score") or 0) - 25000
            recent.append(r)
        curve = downsample_curve(data["curve"].get(account_id, []), curve_n)
        return {"season": sp, "account": row,
                "rank_distribution": [row.get("rank_1", 0), row.get("rank_2", 0),
                                      row.get("rank_3", 0), row.get("rank_4", 0)],
                "curve": curve, "recent_games": recent}

    @app.get("/api/ladder/seasons/{season_id}/models/{model_id}")
    def get_model(season_id: str, model_id: str):
        sp = _season_or_404(season_id)
        rows = sorted_rows(enrich_rows(store, season_id), "rank")
        accs = [r for r in rows if r.get("model_id") == model_id]
        if not accs:
            raise HTTPException(status_code=404, detail={
                "reason": {"state": "invalid", "code": "model_not_found",
                           "message": f"模型 {model_id} 不存在", "retryable": False}})
        summaries = summarize_models(accs)
        reg = store.load_season(season_id)["registry"]
        checkpoint = next((m.get("checkpoint") for m in reg.get("models", [])
                           if m.get("model_id") == model_id), None)
        return {"season": sp,
                "model": {"model_id": model_id, "checkpoint": checkpoint,
                          "accounts": accs, "summary": (summaries[0] if summaries else None)},
                "league_summary": None}

    # ---- SPA 静态资源 ----
    if dist_dir and (dist_dir / "index.html").is_file():
        assets = dist_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            candidate = dist_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(dist_dir / "index.html"))
    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="C:/arena/ladder_ui_data")
    ap.add_argument("--dist", default="C:/arena/ladder_ui/dist")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=50721)
    a = ap.parse_args()
    import uvicorn
    app = create_app(Path(a.data_root), Path(a.dist) if a.dist else None)
    print(f"[ladder-api] data_root={a.data_root} dist={a.dist} "
          f"http://{a.host}:{a.port}", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()

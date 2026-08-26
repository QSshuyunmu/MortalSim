import sys, time, httpx
from pathlib import Path
sys.path.insert(0, r'D:\tenhoulib\MortalSim-Bot\src')
from parser import parse_sim_command
from render_png import render_png

client = httpx.Client(base_url="http://127.0.0.1:50715", trust_env=False, timeout=15)

def run_test(case_name, msg, rec_tile, out_png_name):
    print(f"\n==================================================================")
    print(f"运行: {case_name}")
    print(f"指令: {msg}")
    print(f"==================================================================")
    req, err = parse_sim_command(msg)
    assert err is None, f"Parse error: {err}"
    req["model_id"] = "mortal-0a88ddad649804d0"
    req["batch_size"] = 1000
    req["rayon_threads"] = 20
    req["runs"] = 50

    while True:
        resp = client.post("/api/runs", json=req)
        if resp.status_code in (200, 201, 202):
            break
        print("Waiting for server to become free...")
        time.sleep(2)

    run_id = resp.json()["run_id"]
    print("Run ID:", run_id)

    while True:
        j = client.get(f"/api/runs/{run_id}").json()
        if j.get("status") == "completed": break
        if j.get("status") in ("failed", "cancelled"):
            print("Failed:", j.get("error"))
            raise SystemExit(1)
        time.sleep(2)

    res = client.get(f"/api/runs/{run_id}/result").json()
    print("候选计算结果:")
    for c in res.get("candidates", []):
        pt = (c.get("hanchan") or {}).get("dan_pt_ev", {}).get("houou_7", {}).get("value")
        er = (c.get("hanchan") or {}).get("expected_rank", {}).get("value")
        val = c.get('value',{}).get('point',{}).get('value')
        print(f"  - {c.get('candidate')}: 局收支={val if val is not None else 0:+.1f}, 予想顺位={er if er is not None else 0:.3f}, 凤七pt={pt if pt is not None else 0:+.2f}")

    out_png = Path(f"D:/tenhoulib/MortalSim-Bot/data/output/{out_png_name}")
    res["config"] = j.get("request", {})
    render_png(
        res,
        asset_dir="D:/tenhoulib/MortalSim-Local-v0.3.0-rc.1-new10/_internal/apps/web/dist/tiles",
        font_path="C:/Windows/Fonts/msyh.ttc",
        output_path=out_png,
        recommended_tile=rec_tile,
    )
    print(f"渲染生成成功: {out_png}")

# Case 1: Tsumo vs Discard (Hand: 123456789m 789s 11p, last tile 1p is valid Tsumo!)
run_test("样例 1: 自摸 (Tsumo) vs 拒胡切牌 (1p, 9s)", "/sim 123456789m789s11p d8p c=tsumo,1p,9s E1-0 100", "tsumo", "sample_tsumo.png")

# Case 2: Ron vs Pass vs 6m
# Hand: 5667m0678p1367s77z, waiting on 2s/7s or 7z. Kami discards 7z -> Valid Ron!
run_test("样例 2: 荣和 (Ron) vs 见逃 (Pass) vs 切6m", "/sim 5667m0678p1367s77z d8m c=ron,pass,6m E2-1 P181,211,397,211 50 seat=西 x=3 河=2zt,1pt,3zt / 5zt,1zt,1st /1pt,2z / 2z,7z", "ron", "sample_ron_pass.png")

# Case 3: Chi / Pon vs Pass
run_test("样例 3: 吃碰副露 (Chi / Pon) vs 门清 (Pass)", "/sim 450m3406p6666789s d6m c=chi:45m>9s,pon>9s,pass seat=西 x=1 河=4z/6m", "chi:45m>9s", "sample_chi_pon.png")

print("\n==================================================================")
print("ALL 3 SNAPSHOT ACTION TEST CASES EXECUTED & RENDERED PERFECTLY!")
print("==================================================================")

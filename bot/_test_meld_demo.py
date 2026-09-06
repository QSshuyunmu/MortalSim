import sys, time, httpx
from pathlib import Path
sys.path.insert(0, r'D:\tenhoulib\MortalSim-Bot\src')
from parser import parse_sim_command
from render_png import render_png

client = httpx.Client(base_url="http://127.0.0.1:50715", trust_env=False, timeout=15)

msg = "/sim 2334m0678p456s77z d1p c=chi:24m>7z,pon>7z,pass E1-0 500 seat=南 x=2 河=1z,3m / 1s / 9p / 9s"
print("1. Parsing command:", msg)
req, err = parse_sim_command(msg)
print("Parse error:", err)
assert err is None

req["model_id"] = "mortal-0a88ddad649804d0"
req["batch_size"] = 1000
req["rayon_threads"] = 20
req["runs"] = 500

print("\n2. Submitting to MortalSim...")
resp = client.post("/api/runs", json=req)
print("HTTP Status:", resp.status_code)
if resp.status_code not in (200, 201, 202):
    print("Response:", resp.text)
    raise SystemExit(1)

run_id = resp.json()["run_id"]
print("Run ID:", run_id)

t0 = time.time()
while True:
    j = client.get(f"/api/runs/{run_id}").json()
    status = j.get("status")
    prog = j.get("progress")
    print(f"[{time.time()-t0:.1f}s] status={status}, progress={prog}", flush=True)
    if status == "completed":
        break
    if status in ("failed", "cancelled"):
        print("Failed:", j.get("error") or j.get("diagnostic_log"))
        raise SystemExit(1)
    time.sleep(5)

print("\n3. Simulation Results:")
res = client.get(f"/api/runs/{run_id}/result").json()
for c in res.get("candidates", []):
    val = (c.get("value") or {}).get("point", {}).get("value")
    ci = (c.get("value") or {}).get("point", {}).get("ci95")
    han = c.get("hanchan") or {}
    er = (han.get("expected_rank") or {}).get("value")
    pt = (han.get("dan_pt_ev") or {}).get("houou_7", {}).get("value")
    print(f"  - 候选 {c.get('candidate')}: 局收支={val:+.1f} (95% CI {ci}), 予想顺位={er:.3f}, 凤七pt={pt:+.2f}")

out_png = Path("D:/tenhoulib/MortalSim-Bot/data/output/meld_decision_500.png")
res["config"] = j.get("request", {})
# Pick recommended
point_best = max(res["candidates"], key=lambda c: (c.get("value") or {}).get("point", {}).get("value", float("-inf")))
pt_best = max(res["candidates"], key=lambda c: ((c.get("hanchan") or {}).get("dan_pt_ev") or {}).get("houou_7", {}).get("value", float("-inf")))
rec_tile = pt_best.get("candidate")

render_png(
    res,
    asset_dir="D:/tenhoulib/MortalSim-Local-v0.3.0-rc.1-new10/_internal/apps/web/dist/tiles",
    font_path="C:/Windows/Fonts/msyh.ttc",
    output_path=out_png,
    recommended_tile=rec_tile,
)
print("Rendered PNG successfully to:", out_png)

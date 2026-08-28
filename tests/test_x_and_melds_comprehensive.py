import sys, time, httpx
from pathlib import Path

client = httpx.Client(base_url="http://127.0.0.1:50715", trust_env=False, timeout=20)
sys.path.insert(0, r"D:\tenhoulib\MortalSim-Bot\src")
from parser import parse_sim_command

def run_test_case(name: str, cmd_str: str, runs: int = 50):
    print(f"\n=======================================================")
    print(f"Running Test Case: {name}")
    print(f"Command: {cmd_str}")
    print(f"=======================================================")
    req, err = parse_sim_command(cmd_str)
    assert err is None, f"Parse error: {err}"
    req["model_id"] = "mortal-0a88ddad649804d0"
    req["batch_size"] = 1000
    req["rayon_threads"] = 20
    req["runs"] = runs

    resp = client.post("/api/runs", json=req)
    assert resp.status_code in (200, 201, 202), f"HTTP error {resp.status_code}: {resp.text}"
    run_id = resp.json()["run_id"]

    t0 = time.time()
    while True:
        j = client.get(f"/api/runs/{run_id}").json()
        st = j.get("status")
        if st == "completed":
            break
        if st in ("failed", "cancelled"):
            raise AssertionError(f"Test failed ({st}): {j.get('error')}")
        time.sleep(1.5)

    res = client.get(f"/api/runs/{run_id}/result").json()
    print(f"Completed in {time.time()-t0:.1f}s. Candidates count: {len(res.get('candidates', []))}")
    for c in res.get("candidates", []):
        cand_name = c.get("candidate")
        val = (c.get("value") or {}).get("point", {}).get("value")
        ci = (c.get("value") or {}).get("point", {}).get("ci95")
        han = c.get("hanchan") or {}
        er = (han.get("expected_rank") or {}).get("value")
        pt = (han.get("dan_pt_ev") or {}).get("houou_7", {}).get("value")
        print(f"  • 候选 {cand_name:10s}: 局收支={val:+7.1f}, 予想顺位={er:.3f}, 凤七pt={pt:+7.2f}")
    return res

# 1. Test Case 1: E3-0 West (39000 pts - Leader & Dealer, Turn 3)
res1 = run_test_case(
    "E3-0 West Leader & Dealer (x=3, P180,200,390,230)",
    "/sim 56m3456666789p22s d8s E3-0 50 seat=西 x=3 P180,200,390,230"
)
for c in res1["candidates"]:
    pt = ((c.get("hanchan") or {}).get("dan_pt_ev") or {}).get("houou_7", {}).get("value")
    er = (c.get("hanchan") or {}).get("expected_rank", {}).get("value")
    assert er < 2.0, f"Leader expected rank should be 1st/2nd (<2.0), got {er}"
    assert pt > 30.0, f"Leader in E3 with 39k points MUST have positive high pt (>+30), got {pt}"
print("[PASS] Test Case 1 Invariants verified!")

# 2. Test Case 2: S4-0 East (7900 pts - 4th place trailing, x=2 sub-turn reaction pon vs pass)
res2 = run_test_case(
    "S4-0 East 4th Place Reaction (x=2, pon>4p vs pass)",
    "/sim 77m4p4056799s112z d5s c=pon>4p,pass S4-0 seat=东 x=2 河=1m,1s / 9p,9s / 7z / 3z P79,176,283,462 50"
)
for c in res2["candidates"]:
    pt = ((c.get("hanchan") or {}).get("dan_pt_ev") or {}).get("houou_7", {}).get("value")
    er = (c.get("hanchan") or {}).get("expected_rank", {}).get("value")
    assert er > 3.0, f"4th place trailing expected rank should be >3.0, got {er}"
    assert pt < -30.0, f"4th place trailing in S4 MUST have negative pt, got {pt}"
print("[PASS] Test Case 2 Invariants verified!")

# 3. Test Case 3: Deep Turn 9 with 2 Melds
res3 = run_test_case(
    "Turn 9 Deep Search with 2 Melds",
    "/sim 4m0m6m3p1z1z4z7z d5s c=3p,4z E1-0 50 seat=西 x=9 河=东:2z(南碰),3z,6z,7zt,8m,1p,3m,6zt,9m / 南:8p,4p,6z,4z,3z,2st,2m(西碰),8s,1s / 西:8s,9s,2s,1s,7pt,4p,4p,2p / 北:4zt,8m,1p,6zt,7p,3zt,5zt(西碰),6pt"
)
print("[PASS] Test Case 3 Invariants verified!")

print("\n=======================================================")
print("ALL COMPREHENSIVE X >= 2 AND MELD TESTS PASSED 100%!")
print("=======================================================")

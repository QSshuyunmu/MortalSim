# Inspect the served ladder snapshot JSON on Atozuke. ASCII-only.
$ErrorActionPreference = "Continue"
$py = "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe"

$code = @'
import json, os, glob
base = r"C:\arena\ladder_ui_data\ladder"
snaps = glob.glob(base + r"\seasons\*\snapshots\*")
for s in snaps:
    f = os.path.join(s, "account_summary.json")
    if not os.path.exists(f):
        print("MISSING", f); continue
    import datetime
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(f))
    d = json.load(open(f, encoding="utf-8"))
    a0 = d["accounts"][0]
    keys = sorted(a0.keys())
    need = ["games_houou", "games_tokujou", "stable_dan_houou", "stable_dan_tokujou",
            "agari_rate", "stats_games", "stable_dan", "highest_rank_name"]
    print("FILE", f)
    print("  mtime", mt, "| games", d.get("games"), "| accounts", len(d["accounts"]))
    print("  row0:", a0.get("account_id"), a0.get("display_name"))
    for k in need:
        print(f"    {k:<20} present={k in keys} value={a0.get(k)!r}")
    nonnull = {k: sum(1 for a in d["accounts"] if a.get(k) is not None) for k in need}
    print("  non-null counts:", nonnull)
'@

$tmp = "C:\arena\ladder\_inspect_snap.py"
Set-Content -Path $tmp -Value $code -Encoding UTF8
& $py -X utf8 $tmp
Remove-Item $tmp -ErrorAction SilentlyContinue

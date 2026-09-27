# Remote ladder DB/stat check (WAL-aware). ASCII-only.
$ErrorActionPreference = "Continue"
$py = "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe"

$code = @'
import sqlite3, os, glob
db = r"C:\arena\ladder_results.db"
con = sqlite3.connect(db)
rows = con.execute("SELECT COUNT(*) FROM ladder_games").fetchone()[0]
mx = con.execute("SELECT MAX(seed_idx) FROM ladder_games").fetchone()[0]
ks = os.path.getsize(db) / 1024 / 1024
print("DB_ROWS", rows, "HANCHAN", rows // 4, "MAX_SEED", mx, "DB_MB", round(ks, 1))
try:
    n = con.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0]
    print("PLAYER_STATS", n)
    for r in con.execute("SELECT avatar_id, rounds, agari, houjuu, fuuro, riichi FROM player_stats ORDER BY rounds DESC LIMIT 6"):
        aid, rd, ag, hj, fu, rc = r
        print(f"  {aid:<14} rounds={rd:>5} agari={ag/rd:.3f} houjuu={hj/rd:.3f} fuuro={fu/rd:.3f} riichi={rc/rd:.3f}")
except Exception as e:
    print("PLAYER_STATS_ERR", e)
con.close()

logs = glob.glob(r"C:\arena\ladder_logs\**\*.json.gz", recursive=True)
tot = sum(os.path.getsize(p) for p in logs) if logs else 0
print("LOG_FILES", len(logs), "TOTAL_MB", round(tot / 1024 / 1024, 1),
      "AVG_KB", round(tot / len(logs) / 1024, 1) if logs else 0)
days = sorted({os.path.basename(os.path.dirname(p)) for p in logs})
print("LOG_DAYS", days)
'@

$tmp = "C:\arena\ladder\_check_db.py"
Set-Content -Path $tmp -Value $code -Encoding UTF8
& $py -X utf8 $tmp
Remove-Item $tmp -ErrorAction SilentlyContinue

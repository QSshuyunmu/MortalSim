#!/usr/bin/env python3
"""kyoku_sim_win.py — Windows 版自亲第一打模拟器 (batched)

Usage:
  python kyoku_sim_win.py --hand "123456789m1234p" --first-tsumo "1m" \
      --discard "1m" --dora "5s" --runs 100 --seed 42
"""
import sys, os, time, argparse
from pathlib import Path

# Resolve both source checkouts and PyInstaller's bundled ``_internal`` tree
# without embedding a developer-specific absolute path.
MORTAL_ROOT = Path(__file__).resolve().parents[1]
MORTAL_DIR = str(MORTAL_ROOT / "mortal")
LIBRIICHI_DIR = str(MORTAL_ROOT / "target" / "release")
MODEL_PATH = str(MORTAL_ROOT / "models" / "model_v4_20240308_best_min.pth")
ONNX_MODEL_PATH = str(MORTAL_ROOT / "models" / "model_v4_20240308_best_min.onnx")

TILE_NAMES = {"1m","2m","3m","4m","5m","6m","7m","8m","9m",
    "1p","2p","3p","4p","5p","6p","7p","8p","9p",
    "1s","2s","3s","4s","5s","6s","7s","8s","9s",
    "E","S","W","N","P","F","C","5mr","5pr","5sr"}

def parse_hand(s):
    tiles = []
    nums = ""
    honor_map = {"1":"E","2":"S","3":"W","4":"N","5":"P","6":"F","7":"C"}
    explicit_honors = {"E","S","W","N","P","F","C"}
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "mps":
            for n in nums:
                if n == "0":
                    t = "5" + ch + "r"  # 0s → 5sr (赤5)
                else:
                    t = n + ch
                if t not in TILE_NAMES: raise ValueError(f"Unknown: {t}")
                tiles.append(t)
            nums = ""
        elif ch == "z":
            for n in nums:
                if n in honor_map:
                    t = honor_map[n]
                    if t not in TILE_NAMES: raise ValueError(f"Unknown: {t}")
                    tiles.append(t)
                else: raise ValueError(f"Bad honor: {n}z")
            nums = ""
        elif ch in "0123456789": nums += ch
        elif ch in explicit_honors:
            if nums: raise ValueError(f"Unexpected honor after numbers")
            tiles.append(ch)
        else: raise ValueError(f"Unexpected: {ch}")
        i += 1
    if nums: raise ValueError(f"Trailing: {nums}")
    return tiles

def main():
    ap = argparse.ArgumentParser(description="自亲第一打模拟器")
    ap.add_argument("--kyoku", type=int, default=1)
    ap.add_argument("--honba", type=int, default=0)
    ap.add_argument("--kyotaku", type=int, default=0)
    ap.add_argument("--bakaze", default="E")
    ap.add_argument("--oya", type=int, default=0)
    ap.add_argument("--scores", type=int, nargs=4, default=[25000]*4)
    ap.add_argument("--dora", default="5s")
    ap.add_argument("--hand", default="123456789m1234p")
    ap.add_argument("--first-tsumo", default=None, help="指定第一摸牌 (如 '1m')")
    ap.add_argument("--discard", default="1m")
    ap.add_argument("--first-kan", default=None, help="第一打暗杠 (如 '9m')")
    ap.add_argument("--first-kyushu", action="store_true", help="第一打九種九牌流局")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--batch-size", type=int, default=1000,
                    help="Max games advanced in parallel per run_many call. "
                         "Larger = bigger inference batch = faster, but more GPU RAM.")
    ap.add_argument("--engine", choices=("python", "onnx"), default="python",
                    help="Inference backend. ONNX is experimental until strict parity passes.")
    ap.add_argument("--onnx-model", default=ONNX_MODEL_PATH)
    ap.add_argument("--rayon-threads", type=int, default=20,
                    help="Rust worker threads. Benchmarked default: 20.")
    args = ap.parse_args()

    if args.rayon_threads is not None:
        if args.rayon_threads < 1:
            ap.error("--rayon-threads must be at least 1")
        os.environ["RAYON_NUM_THREADS"] = str(args.rayon_threads)

    sys.path.insert(0, MORTAL_DIR)
    sys.path.insert(0, LIBRIICHI_DIR)
    import libriichi

    hand = parse_hand(args.hand)
    print(f"Hand: {hand}", flush=True)
    print(f"First tsumo: {args.first_tsumo}  First discard: {args.discard}  Dora: {args.dora}", flush=True)
    print(f"Oya: {args.oya}  Kyoku: {args.kyoku}  Honba: {args.honba}", flush=True)
    print(f"Runs: {args.runs}", flush=True)

    print(f"libriichi version: {libriichi.__version__}", flush=True)

    dll_directories = []
    if args.engine == "onnx":
        import onnxruntime
        import torch
        capi_dir = os.path.join(os.path.dirname(onnxruntime.__file__), "capi")
        torch_lib_dir = os.path.join(os.path.dirname(os.__file__), "site-packages", "torch", "lib")
        os.environ["ORT_DYLIB_PATH"] = os.path.join(capi_dir, "onnxruntime.dll")
        if hasattr(os, "add_dll_directory"):
            dll_directories.append(os.add_dll_directory(capi_dir))
            dll_directories.append(os.add_dll_directory(torch_lib_dir))
        # Load PyTorch's bundled CUDA 12/cuDNN 9 DLLs before ORT registers CUDA.
        torch.cuda.init()
        print(f"Engine: ONNX Runtime CUDA ({args.onnx_model})", flush=True)
        eng = libriichi.arena.MortalOnnxEngine(args.onnx_model, 0, True)
    else:
        import torch
        from model import Brain, DQN
        from engine import MortalEngine

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Engine: PyTorch ({device})", flush=True)
        state = torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
        cfg = state["config"]
        v = cfg["control"]["version"]
        c = cfg["resnet"]["conv_channels"]
        b = cfg["resnet"]["num_blocks"]
        brain = Brain(version=v, conv_channels=c, num_blocks=b).eval().to(device)
        dqn = DQN(version=v).eval().to(device)
        brain.load_state_dict(state["mortal"])
        dqn.load_state_dict(state["current_dqn"])
        print(f"Model: v{v} {c}ch {b}blocks", flush=True)
        eng = MortalEngine(brain, dqn, is_oracle=False, version=v, device=device,
                           enable_amp=(device.type=="cuda"), name="M",
                           enable_rule_based_agari_guard=True)
    runner = libriichi.arena.CustomKyokuRunner()

    t0 = time.time()
    # Basic type/rank counters
    type_counts = {"hora": 0, "tsumo": 0, "ryukyoku": 0, "error": 0}
    ranks = [0, 0, 0, 0]

    # Stat accumulator for the target player (oya)
    stat_fields = [
        "round", "oya", "point",
        "agari", "agari_as_oya", "agari_jun", "agari_point_oya", "agari_point_ko",
        "houjuu", "houjuu_jun", "houjuu_to_oya", "houjuu_point_to_oya", "houjuu_point_to_ko",
        "riichi", "riichi_as_oya", "riichi_jun", "riichi_agari", "riichi_agari_jun",
        "riichi_agari_point", "riichi_houjuu", "riichi_ryukyoku", "riichi_point",
        "fuuro", "fuuro_num", "fuuro_agari", "fuuro_agari_jun", "fuuro_agari_point",
        "fuuro_houjuu", "fuuro_point",
        "dama_agari", "dama_agari_jun", "dama_agari_point",
        "ryukyoku", "ryukyoku_point",
        "rank_1", "rank_2", "rank_3", "rank_4", "tobi",
        "yakuman", "nagashi_mangan",
        "chasing_riichi", "riichi_got_chased",
    ]
    stat_sum = {f: 0 for f in stat_fields}

    # Run games in chunks of --batch-size so each run_many call advances many
    # in-flight games in parallel, keeping the inference batch large and the GPU
    # saturated. Profiling showed ~98% of wall time is GPU model fwd at small
    # batch; per-call overhead is <2%, so batch size is the only real lever.
    # (Earlier BATCH=20 gave avg batch 11 → 2.9 games/s; BATCH=1000 gives avg
    # batch ~550 → 9.3 games/s, a 3.2x speedup, with zero behaviour change.)
    BATCH = max(1, min(args.batch_size, args.runs))
    done = 0
    for batch_start in range(0, args.runs, BATCH):
        n = min(BATCH, args.runs - batch_start)
        try:
            results = runner.run_many(
                engine=eng, kyoku=args.kyoku, honba=args.honba, kyotaku=args.kyotaku,
                bakaze=args.bakaze, oya=args.oya, scores=args.scores,
                dora_marker=args.dora, main_haipai=hand,
                first_discard=args.discard,
                first_tsumo=args.first_tsumo,
                first_kan=args.first_kan,
                first_kyushu=args.first_kyushu,
                seed_start=(args.seed + batch_start, 0xDEAD), count=n,
            )
        except Exception as e:
            print(f"  batch@{batch_start}: {e}", flush=True)
            type_counts["error"] += n
            continue
        for r in results:
            typ = r["result"]["type"]
            if typ in type_counts:
                type_counts[typ] += 1
            ranks[r["players"][args.oya]["final_rank"] - 1] += 1

            # Accumulate Stat fields for the target player
            st = r.get("stat")
            if st is not None:
                for f in stat_fields:
                    stat_sum[f] += getattr(st, f)
            done += 1

    elapsed = time.time() - t0
    total = type_counts["hora"] + type_counts["tsumo"] + type_counts["ryukyoku"]
    if total == 0:
        print(f"\nAll failed (errors: {type_counts['error']})", flush=True)
        return

    rnd = stat_sum["round"] or total  # fallback
    agari_total = stat_sum["agari"]
    houjuu_total = stat_sum["houjuu"]
    riichi_total = stat_sum["riichi"]
    fuuro_total = stat_sum["fuuro"]
    ryukyoku_total = stat_sum["ryukyoku"]
    avg_rank = sum((i+1)*ranks[i] for i in range(4)) / total

    def safe_div(a, b):
        return a / b if b else 0.0

    print(f"\n{'='*60}")
    print(f"  自亲第一打模拟器 — 结果")
    print(f"{'='*60}")
    print(f"  总局数: {total}  错误: {type_counts['error']}  耗时: {elapsed:.1f}s ({total/elapsed:.1f}/s)")
    print(f"{'─'*60}")
    print(f"  【局结果分布】")
    print(f"    荣和: {type_counts['hora']:4d} ({type_counts['hora']/total:.1%})")
    print(f"    自摸: {type_counts['tsumo']:4d} ({type_counts['tsumo']/total:.1%})")
    print(f"    流局: {type_counts['ryukyoku']:4d} ({type_counts['ryukyoku']/total:.1%})")
    print(f"{'─'*60}")
    print(f"  【目标玩家 (seat {args.oya}, 亲家) 统计】")
    print(f"    和了率:   {safe_div(agari_total, rnd):.1%}  ({agari_total}/{rnd})")
    print(f"    放铳率:   {safe_div(houjuu_total, rnd):.1%}  ({houjuu_total}/{rnd})")
    print(f"    立直率:   {safe_div(riichi_total, rnd):.1%}  ({riichi_total}/{rnd})")
    print(f"    副露率:   {safe_div(fuuro_total, rnd):.1%}  ({fuuro_total}/{rnd})")
    print(f"    流局率:   {safe_div(ryukyoku_total, rnd):.1%}  ({ryukyoku_total}/{rnd})")
    print(f"    局收支:   {safe_div(stat_sum['point'], rnd):+.1f}")
    print(f"{'─'*60}")
    print(f"  【和了详细】")
    ap_oya = stat_sum["agari_point_oya"]
    ap_ko = stat_sum["agari_point_ko"]
    print(f"    平均和了点:     {safe_div(ap_oya + ap_ko, agari_total):.0f}")
    print(f"      亲家和了点:   {safe_div(ap_oya, stat_sum['agari_as_oya']):.0f}  ({stat_sum['agari_as_oya']}次)")
    print(f"      子家和了点:   {safe_div(ap_ko, agari_total - stat_sum['agari_as_oya']):.0f}  ({agari_total - stat_sum['agari_as_oya']}次)")
    print(f"    平均和了巡数:   {safe_div(stat_sum['agari_jun'], agari_total):.1f}")
    print(f"    役满:           {stat_sum['yakuman']}")
    print(f"{'─'*60}")
    print(f"  【放铳详细】")
    hp_oya = stat_sum["houjuu_point_to_oya"]
    hp_ko = stat_sum["houjuu_point_to_ko"]
    print(f"    平均放铳点:     {safe_div(hp_oya + hp_ko, houjuu_total):.0f}")
    print(f"      放铳给亲家:   {safe_div(hp_oya, stat_sum['houjuu_to_oya']):.0f}  ({stat_sum['houjuu_to_oya']}次)")
    print(f"      放铳给子家:   {safe_div(hp_ko, houjuu_total - stat_sum['houjuu_to_oya']):.0f}  ({houjuu_total - stat_sum['houjuu_to_oya']}次)")
    print(f"    平均放铳巡数:   {safe_div(stat_sum['houjuu_jun'], houjuu_total):.1f}")
    print(f"{'─'*60}")
    print(f"  【立直详细】")
    print(f"    立直和了率:     {safe_div(stat_sum['riichi_agari'], riichi_total):.1%}  ({stat_sum['riichi_agari']}/{riichi_total})")
    print(f"    立直放铳率:     {safe_div(stat_sum['riichi_houjuu'], riichi_total):.1%}  ({stat_sum['riichi_houjuu']}/{riichi_total})")
    print(f"    立直流局率:     {safe_div(stat_sum['riichi_ryukyoku'], riichi_total):.1%}  ({stat_sum['riichi_ryukyoku']}/{riichi_total})")
    print(f"    平均立直巡数:   {safe_div(stat_sum['riichi_jun'], riichi_total):.1f}")
    print(f"    平均立直收支:   {safe_div(stat_sum['riichi_point'], riichi_total):+.1f}")
    print(f"    追立率:         {safe_div(stat_sum['chasing_riichi'], riichi_total):.1%}")
    print(f"{'─'*60}")
    print(f"  【副露详细】")
    print(f"    副露后和了率:   {safe_div(stat_sum['fuuro_agari'], fuuro_total):.1%}")
    print(f"    副露后放铳率:   {safe_div(stat_sum['fuuro_houjuu'], fuuro_total):.1%}")
    print(f"    平均副露次数:   {safe_div(stat_sum['fuuro_num'], fuuro_total):.2f}")
    print(f"{'─'*60}")
    print(f"  【ダマ詳細】")
    dama_total = stat_sum["dama_agari"]
    print(f"    ダマ和了:       {dama_total}")
    if dama_total:
        print(f"    ダマ平均和了点: {safe_div(stat_sum['dama_agari_point'], dama_total):.0f}")
        print(f"    ダマ平均巡数:   {safe_div(stat_sum['dama_agari_jun'], dama_total):.1f}")
    print(f"{'─'*60}")
    print(f"  【顺位分布】")
    labels = ["一位","二位","三位","四位"]
    for i in range(4):
        bar = "#" * int(ranks[i] / total * 50)
        print(f"    {labels[i]}: {ranks[i]:4d} ({ranks[i]/total:.1%}) {bar}")
    print(f"    平均顺位: {avg_rank:.3f}")
    print(f"{'─'*60}")
    print(f"  SMOKE_TEST_PASS")

if __name__ == "__main__":
    main()

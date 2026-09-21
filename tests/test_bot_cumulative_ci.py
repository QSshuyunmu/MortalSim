"""Regression tests ensuring confidence intervals strictly shrink as runs accumulate."""
import math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

from render_png import _resolve_ci95, _fmt_ci95

def test_resolve_ci95_monotonically_shrinks():
    cum_2k = {"runs": 2000, "mean_score": -500.0, "stddev_score": 3400.0, "mean_pt": 4.5, "stddev_pt": 15.0, "mean_mleague": -8.0, "stddev_mleague": 8.5}
    cum_4k = {"runs": 4000, "mean_score": -480.0, "stddev_score": 3380.0, "mean_pt": 4.7, "stddev_pt": 14.8, "mean_mleague": -8.1, "stddev_mleague": 8.4}
    cum_6k = {"runs": 6000, "mean_score": -470.0, "stddev_score": 3350.0, "mean_pt": 4.8, "stddev_pt": 14.6, "mean_mleague": -8.1, "stddev_mleague": 8.3}

    ci_2k = _resolve_ci95(None, cum_2k, "mean_score", "stddev_score")
    ci_4k = _resolve_ci95(None, cum_4k, "mean_score", "stddev_score")
    ci_6k = _resolve_ci95(None, cum_6k, "mean_score", "stddev_score")

    w_2k = ci_2k[1] - ci_2k[0]
    w_4k = ci_4k[1] - ci_4k[0]
    w_6k = ci_6k[1] - ci_6k[0]

    assert w_4k < w_2k, f"4k CI should be narrower than 2k CI ({w_4k} vs {w_2k})"
    assert w_6k < w_4k, f"6k CI should be narrower than 4k CI ({w_6k} vs {w_4k})"

def test_resolve_ci95_overrides_stale_single_run_ci():
    stale_single_ci = [-650.0, -350.0]
    cum_6k = {"runs": 6000, "mean_score": -470.0, "stddev_score": 3350.0}

    resolved_ci = _resolve_ci95(stale_single_ci, cum_6k, "mean_score", "stddev_score")
    resolved_w = resolved_ci[1] - resolved_ci[0]

    assert resolved_w < 200.0, f"Stale single-run CI should be replaced by cumulative tight CI, got width {resolved_w}"

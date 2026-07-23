# Result schema v2

`schema_version: 2` fixes round-end statistics around the perspective of the
configured target player (`oya`). New consumers must use `candidates`; the old
`summaries` key is read-only compatibility data.

## Terminal partition

Every completed game belongs to exactly one terminal outcome:

- `self_win`: the target player wins. `self_ron` and `self_tsumo` partition it.
- `self_deal_in`: the target player deals into another player.
- `draw`: exhaustive and abortive draws.
- `sideways`: one non-target player deals into another non-target player.
- `other_tsumo`: a non-target player wins by tsumo.

Errors are excluded from the completed-game denominator. Multi-ron is resolved
in this order: target winner, target deal-in, other-player result. The runner
also returns every actor and target in `agari_actors` and `agari_targets`.

The following invariants are checked during aggregation:

```text
self_win = self_ron + self_tsumo
completed_games = self_win + self_deal_in + draw + sideways + other_tsumo
```

## Statistical values

Rates contain `count`, `total`, `rate`, and a Wilson `ci95`. Means contain
`value`, sample `stddev`, Student-t `ci95`, `n`, `sum`, and `sum_sq`. The last
three fields form the merge state used by history extensions. A confidence
interval is `null` when there are too few observations. Candidate comparisons
use paired samples in seed order.

### Average round balance

`candidate.value.point.value` (shown as "average round balance" in the UI) is
the arithmetic mean of the target player's terminal Hora/Ryukyoku settlement
delta across completed games only. This matches NAGA's 局収支 convention: the
separate 1,000-point payment for the target's accepted riichi is not subtracted
from this value.

The exact end-minus-start score change is retained only inside the runner's
validation path. It is not part of the public result protocol. For every runner
row the following identities are verified before aggregation:

```text
score_delta = result.final_scores[oya] - result.initial_scores[oya]
round_balance - score_delta = 1000 * target_riichi_accepted
```

The headline value is not the raw value of a winning hand. It includes a
previously posted kyotaku when it is claimed. The four internal score deltas
must add up to `1000 * (kyotaku_start - kyotaku_remaining)`. A malformed row
is classified as an error and never contributes a zero to the mean.

This definition is `metrics_version: 2`. Metrics v1 histories used a retired
definition in `value.point`; their average round balance is shown as
unavailable, and they cannot be extended or compared with v2 results.

## Public round input

New requests identify the round with `round: E1..E4, S1..S4, W1..W4`.
The target player is always the dealer. `honba` and `kyotaku` are integers from
0 through 99. Scores are entered relative to the target:

```json
{
  "round": "E1",
  "honba": 0,
  "kyotaku": 0,
  "scores": {
    "self": 25000,
    "shimocha": 25000,
    "toimen": 25000
  }
}
```

The upstream player's score is derived as
`100000 - kyotaku * 1000 - self - shimocha - toimen`. All scores must be
non-negative multiples of 100.

## First-discard riichi

`discards` accepts either legacy tile strings or action objects. A riichi
candidate is a distinct action and may coexist with an ordinary discard of the
same tile:

```json
"discards": [
  {"tile": "1m", "riichi": false},
  {"tile": "1m", "riichi": true}
]
```

The runner sends `Reach` and then forces the requested discard on the next
decision. It validates the exact discard, closed-hand state, score threshold,
and post-discard tenpai condition. An unavailable first-discard riichi is an
explicit error; it is never silently simulated as an ordinary discard.

## History extensions

A completed schema-v2 result can be extended atomically:

```text
POST /api/runs/{run_id}/extensions
GET  /api/runs/{run_id}/extensions/{operation_id}/events
POST /api/runs/{run_id}/extensions/{operation_id}/cancel
```

Only `additional_runs` is accepted. New seeds continue immediately after the
existing attempted range. A cancelled or failed extension leaves the parent
result unchanged; a successful extension updates `total_runs`,
`extension_history`, confidence intervals, distributions, yaku counts, and the
deterministic representative sample pool.

## Availability

The Rust runner currently supplies terminal outcomes, all winning actors and
targets, final scores, rank, first-tenpai turn, final draw-tenpai state, riichi
state, and call count. Existing `Stat` supplies the aggregate win, deal-in,
riichi, call, draw, turn, point, yakuman, and nagashi-mangan totals.

The scoring engine returns pattern and situational yaku identities plus separate
dora, ura-dora, and aka-dora counts. The public schema always contains 55 stable
slots. Results produced by an older runner report `available: false`; they must
remain `null` rather than being represented as zero.

## Samples and replay

Candidates contain representative samples grouped by metric. At most 100 are
kept: 50 earliest seeds plus 50 deterministic hash-selected samples. Each item
stores only seed, trace hash, point delta, final rank, outcome, and win method.

Use:

```text
GET  /api/runs/{run_id}/samples?candidate=1s&metric=outcome.self_ron
POST /api/runs/{run_id}/replay
```

Replay runs exactly one game with the original configuration. When supplied,
`expected_trace_hash` is compared with the new trace and a mismatch is recorded
in the result warning list.

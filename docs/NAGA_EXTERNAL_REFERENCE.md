# External NAGA Reference

This is a reproducible external comparison record, not a regression oracle.
NAGA and MortalSim use different decision models and random streams, so their
per-run statistics are not expected to match exactly. It exists to catch a
large semantic drift in input mapping or score accounting.

## Source

- Captured: 2026-07-23
- Viewer: https://naga.dmv.nico/htmls/simulation_viewer.html?sim_ids=4eaf8e27742a06e4ab6fc35fe7e20f7fd6dd08f6a679bb468f588e859a354923,1add748b9de9cf2e28c17da809a5582eb71ff77b81d9b4324970ce8550fc420a,dbdbf20bb1c0dd27babec43d7d04e2ad85745298efec5303ccb2e03c07befa75
- NAGA result files exposed three 500-game chunks per candidate (1,500 games)
  at capture time.

## Shared situation

```text
East 1, 0 honba, 0 kyotaku
Scores: 25000 / 25000 / 25000 / 25000
Dora indicator: 9m
14-tile hand: 1m 3m 4m 5m 5mr 6m 1p 2p 3p 9p 9p 9p 1s 2s
Candidates: 1m, 5m, 2s
No first-discard riichi
```

## NAGA aggregate at capture

| Candidate | Games | Average round balance | Wins | Deal-ins | Other tsumo | Draws | Sideways |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1m | 1500 | +4434.15 | 781 | 164 | 184 | 272 | 99 |
| 5m | 1500 | +5359.97 | 694 | 196 | 196 | 297 | 117 |
| 2s | 1500 | +5287.96 | 731 | 173 | 186 | 274 | 136 |

## Score-definition audit

NAGA's displayed `mean_kyoku_bp` is effectively the target player's terminal
settlement delta. It does not subtract the separate 1,000-point payment made
when the target's riichi is accepted. This was confirmed by parsing all 1,500
public `haihu` records per candidate:

| Candidate | NAGA display | Mean terminal settlement |
| --- | ---: | ---: |
| 1m | +4434.15 | +4451.87 |
| 5m | +5359.97 | +5371.33 |
| 2s | +5287.96 | +5308.80 |

The remaining 11-21 point difference is internal to NAGA's estimator and is
negligible relative to its confidence interval. By contrast, MortalSim metrics
v1 used exact final score minus starting score. Therefore:

```text
NAGA-style round balance
  = exact net score change + 1000 * target accepted-riichi indicator
```

The audited MortalSim 2,000-game result used model SHA256
`0a88ddad649804d085491b5397d895f596b0e55f30632c549ea145bb44786563`,
seed 89, Batch 1000, and 20 Rayon threads. After applying the terminal
settlement definition, its NAGA-style balances were `+4238.95` (1m),
`+5401.70` (5m), and `+5007.30` (2s). Their 95% confidence intervals overlap
the NAGA results above. The remaining differences are small enough to be
explained by model, random-stream, and sample variation.

MortalSim metrics v2 exposes only `value.point`, the NAGA-compatible terminal
round balance. Exact score snapshots remain internal validation data and are
not a second user-facing point metric.

## Formal Lite v0.3 RC check

`stable_advantage_v2` 使用相同模型 SHA、seed 89 和局面各运行 1,000 局，得到：

| Candidate | Average round balance | Win rate | Deal-in rate |
| --- | ---: | ---: | ---: |
| 1m | +4110.7 | 48.9% | 10.1% |
| 5m | +5237.1 | 49.0% | 11.9% |
| 2s | +4994.9 | 45.5% | 12.9% |

推荐仍为 `5m`，与 NAGA 及 Legacy AMP 对照一致。该 1,000 局检查只能验证推荐方向
没有发生明显漂移，不替代 50,000 局/候选迁移 Gate。

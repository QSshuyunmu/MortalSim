# 半庄终局顺位模型（Hanchan Rank Model）

MortalSim 新增的「半庄终局予想」统计由一个 LightGBM 四分类模型驱动。它把
模拟小局结束后的下一局状态（点数、场风、局数、本场、供托、亲家）映射到
目标玩家最终半庄顺位分布。

## 与 Mortal 决策模型的关系

- 这不是 Mortal v4 权重，也不是和牌/切牌 AI；
- 它是从真实天凤凤凰卓牌谱聚合出的统计模型；
- 不包含原始牌谱、不包含玩家信息；
- 不参与模拟对局决策，只用于结果后处理统计。

## 模型产物

```text
models/hanchan_rank/
  hanchan_rank_lgb_seat0.txt
  hanchan_rank_lgb_seat1.txt
  hanchan_rank_lgb_seat2.txt
  hanchan_rank_lgb_seat3.txt
  hanchan_rank_model_manifest.json
```

## 特征 schema v1

```text
f0..f3  = s0..s3 / total
f4      = kyoku_idx / 12          # E1=0 .. W4=11
f5      = honba
f6      = kyotaku * 1000 / total
f7..f10 = oya one-hot
total   = sum(scores) + 1000 * kyotaku
```

## 段位 pt 表

见 `docs/HANCHAN_PT_TABLE.md`。

## 结果字段

每个候选新增 `candidate.hanchan`：

```json
{
  "expected_rank": {"value": 2.14, "ci95": [2.10, 2.18]},
  "rank_rates": [
    {"rank": 1, "count": 0.385, "total": 2000, "rate": 0.385, "ci95": [...]},
    {"rank": 2, ...},
    {"rank": 3, ...},
    {"rank": 4, ...}
  ],
  "dan_pt_ev": {
    "houou_7": {"value": 23.92, "ci95": [22.10, 25.72]},
    "houou_8": {"value": 21.42, "ci95": [19.50, 23.33]},
    "houou_9": {"value": 18.93, "ci95": [16.91, 20.93]},
    "houou_10": {"value": 16.44, "ci95": [14.31, 18.56]}
  }
}
```

顶层新增 `hanchan_model` 身份块，扩容合并时与运行时身份一起校验。

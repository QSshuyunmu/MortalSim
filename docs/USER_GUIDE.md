# MortalSim 使用指南

1. 双击 `Start-MortalSim.cmd`，不要从 ZIP 内直接运行，也不要只复制 `MortalSim.exe`。
2. 首次进入“设置与诊断”，确认 Formal Lite、RTX 40 Compute Capability 8.9、运行时 SHA 均可用，再导入标准 Mortal v4 / 256 / 54 `.pth`。
3. 在“新建分析”输入 14 张手牌、宝牌和候选第一打。手牌最后一张固定视为第一摸。
4. 局目选择东一至西四；自家、下家、对面点数可编辑，上家点数按 `100000 - 供托×1000 - 其余三家` 自动计算。
5. 如 14 张配牌已经听牌，可在候选牌旁开启“立”以强制第一打宣告立直；程序仍会校验该动作是否合法。
6. 设置局数和 seed。所有候选自动共享同一 seed 区间；Formal Lite Batch 固定为 1000，不能改动。
7. 点击“开始模拟”。任务抽屉显示进度、吞吐、错误数和 GPU 状态；浏览历史不会中断任务。
8. 结果页先看配对平均局收支差及 CI，再查看顺位、五类终局、和牌、防守、立直、听牌、副露、役种和稳定性曲线。
9. 使用 Excel、JSON 或 HTML 导出。Excel/HTML呈现当前指标总表的全部统计指标，JSON保留完整 schema v3 结果协议。
10. 完成且带 `merge_state_version: 2` 的 schema v3 记录可原子追加局数。取消或失败不会改写父结果；v1/v2 及早期 schema v3 RC 历史只读，只能复制配置后按正式 Lite 重跑。

结果页的契约徽标、模型 SHA、Runtime Build ID 和 Artifact SHA 是复现身份的一部分。只有这些字段、Batch、规则和 seed 全部相同的记录才允许合并。

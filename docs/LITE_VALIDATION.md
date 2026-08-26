# Formal Lite v0.3 验证说明

本文区分两个决策契约，避免把“迁移后统计接近”写成“旧引擎位级一致”。机器可读
状态以 [`LITE_VALIDATION-v0.3.0-rc.1.json`](LITE_VALIDATION-v0.3.0-rc.1.json)
为准。

## 契约

- `legacy_amp_v1`：原 PyTorch CUDA autocast、最终 Q argmax，仅用于开发对照。
- `stable_advantage_v2`：AOT CUDA 图输出 raw advantage，Rust 在合法动作中使用严格
  `>` 扫描；并列保留较小动作 ID。公开 Batch 为 1000，图容量为 1024。

模型 SHA256、运行时 Artifact SHA256、Build ID、SM89 cubin、Batch、padding 和 Rust
选择器共同定义 v2 结果身份。schema v1/v2 历史只读，不得和 schema v3 合并。

## Legacy Gate 结论

在固定 300 局、14,397 次决策的参考轨迹中，最接近的 AMP-static 原生图仍有 3 次
动作分歧。GEMM、Native Conv 和 FP32 图会在不同的近似并列状态分叉；更换卷积实现、
精度或启发式动作偏置都不能构成严格复刻。旧 AMP 攻关因此按预定停止条件结束。

该失败不是 v2 Gate 的“通过”。v0.3 通过建立新决策契约来获得轻量、可复现的正式
语义，并通过大样本迁移阈值判断它是否足够接近旧版统计行为。

## 当前 RC 已验证

本机环境：Windows x64、RTX 4050 Laptop、Compute Capability 8.9。

- `stable_advantage_v2` 图可以加载、导入用户 v4/256/54 权重并完成原生推理。
- 原生运行时 ABI、单文件 SHA 和聚合 Artifact SHA 在启动前验证。
- Rust 稳定选择器覆盖非法动作、并列、负数、NaN、空 mask 和和牌守卫。
- schema v3 保存契约、模型和运行时身份；`merge_state_version: 2` 还保存标量统计的
  精确事件数与总和，扩容要求完全相同的身份与 Batch。
- 发布构建排除 PyTorch、`.pth`、`.onnx`、日志和开发工具链。
- 本地 Formal Lite 冒烟测试已产生 0 error 的逐局签名。
- 三个独立进程对 `1s`、`6s` 各 1000 局得到完全相同的 trace/result SHA256。
- 三个兼容 v4 权重各 1000 局均为 0 error。
- `1000 + 追加1000` 与一次 2000 局对两个候选的规范化结果 SHA256 完全相同。
- 连续 30 分钟运行 43,000 局，显存首末四分位中位数均为 489 MiB、增长 0 MiB，
  0 error、0 critical sample；监测开/关三组配对吞吐差通过 1% 门槛。
- 20,000 局 Legacy AMP 语料包含 1,102,345 次决策；Formal Lite 有 631 次动作变化，
  变化率 0.05724%，低于 0.10% 门槛。
- Legacy 与 Lite 各跑 `1s`、`6s` 50,000 局：配对局收支差分别为 -2.222
  `[-86.25,+81.81]` 与 -4.868 `[-88.23,+78.49]`，五类终局最大点估计差
  0.034pp，全部通过迁移阈值。
- 最终 Portable ZIP 为 33.205 MiB，解压 71.966 MiB；模型导入、schema v3 单局、
  no-store 历史读取与敏感文件审计均通过。

本 RC 的运行时身份：

```text
engine_id: aoti-cuda-sm89
build_id: v0.3.0rc1-b9cc517e5828
artifact_sha256: b9cc517e58283b5f5520904c0feef9bf04271b4e6093019e4bd0b99afb40d2fd
batch_size: 1000
batch_capacity: 1024
precision_profile: amp-static-advantage
```

## RC 范围与未执行 Gate

项目决定本次不执行第二台 RTX 40 Windows 设备的同 Artifact 验证。因此
`v0.3.0-rc.1` 只声明当前 RTX 4050 Laptop 上的验证结果，不声明跨设备签名一致。

该选择不等同于 Gate 通过，发布状态继续保持 RC，验证 JSON 的
`formal_release_ready` 保持 `false`。未来如发布不带 RC 标识的正式 `v0.3.0`，仍需另行定义并完成跨设备支持范围。

## 复现工具

```powershell
# 采集 Legacy AMP 决策语料
python tools/parity/collect_corpus.py --output D:\corpora\legacy --runs 300

# 分层输出与 ULP 比较
python tools/parity/layer_probe.py --help
python tools/parity/compare_ulp.py reference.npz candidate.npz

# 对 100 万决策检查 Lite 动作变化率
python tools/parity/compare_runtime.py `
  --corpus D:\corpora\legacy `
  --checkpoint D:\models\model.pth `
  --runtime-dir D:\runtime `
  --output migration-actions.json

# 50,000 局/候选统计迁移 Gate
python tools/parity/migration_gate.py `
  --checkpoint D:\models\model.pth `
  --runtime-dir D:\runtime `
  --runs 50000 `
  --output migration-rounds.json

# 正式固定 seed 硬件签名
python tools/validate_formal_lite.py `
  --checkpoint D:\models\model.pth `
  --runtime-dir D:\runtime `
  --runs 1000 `
  --output gate.json

# 30 分钟显存与 GPU 监测开销 Gate
python tools/validate_vram_stability.py `
  --checkpoint D:\models\model.pth `
  --runtime-dir D:\runtime `
  --duration-seconds 1800 `
  --output vram-gate.json
```

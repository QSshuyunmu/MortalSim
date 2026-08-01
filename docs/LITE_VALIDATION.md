# Lite 验证记录

本机 RTX 4050 Laptop、NVIDIA Driver 592.82、Windows x64，构建于 2026-08-01。

## 已通过

- `cargo test -p libriichi --lib`: 34 passed
- Python/API tests: 50 passed
- 前端 `npm run build`: passed
- Lite PyInstaller Portable: generated successfully
- Lite archive: 36.7 MiB compressed; 81.3 MiB unpacked
- 打包 `MortalSim.exe` 启动并返回 `/api/health` 200
- 不安装 Python/Rust/CUDA Toolkit 的运行时路径只加载 Lite CUDA DLL；发布包不含权重
- 三个本地 v4 权重可由受限解析器读取，架构均为 256 channels / 54 blocks
- 当前 RTX 4050 Laptop 单次 1000 局测量：PyTorch AMP Reference 12.27 局/s，Lite 11.89 局/s（约 96.9%）；该测量不改变严格一致性结论

## 未通过的发布门槛

当前 AOTInductor CUDA 图尚未达到参考 PyTorch AMP 的逐局严格等价，不能把 Lite 图声明为最终权威引擎。固定 1000 seed 语料（同一局面、同一 seed、同一模型）结果如下：

| 图 | trace hash 不同 | result 不同 | metrics 不同 |
| --- | ---: | ---: | ---: |
| AMP-static GEMM B1024 | 667 | 598 | 546 |
| FP32 GEMM B256 | 732 | 666 | 616 |

上述结果中的“固定动作偏差校正”实验已废弃：它是针对单个 corpus 的启发式，不属于可发布算法，也没有进入源代码。

在保持同一 Rust 轨迹、只比较每个决策的动作时，AMP-static 图在 300 局、14,397 个决策中出现 3 个近似 Q 值分叉。它们会在后续局面中级联，所以不能把“多数决策相同”当作严格等价。

使用正式验收局面 `4567m3477p134066s`、摸牌 `6s`、宝牌指示 `9s`、seed `(42, 0xDEAD)`，并让 Rust 分别沿参考动作和 Lite 动作进行比较时，当前 AMP-static 图仍有动作分叉：

| 首打 | 参考轨迹决策数 | 动作不同 |
| --- | ---: | ---: |
| `1s` | 55,438 | 43 |
| `6s` | 56,842 | 29 |

因此这两个固定语料不能宣称终局、得点或 trace hash 严格一致；它们会在第一个分叉后产生不同轨迹。Native Conv AMP 与 FP32 GEMM 只是在不同近似并列时改变分叉位置，300 局探针仍各出现 3 次分叉，没有一个可以安全替代参考路径。

为消除这个近似，另行尝试了带 `torch.autocast("cuda")` 的 AOT 图。Windows MSVC 环境可以完成图捕获，但 ExecuTorch/Triton 在 RTX 4050 的共享内存限制（要求 131072 bytes，硬件上限 101376）处失败；普通 PowerShell 还会因缺少 `CUDA_HOME` 提前失败。该实验没有生成可运行的候选 DLL，不能算作通过。

因此当前 Lite 图只能作为实验性能路径；严格比较应使用 `MORTALSIM_ENGINE=python` 的参考 AMP 引擎。发布流程在严格语料通过前不得把 Lite 标记为“100% 一致”。

## 下一步门槛

1. 若继续做 Lite，应改用能控制 Triton block/shared-memory 的新后端；本轮 `torch.autocast` AOT 图已记录为不可用候选。
2. 只有新的图在 `1s`、`6s` 固定 1000 seed 上逐决策 100% 一致，才比较终局、得点和 trace hash。
3. 只有逐局 100% 一致且吞吐达到参考路径 70% 后，才移除本页的实验状态并把 Lite 作为正式默认；在此之前发布包必须保留 Reference/实验标记。

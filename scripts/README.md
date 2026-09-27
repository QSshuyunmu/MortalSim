# Atozuke 天凤四卓分层天梯自弈竞技场（CPU · ONNX）

30 席 Avatar 分身矩阵 · 凤凰/特上/上级三卓自动升降 · 冲击 11 段「天凤位」。
运行于 Atozuke（192.168.123.2 · 14C/18T · 32GB · 无 CUDA · Python 3.13），全 CPU ONNX 推理。

---

## 一、架构

```
┌──────────────────────────────────────────────────────────────┐
│ 计划任务 AtozukeLadderArena（开机自启 + 崩溃自愈 + 单实例守卫）│
│  └ ladder_arena_atozuke.py                                   │
│     ├ 11 款物理引擎（ONNX 优先，PyTorch 回退，全 CPU）        │
│     ├ 30 席 Avatar → 三卓升降状态机（ladder_engine.py）       │
│     ├ 6 桌并行 × 64 半庄/桌，心跳报活，中断即存档             │
│     ├ C:/arena/ladder_results.db（逐局簿记）+ ladder_state.json│
│     └ 每 5 批：滚动备份 + 生成 workbench UI 数据三件套        │
│ 计划任务 AtozukeLadderUI（端口 28787）                        │
│  └ ladder_api_server.py（FastAPI）+ keqing1-workbench 前端    │
│     └ /api/ladder/* ← 读三件套                                │
└──────────────────────────────────────────────────────────────┘
浏览器 → http://192.168.123.2:28787   实时榜单
本机终端 → ladder_watch_local.py      文字看板
```

## 二、目录结构

| 文件 | 说明 |
|---|---|
| `ladder_arena_atozuke.py` | 主运行器：组桌/调度/结算/心跳/断点续跑/停机文件 |
| `ladder_engine.py` | 天梯核心：PlayerState 升降段状态机、官方算分、Avatar |
| `models_config.json` | 11 款物理模型 + 30 席 Avatar 的权威配置（v2.3） |
| `export_ladder_for_workbench.py` | DB → 合作仓库榜单 UI 的 JSON 三件套转换器 |
| `ladder_api_server.py` | 榜单 API（FastAPI，前端契约与 keqing1-workbench 原版一致） |
| `ladder_watch_local.py` | 本机终端看板（纯标准库，自适应宽度） |
| `bench_ladder.py` | 吞吐微基准台：变体隔离矩阵 + 确定性哈希校验 |
| `export_ladder_onnx.py` | PolicyNet 头模型的 ONNX 融合导出 + 等价性校验 |
| `optional_producer_protection.py` | 可选：特上生产者保级保护（默认关闭） |
| `remote/daemon_ladder.ps1` | 远端守护循环（自愈 + 单实例守卫） |
| `remote/switch_to_ladder.ps1` | 守护切换脚本（停旧混池任务/注册新任务/防火墙） |
| `remote/probe_ladder.ps1` | 状态探针（进程/CPU 采样/日志尾/UI 健康检查） |
| `remote/proc_tree.ps1` | 进程树查询（排查双实例用） |

配套 Rust 补丁：[`third_party/libriichi-rs/`](../../../third_party/libriichi-rs/)（见下文「libriichi 补丁」）。

## 三、快速开始

```powershell
# 0) 前置：Atozuke 已有 C:\arena\{mortal, models\tsypx, models\onnx, pyd_native, onnxruntime.dll}
#    Python 3.13 + fastapi + uvicorn（UI 用）

# 1) 部署代码（本机执行）
scp -r scripts/atozuke_arena/* new-machine:C:/arena/ladder/
scp -r keqing1-workbench/workbench/replay_ui/dist new-machine:C:/arena/ladder_ui/

# 2) 编译 Rust 补丁（本机）
cd libriichi-rs && cargo build --release --lib
# 产物 libriichi.dll 重命名为 libriichi.pyd → Atozuke:C:\arena\pyd_native\libriichi.pyd

# 3) 切换守护 + 启动（Atozuke 管理员执行一次）
powershell -File C:\arena\ladder\switch_to_ladder.ps1

# 4) 观察
Get-Content C:\arena\ladder\ladder_stdout.log -Tail 20 -Encoding UTF8
```

## 四、配置参考

### 卓别门槛与算分（天凤官方规程）

| 卓别 | 准入（AND） | 一位 | 二位 | 三位 | 四位 |
|---|---|---|---|---|---|
| 凤凰卓 | 七段 且 R≥2000 | +90 | +45 | 0 | −(15×段位+30) |
| 特上卓 | 四段 且 R≥1800 | +75 | +30 | 0 | 同上 |
| 上级卓 | 一段以上 或 R≥1600 | +60 | +15 | 0 | 同上 |

- 升段：PT ≥ 400×段位；降段：PT<0 重置 200×新段位；初段保底重置
- 天凤位：十段满 4000PT 晋升，此后段位/PT 永久冻结
- 100R 缓冲：凤桌初始 R2100、特上初始 R1900（避免单局吃四即掉卓）

### 运行参数（daemon 或命令行）

| 参数 | 默认 | 说明 |
|---|---|---|
| `--batch-seeds` | 16 | 每桌 64 半庄；批越大单 obs 摊销越好，反馈越慢 |
| `--tables-per-room` | 3 | 每卓并行桌数（共 6 桌）。**实测 6 桌是 18 核甜点，10 桌过订阅崩溃** |
| `ARENA_ONNX_THREADS` | 1 | ONNX intra 线程。**实测 1 全面优于 2**（真实批次仅 4~8 obs） |
| `LADDER_TORCH_THREADS` | 3 | PyTorch 回退通路线程数 |
| `--seed-base` | 300000 | seed 起点；每次启动自动续接到库内最大 seed 之后 |

## 五、运维手册

| 操作 | 方式 |
|---|---|
| 优雅停机 | `New-Item C:\arena\LADDER_STOP` → 跑完当前批并存档后退出 |
| 查看进度 | 日志尾 `[心跳]`（每 60s：分钟/完成桌/在跑桌）与 `[桌完]`（单桌吞吐） |
| 中断 | 第一次 Ctrl+C / kill → 等待在跑桌完成并**全部入库**；第二次才硬放弃 |
| 断点续跑 | 重启后自动：库 seed 续接 + `ladder_state.json` 恢复 30 席段位/PT/R |
| 单实例守卫 | guardian 每轮检查是否已有 ladder 进程，杜绝双实例写同一 DB |
| 榜单 UI | `http://192.168.123.2:28787`（防火墙规则 AtozukeLadderUI） |
| 回滚旧混池 | `schtasks /Change /TN AtozukeLadderArena /DISABLE` + `/ENABLE` 旧任务；`pool_results.db` 全程未动 |

## 六、libriichi 补丁（根因分析与验证）

### 根因：全局推理被 GIL 串行化

`agent/mortal.rs` 原生 ONNX 路径的 `native.infer(...)` 原本整个运行在
`Python::with_gil` 闭包内（`PyRef` 借用要求持有 GIL）。多桌并发的全部推理
因此被一把 GIL 串成单核——18 核机器实测仅用 1.6~3.9 核，且与引擎类型无关。

### 修复（本次 5 个文件）

| 文件 | 变更 |
|---|---|
| `arena/mortal_onnx.rs` | `Session` 改 `Arc<Mutex<Session>>`（ort rc.12 `run` 需 `&mut`，Mutex 保留但**锁等待移到 GIL 外**）；推理逻辑抽为自由函数 `infer_batch(session, ...)`；新增 `infer_direct` pymethod（基准用） |
| `agent/mortal.rs` | 原生路径：GIL 内仅克隆 `Arc` 句柄（纳秒级），推理在 GIL 之外执行；新增 `ensure_evaluated` |
| `agent/defs.rs` | `BatchAgent: Send` 超trait + `ensure_evaluated` 默认方法 |
| `agent/batchify.rs` | 泛型补 `Send` 约束 |
| `arena/game.rs` | `commit` 阶段：每回合 4 个 agent 的评估用 `std::thread::scope` **并行**执行（各自独立会话互不干扰），打破单桌串行墙 |

### 验证

1. **数值等价**：固定种子（777~779）× 4 模型 × 3 seed = 12 局，新旧 pyd 逐局
   名次与素点**逐位一致（12/12）**；并行评估版 vs 串行版再次 **12/12 一致**。
2. **确定性**：同种子跨 intra 线程级别哈希一致（线程数不影响对局结果）。
3. **吞吐基准**（`bench_ladder.py`，每桌 4 半庄矩阵）：

| 变体 | 聚合吞吐 |
|---|---|
| 独占会话 + intra=1 + 6 桌（**现役**） | **7.76 半庄/分** |
| 共享会话 + intra=2 + 6 桌 | 6.02 |
| 独占 + intra=2 + 6 桌（旧配置） | 2.10 |
| 独占 + intra=2 + 10 桌 | 1.73（过订阅崩溃） |

单会话延迟：batch1 = 14.4ms（intra1）vs 59.0ms（intra2）；真实对局每回合引擎批
仅 4~8 obs，故 **intra=1 全面优于 2**；10 桌为 18 核过订阅上限。

## 七、已知限制与后续

1. 单桌内部回合循环仍为串行（每回合 4 次评估现已并行，但回合之间必须顺序），
   单桌吞吐上限 ≈ 1~4 半庄/分；聚合吞吐靠桌数线性扩展（当前 6 桌 ≈ 5~8 半庄/分）。
2. 四项细 stats（和率/放铳率/副露率/立直率）未接入：UI 端可空显示；
   后续可用 libriichi stat 模块从采样 mjai 日志补齐。
3. `keqing1-workbench` 原版 `server.py` 依赖私有包 keqing_core，本包以契约等价的
   `ladder_api_server.py` 替代；keqing_core 可用后可直接换回原版 server。

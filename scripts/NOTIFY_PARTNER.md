# 告知：Atozuke 天梯自弈竞技场已落地（新增 libriichi 补丁 + 榜单接入）

致合作开发者：

Atozuke 机器上的「天凤四卓分层天梯自弈竞技场」已完成部署并常驻运行。本次提交
新增 `scripts/atozuke_arena/`（完整 CPU 竞技场）与 `third_party/libriichi-rs/`
（打完补丁的 libriichi 完整源码），请重点审阅后者——它包含 5 个文件的共享
Rust 代码变更。

---

## 一、本次新增内容

| 路径 | 内容 |
|---|---|
| `scripts/atozuke_arena/` | 天梯主运行器 + 引擎 + 配置 + UI 转换器/API + 基准台 + 运维脚本 + README |
| `third_party/libriichi-rs/` | **完整可编译**的 libriichi crate（含 5 文件补丁，见下） |

天梯规格：30 席 Avatar（5 冲顶主力 / 9 特凤升降机 / 16 特上原住民）、凤凰-特上-
上级三卓自动升降、官方算分（四位 −(15D+30)、十段 4000PT 晋天凤位）、6 桌并行、
断点续跑、单实例守卫。数据落 Atozuke 本地 SQLite，实时导出榜单 JSON。

## 二、需要你关注的三件事

### 1. `third_party/libriichi-rs/` 是共享 Rust 代码的实质变更

5 个文件的修改（详见 `scripts/atozuke_arena/README.md` 第六节）：

- `agent/mortal.rs` + `arena/mortal_onnx.rs`：**ONNX 推理移出 GIL**。
  原实现 `native.infer()` 在 `Python::with_gil` 闭包内执行，多桌并发时全部
  推理被 GIL 串行化（18 核机器实测仅用 1.6~3.9 核）。现改为 GIL 内仅提取
  `Arc<Mutex<Session>>` 句柄，推理与锁等待都在 GIL 之外。
- `arena/game.rs`：`commit` 阶段 4 个 agent 的评估用 `std::thread::scope`
  并行执行（各 agent 独立会话，互不干扰）——打破单桌串行墙。
- `agent/defs.rs` / `agent/batchify.rs`：`BatchAgent: Send` 超trait 及配套。

**如果你的构建流程引用同一 crate，请同步这些变更**；`Session` 由
`Mutex<Session>` 变为 `Arc<Mutex<Session>>` 是接口级变化（`infer` 抽为
自由函数 `infer_batch`）。另新增 `infer_direct` pymethod 供基准测试调用。

### 2. 数值等价性已验证

固定种子（777~779）× 4 模型 × 3 seed = 12 局：补丁前后逐局名次与素点
**逐位一致（12/12）**；并行评估版 vs 串行版再次 12/12 一致。同种子跨
线程数（intra 1/2）哈希一致。调度变更不影响任何对局结果。

### 3. 榜单数据契约未变，新增了生产者

`export_ladder_for_workbench.py` 产出的三件套（`account_summary.json` /
`account_ledger.jsonl` / `rating_curve.csv`）+ 赛季注册表与你现有的
`workbench/replay/ladder.py` 加载器**完全兼容**（schema
`keqing.ladder.season.v1` / `...report.v2`）。四项细 stats
（和率/放铳率/副露率/立直率）暂为 null，UI 端 null-safe。

另有 `ladder_api_server.py`：因原版 `server.py` 依赖私有包 keqing_core
（keqing-mortal 仓库未公开），我们按相同 HTTP 契约实现了轻量只读版
（4 个 GET 端点 + SPA 静态），已部署 Atozuke:28787。keqing_core 可用后
可直接换回原版 server.py，三件套无需任何改动。

## 三、性能数据（Atozuke 18 核 CPU 实测）

| 变体 | 聚合吞吐 |
|---|---|
| 修复前（GIL 内推理，6 桌） | ~1.6 半庄/分（CPU 仅 1.6~3.9 核） |
| **修复后（GIL 外 + 回合内并行评估，6 桌）** | **~5-8 半庄/分（CPU 7.8 核）** |

完整基准矩阵（6 变体 × 确定性校验）见 README 第六节，复现命令：
`python C:\arena\ladder\bench_ladder.py`。

## 四、兼容性与回滚

- 平台：Windows / Python 3.13 / ort 2.0.0-rc.12（CPU EP）；无 CUDA 依赖
- 旧混池（`pool_arena.py` + `pool_results.db`）**零改动**，计划任务仅停用
  未删除，回滚 = 停新任务 + 重新启用旧任务
- libriichi 旧版 pyd 备份于 Atozuke `C:\arena\pyd_native\libriichi_gil_backup.pyd`

有问题随时沟通，也欢迎直接在分支上 review。

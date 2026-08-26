# MortalSim 架构

MortalSim 是仅监听本机回环地址的 Web 桌面应用。Windows 启动器选择空闲端口，
启动 FastAPI 服务并打开浏览器；前端静态资源、模拟服务和用户数据均留在本机。

## 运行路径

```text
React / TypeScript UI
        |
        | REST + SSE
        v
FastAPI / JobManager
        |
        | multiprocessing worker
        v
SimulationService
        |                         |
        | continuous buffers      | runtime identity
        v                         v
Rust CustomKyokuRunner     Formal Lite CUDA runtime
        |                         |
        +---- legal mask ---------+---- raw advantage [B, 46]
                                  |
                                  v
                      Rust stable action selector
```

- `JobManager` 创建、取消和恢复运行与扩容任务，并将进度及 GPU 采样转换为 SSE。
- `SimulationService` 校验局面，调用 Rust 对局核心和原生 CUDA 推理运行时。
- `StatisticsService` 聚合五类终局、局收支、役种、置信区间及配对比较。
- 结果以 schema v3 JSON 原子写入 `%LOCALAPPDATA%\MortalSim\runs`。

## 正式决策契约

公开 Lite 使用 `stable_advantage_v2`。AOTInductor CUDA 图固定为 SM89、容量
1024，接收 Mortal v4（256 channels / 54 blocks）权重并返回原始 advantage。
合法动作的选择、并列规则和和牌守卫均由 Rust 实现。公开 Batch 固定为 1000，
不足容量的行在固定图内补零并全部屏蔽。

运行结果保存模型 SHA256、原生图及运行时 SHA256、build ID、GPU compute
capability、Batch 和精度配置。扩容只有在这些身份完全一致时才允许合并。

`legacy_amp_v1` 只属于安装 PyTorch 的开发精度实验室，不包含在公开 Portable，
也不与正式 Lite 结果合并。schema v1/v2 历史仅只读，可复制局面重新运行成
schema v3，但不会被隐式迁移。

## 分发边界

Portable ZIP 包含应用、Rust 扩展、前端静态资源、CUDA 运行时和无参数原生图，
不包含 PyTorch、CUDA Toolkit 或模型权重。用户通过设置页导入本机兼容 `.pth`；
导入后生成以 SHA256 标识的不可变副本。服务不会下载或上传模型、手牌和结果。

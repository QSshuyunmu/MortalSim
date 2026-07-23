# MortalSim 架构

MortalSim 是本地 Web 桌面应用：启动器运行 FastAPI 服务并打开浏览器，`JobManager` 管理任务生命周期，`SimulationService` 将请求交给独立 multiprocessing Worker，`StatisticsService` 负责版本化结果封装。Worker 调用现有 Rust `CustomKyokuRunner` 和 Python AMP 模型。SSE 将进度和 GPU 状态推送到页面；运行结果以版本化 JSON 保存到用户数据目录。

正式推理仍使用 Python AMP。ONNX 路径在严格逐局一致性通过前不会作为默认引擎。

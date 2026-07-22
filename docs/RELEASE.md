# 发布流程

1. 确认模型授权、许可证和 `MODEL_MANIFEST.json`。
2. 将授权模型放在 `Akagi/model_v4_20240308_best_min.pth`，并在安装 CUDA 版 PyTorch 且 GPU 可用的 Windows x64 环境执行 `packaging/build_windows.ps1`。没有模型时只能使用 `-AllowMissingModel` 生成诊断包。
3. 验证 CUDA、无写权限目录、路径含空格和取消任务。
4. 运行固定 100 seed smoke test，并核对旧版 trace。
5. 创建 `v0.x.y` tag，上传 CUDA ZIP 和 SHA256SUMS 到 GitHub Release。
6. 首个版本使用 pre-release，外部验证后再标记稳定版。

# 发布流程

1. 确认公开仓库、Release 资产、文档和发布说明均不含权重文件、权重下载链接或权重来源。
2. 在安装 CUDA 版 PyTorch 的 Windows x64 环境执行 `packaging/build_windows.ps1`。它只生成不含模型的 Core + Runtime 分卷。
3. 运行 `packaging/verify_release.ps1`，确认每个 Release 资产均小于 2 GiB、SHA256SUMS 完整、Core 含法律文件和 SBOM。
4. 在干净 Windows 环境解压 Core 和全部 Runtime 分卷，双击 `Start-MortalSim.cmd`；导入模型后运行固定 100 seed GPU smoke，并核对旧版 trace。
5. 使用 `packaging/prepare_public_repo.ps1` 生成无历史、无权重、无本机构建产物的公开仓库；配置公开提交身份后再创建首个 commit。
6. 创建语义化 pre-release tag，上传 Core、全部 Runtime、`SHA256SUMS.txt` 与 release notes。外部验证后再标记稳定版。

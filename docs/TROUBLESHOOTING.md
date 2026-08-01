# 故障排查

## 页面没有打开

确认已完整解压并通过 `Start-MortalSim.cmd` 启动，检查安全软件是否隔离了 `_internal` 中的 DLL。手动打开启动器日志中的 `127.0.0.1` 地址。仍失败时从 PowerShell 运行 `MortalSim.exe` 并保留完整错误文本。

## CUDA 不可用

先运行 `nvidia-smi`，再查看诊断页的 Compute Capability。v0.3 Formal Lite 只接受 `8.9`（RTX 40），且不会使用 CPU 或 PyTorch 回退。更新 NVIDIA 驱动后重启；不要为 Portable 额外安装 `requirements-lock.txt` 或 CUDA Toolkit。

## Formal Lite 不可用

诊断页会分别报告缺失文件、SHA 不匹配、ABI 不一致、非 SM89 和 CUDA 初始化失败。不要单独替换 `model.dll` 或任一运行时 DLL；它们必须和 `runtime_manifest.json` 属于同一构建。重新下载 ZIP 并校验 SHA256。

## 模型导入失败

只接受标准 Mortal v4 / 256 channels / 54 blocks `.pth`。受限读取器不会执行权重携带的代码；缺字段、未知 pickle 全局、shape 不符、损坏文件和额外张量都会拒绝。Lite 包不提供模型下载地址，也不包含模型。

## 模拟失败

保存运行 ID、错误信息、Build ID、Artifact SHA、GPU/驱动信息和 `%LOCALAPPDATA%\\MortalSim\\logs`，再提交 GitHub Issue。不要上传模型、个人牌谱或敏感文件。

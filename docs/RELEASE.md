# Lite 发布流程

Lite 发布包不包含任何模型权重，构建产物只应包含应用、Rust 扩展、前端静态文件和轻量 CUDA 运行时。模型由用户在应用内导入，并使用 SHA256 作为本地身份。

## 构建

在 Windows x64、已安装 NVIDIA 驱动的构建机上：

```powershell
$env:PYO3_PYTHON = "C:\Path\to\python.exe"
# ArtifactDir 必须包含 mortal_lite_runtime.dll、aoti_cuda_shims.dll、
# cudart64_12.dll 和由固定模型导出的 model.dll
powershell -ExecutionPolicy Bypass -File packaging/build_lite_windows.ps1
```

脚本会构建前端和 `libriichi`，运行 Lite PyInstaller spec，生成 `release/MortalSim-Windows-x64-Lite-v*.zip`、SHA256 文件和 `build/lite-stage/RELEASE_MANIFEST.json`。权重、`.pth`、`.onnx` 不会进入包。正式发布前应在干净 Windows 机器上导入权重并执行固定 seed smoke test。

## 体积与依赖审计

检查压缩包和解压目录大小，确认没有 `torch/`、训练数据、日志、模型或个人路径；确认 `nvidia-smi` 可用且包内 DLL 依赖完整。`packaging/verify_release.ps1` 用于通用发布检查，Lite 构建脚本额外限制压缩包不超过 300 MiB。

## 发布资产

- `MortalSim-Windows-x64-Lite-vX.Y.Z.zip`
- `SHA256SUMS-Lite.txt`
- 发布说明（平台要求、模型导入、已知限制、严格一致性状态）
- `LICENSE`、`NOTICE`、`THIRD_PARTY_LICENSES.md`、`MODEL_LICENSE.md`

Lite 的 AOTI CUDA 图必须以当前 PyTorch AMP 参考引擎做固定 seed 逐局回归；未通过严格动作/trace 等价时，不得在发布说明中声称等价，应保留参考引擎作为可验证路径并明确标注实验状态。

# Formal Lite 发布流程

v0.3 Release 只包含应用、Rust 扩展、前端、SM89 AOT CUDA 图和最小 CUDA 运行时。
不包含或下载任何 `.pth`/`.onnx` 权重，也不包含 PyTorch、训练数据、牌谱和日志。

## 固定环境

- Windows 10/11 x64 构建机，Python 3.13、锁定 MSVC/Rust/Node 版本。
- 精确版本记录在 `tools/lite-toolchain.lock.json`；构建机任何版本漂移都要产生新的
  Build ID 和 Artifact SHA，并重新执行全部 GPU Gate。
- `packaging/lite_runtime` 或 `MORTALSIM_LITE_ARTIFACT_DIR` 必须来自批准的 SM89 构建，
  并含五个文件：`mortal_lite_runtime.dll`、`aoti_cuda_shims.dll`、
  `cudart64_12.dll`、`model.dll`、`runtime_manifest.json`。
- Manifest 必须声明 ABI 2、`stable_advantage_v2`、Batch 1000、容量 1024、SM89，
  且所有文件 SHA 与聚合 Artifact SHA 一致。

## 本地构建

先在锁定的 ExecuTorch/PyTorch 构建环境中生成 SM89 raw-advantage 图，再从 Visual
Studio x64 Native Tools PowerShell 编译最小宿主：

```powershell
python tools/export_mortal_executorch.py `
  --checkpoint D:\models\model-v4.pth `
  --output-dir D:\build\formal-graph `
  --batch 1024 `
  --precision amp-static `
  --output-kind advantage

tools/build_lite_runtime.ps1 `
  -GraphDirectory D:\build\formal-graph `
  -OutputDirectory D:\approved-runtime `
  -CudaRoot $env:CUDA_PATH `
  -BuildId v0.3.0rc1-local
```

图构建使用的 checkpoint 仅用于确定架构和生成可替换常量；批准的 runtime 目录及
Release 都不能复制 `.pth`、`.ptd` 或 `.pte`。`model.dll` 必须允许应用启动时用用户
导入权重覆盖全部 767 个常量。

然后组装 Portable：

```powershell
$env:PYO3_PYTHON = "C:\Path\to\python.exe"
$env:MORTALSIM_LITE_ARTIFACT_DIR = "D:\approved-runtime"
powershell -ExecutionPolicy Bypass -File packaging/build_lite_windows.ps1
```

脚本执行前端构建、release Rust 扩展、libtorch-free PyInstaller onedir、法律文件和
SBOM 组装，最后输出：

```text
release/MortalSim-Windows-x64-Lite-v0.3.0-rc.1.zip
release/SHA256SUMS-Lite.txt
release/SBOM.cdx.json
release/LITE_VALIDATION-v0.3.0-rc.1.json
```

ZIP 必须不超过 300 MiB，解压不超过 700 MiB。

## 包验收

```powershell
powershell -ExecutionPolicy Bypass -File packaging/verify_release.ps1 `
  -ReleaseDirectory release
```

随后在无 Python/Rust/CUDA Toolkit 的干净 Windows 机器上：

1. 校验 `SHA256SUMS-Lite.txt` 后完整解压。
2. 启动 `Start-MortalSim.cmd`，调用 `/api/health` 和 `/api/capabilities`。
3. 确认 Formal Lite Ready、Compute Capability 8.9 和 Artifact SHA。
4. 导入用户自备兼容权重，运行固定 seed 1000 局 smoke。
5. 检查取消、后台扩容、重启恢复、导出和中文路径。
6. 扫描 ZIP，确认无 `.pth`、`.onnx`、日志、绝对个人路径、token 或开发工具链。

## 发布门槛

Source CI、固定构建机和两台 RTX 40 GPU Gate 必须全绿。当前
`LITE_VALIDATION-v0.3.0-rc.1.json` 中任一 `pending` 为 `true` 时，只能发布 RC，
不能创建最终 `v0.3.0` tag。旧 `v0.2.0-alpha.0` tag/分支不得覆盖。

Release 说明必须写明平台、GPU/驱动、模型不随包发布、决策契约、模型与运行时身份、
已知限制、安装/卸载和许可证。最终资产另附 `SHA256SUMS-Lite.txt`、SBOM 与验证 JSON。

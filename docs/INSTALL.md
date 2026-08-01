# MortalSim Lite 安装与使用

## 运行要求

- Windows 10/11 x64
- NVIDIA RTX 40 系列 GPU（Compute Capability 8.9）与正常工作的 NVIDIA 驱动；应用只监听 `127.0.0.1`
- 不需要安装 Python、Rust、Visual Studio、PyTorch 或 CUDA Toolkit
- Lite 包不包含模型权重。需要自行准备兼容的 Mortal v4 权重（256 channels、54 blocks、`.pth`）

## 安装

1. 从 GitHub Release 下载 `MortalSim-Windows-x64-Lite-*.zip`。
2. 用 Windows 资源管理器“全部解压”，不要直接在压缩包内运行。
3. 解压路径可以包含空格或中文，但建议使用有写权限的普通目录。
4. 双击 `Start-MortalSim.cmd`。它会检查文件完整性，然后启动 `MortalSim.exe`。
5. 首次打开后进入“设置与诊断”，点击“导入权重”，选择本机 `.pth` 文件。
6. 诊断页必须同时显示 `Formal Lite ready`、Compute Capability `8.9`、运行时 Build ID 和 Artifact SHA256。
7. 导入完成后，在“新建分析”中选择模型，填写局面和候选第一打，开始模拟。

模型会复制到 `%LOCALAPPDATA%\MortalSim\models`，原始下载文件可以移走。运行记录写入 `%LOCALAPPDATA%\MortalSim\runs`，不会写入解压目录，也不会上传任何数据。

## GPU 检查

在 PowerShell 执行 `nvidia-smi`。如果命令不存在、驱动不可用、显卡被系统禁用或计算能力不是 8.9，应用会在诊断页给出原因；Lite 不会静默回退到 CPU。`nvidia-smi` 顶部显示的“CUDA Version”是驱动可支持版本，不表示需要另装 Toolkit。Lite 包自带所需 CUDA 运行时 DLL。

## 开发运行

```powershell
$env:PYO3_PYTHON = "C:\Path\to\python.exe"
python -m pip install -r requirements-lock.txt
python -m pip install -r requirements-test.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
python run_mortalsim.py
```

开发模式默认使用 `stable_advantage_v2` Lite。旧 `legacy_amp_v1` 只用于精度实验室，需要本机安装锁定的 PyTorch CUDA 环境；公开 Portable 不包含也不暴露该引擎。

## 卸载

删除解压目录即可。若要删除模型、历史和日志，再删除 `%LOCALAPPDATA%\MortalSim`。

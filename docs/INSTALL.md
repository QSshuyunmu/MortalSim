# MortalSim 安装

## 开发运行

```powershell
python -m apps.desktop_launcher.main
```

或双击仓库根目录的 `start_mortalsim.bat`。程序会启动本地 API 并打开浏览器。

## Portable 版本

从 GitHub Releases 下载 Windows x64 CUDA ZIP，解压后双击 `MortalSim.exe`。
安装目录不保存运行结果；结果默认写入 `%LOCALAPPDATA%\\MortalSim`。

## CUDA

CUDA 包需要兼容的 NVIDIA 驱动和 CUDA 版 PyTorch。MortalSim 是 GPU 专用应用，CUDA 初始化失败时不会回退到 CPU；请根据设置页诊断信息修复驱动或运行时。

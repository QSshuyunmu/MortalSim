# MortalSim 安装

## 开发运行

```powershell
python -m apps.desktop_launcher.main
```

或双击仓库根目录的 `start_mortalsim.bat`。程序会启动本地 API 并打开浏览器。

## Portable 版本

从 GitHub Releases 下载对应的 Windows x64 CPU 或 CUDA ZIP，解压后双击 `MortalSim.exe`。
安装目录不保存运行结果；结果默认写入 `%LOCALAPPDATA%\\MortalSim`。

## CUDA

CUDA 包需要兼容的 NVIDIA 驱动。CUDA 初始化失败时可在设置页确认环境并切换 CPU 模式。

# MortalSim 安装

## 开发运行

```powershell
python -m apps.desktop_launcher.main
```

或双击仓库根目录的 `start_mortalsim.bat`。程序会启动本地 API 并打开浏览器。

## Portable 版本

从同一个 GitHub Release 下载 `Core` 和全部 `Runtime-XX` CUDA ZIP，将它们全部解压到同一目录，再双击 `Start-MortalSim.cmd`。启动脚本会检查 CUDA 运行时是否完整。

公共包不附带、托管或下载模型权重。首次打开后，在“设置与诊断”中导入本机已有的兼容 `.pth` 文件。安装目录不保存运行结果；结果默认写入 `%LOCALAPPDATA%\\MortalSim`。

## CUDA

CUDA 包需要兼容的 NVIDIA 驱动和 CUDA 版 PyTorch。MortalSim 是 GPU 专用应用，CUDA 初始化失败时不会回退到 CPU；请根据设置页诊断信息修复驱动或运行时。

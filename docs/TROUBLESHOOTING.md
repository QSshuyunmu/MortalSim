# 故障排查

## 页面没有打开

确认 `MortalSim.exe` 没有被安全软件拦截，并手动打开启动器日志中的 `127.0.0.1` 地址。

## CUDA 不可用

在设置页查看 Python、模型、`nvidia-smi` 和 CUDA 状态。MortalSim 仅支持 GPU；请安装 `requirements-cuda.txt`，确认 `torch.version.cuda` 非空且 `torch.cuda.is_available()` 返回 `True`。

## 模拟失败

保存运行 ID、错误信息和 `%LOCALAPPDATA%\\MortalSim\\logs`，再提交 GitHub Issue。不要上传模型、个人牌谱或敏感文件。

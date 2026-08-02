MortalSim Lite 本机自包含版
============================

双击 Start-MortalSim.cmd 或 Start-MortalSim-Local.cmd 启动。不要直接运行
MortalSim.exe，因为启动脚本负责启用同目录的数据目录。

此目录已经包含一份本机模型副本，并将模型、历史结果、日志和缓存固定写入
同目录下的 data 文件夹，不依赖源码仓库，也不会使用 %LOCALAPPDATA% 中的
另一套 MortalSim 数据。

请勿将此目录、其中的 data/models 或任何 .pth 文件上传到 GitHub 或公开发布。
公开 Release 不包含模型权重。

可以整体移动或备份本目录。删除本目录即删除这套本机版及其运行历史。

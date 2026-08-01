# MortalSim Lite

MortalSim Lite 是一个只在 Windows 本机运行的日麻自亲第一打模拟与比较工具。
它使用 Rust `libriichi` 模拟核心和精简 CUDA 推理图，适合希望在不安装 Python、
Rust 或 CUDA Toolkit 的情况下运行 GPU 模拟的用户。

> 当前 Lite 原生 CUDA 图仍处于 alpha 验证阶段。正式对照以 PyTorch AMP Reference
> 为准；固定 seed 严格一致性尚未通过时，请不要把 Lite 与 Reference 的细微差异
> 解释为模型决策已经完全相同。

## 运行前确认

- Windows 10/11 x64。
- NVIDIA 显卡和正常工作的驱动。先在 PowerShell 运行 `nvidia-smi`，能看到显卡、
  驱动版本和显存即可；不需要安装 CUDA Toolkit。
- 至少约 100 MiB 的解压空间，运行时还需要模型文件和结果目录空间。
- 一个与 Mortal v4（256 channels、54 blocks）兼容的 `.pth` 权重。Lite 包不包含、
  不下载也不代分发模型权重，用户需要自行确认权重的来源和使用许可。

## 安装与首次启动

1. 从 GitHub Releases 下载 `MortalSim-Windows-x64-Lite-*.zip`，同时下载同目录的
   `SHA256SUMS-Lite.txt`。
2. 在 PowerShell 中校验压缩包（把路径替换成实际文件）：

   ```powershell
   Get-FileHash .\MortalSim-Windows-x64-Lite-*.zip -Algorithm SHA256
   ```

   将输出与 `SHA256SUMS-Lite.txt` 对比。校验失败时不要解压或运行。
3. 将 ZIP 解压到有写权限的普通目录，例如 `D:\Apps\MortalSimLite`。不要直接在
   `C:\Program Files` 下运行，也不要只打开 ZIP 内的文件。
4. 双击 `Start-MortalSim.cmd`。它会启动本地服务并打开浏览器；服务只监听
   `127.0.0.1`，不会把手牌、seed、模型或结果上传到网络。
5. 如果浏览器没有自动打开，手动访问终端中显示的 `http://127.0.0.1:<端口>`。
6. 首次打开“设置与诊断”，选择“导入模型”，导入兼容的 `.pth`。程序会检查 Mortal
   架构、SHA-256 和一次 CUDA 前向；通过后模型副本保存到
   `%LOCALAPPDATA%\MortalSim\models`，以后不依赖原下载路径。

## 第一次分析

1. 打开“新建分析”。输入 14 张牌的字符串，最后一张固定作为第一摸；例如
   `4567m3477p134066s`。不要再单独填写第一摸。
2. 填写宝牌指示牌，并选择一个或多个候选第一打。牌面预览出现后再开始模拟。
3. 选择局目、四家点数、本场、供托、模拟局数和 seed。需要可复现的候选比较时，
   保持固定 seed，让所有候选使用同一个 seed 区间。
4. 点击“开始模拟”。运行页会显示候选进度、吞吐、错误数、GPU 温度、利用率和显存。
   可在后台任务抽屉中切换到历史记录；取消只会保留取消状态，不会伪装成完整结果。
5. 在结果页先看推荐第一打、平均局收支、95% CI 和配对差值，再查看五类终局、顺位、
   和了构成、防守、立直、听牌、副露、役种和稳定性曲线。

## 历史与导出

- 已完成的 schema v2 分析可以使用“增加相同模拟局数”扩容。扩容继承原手牌、规则、
  seed 起点、模型和候选；任务在后台运行，可随时取消，只有所有候选成功后才原子合并。
- 结果页的“下载全量数据”提供三种格式：JSON、Excel 和离线 HTML。三种格式均只包含
  当前界面总表中的全部统计指标，不额外打包日志、模型或原始牌谱。
- 运行历史、模型副本、GPU 采样和导出文件保存在 `%LOCALAPPDATA%\MortalSim`，
  不写入安装目录。删除历史不会删除模型库。

## 常见问题

### 显示 CUDA 不可用

确认 `nvidia-smi` 能工作，关闭占用显存异常的程序后重启 MortalSim。Lite 是 GPU-only，
不会静默回退 CPU；如果驱动过旧，请更新 NVIDIA 驱动而不是安装 CUDA Toolkit。

### 模型导入失败

Lite 只接受标准 Mortal v1–v4 state-dict，首发包重点支持 v4、256 channels、54 blocks。
检查文件完整性、扩展名是否为 `.pth`，并确认权重来源允许在本机使用。损坏或未知架构
不会加入模型库。

### 牌面不显示

确认没有从 ZIP 内直接运行，重新完整解压并启动 `Start-MortalSim.cmd`。应用资源位于
`_internal` 和前端静态目录，不能只复制 `MortalSim.exe` 单文件。

### 如何报告问题

请附上应用版本、Windows 版本、GPU 与驱动版本、复现步骤、完整错误文本以及
`%LOCALAPPDATA%\MortalSim\logs` 中相关日志。不要上传模型权重、个人牌谱或包含密钥的文件。

## 安全与许可

MortalSim 是离线分析工具，不连接麻将客户端、不拦截网络流量、不自动操作线上对局。
应用代码采用 AGPL-3.0-or-later；CUDA runtime、第三方依赖和模型权重可能有单独条款，
请阅读 `NOTICE`、`THIRD_PARTY_LICENSES.md` 和 `MODEL_LICENSE.md`。发布包不包含模型权重。

界面截图：

![分析台](docs/images/analysis-workbench.png)
![候选结果比较](docs/images/result-comparison.png)
![结果图表](docs/images/result-charts.png)

# MortalSim

[English](README.md) | **简体中文**

<p align="center">
  <img src="apps/web/public/mascot.webp" alt="MortalSim 原创红蟹吉祥物" width="160">
</p>

MortalSim 是一款在 Windows 本机运行的日麻第一打模拟与比较工具。它使用
Rust `libriichi` 模拟核心和 Python AMP 模型，对多个候选第一打使用相同
seed 进行配对模拟，帮助用户比较平均局收支、终局分布与详细攻防指标。

所有手牌、seed、模型、GPU 状态和模拟结果都只保存在本机。MortalSim
不会连接麻将客户端、拦截网络流量或自动操作线上对局。

## 功能

- 多个候选第一打的固定 seed 配对比较
- NAGA 口径平均局收支、95% 置信区间和配对差值
- 自家和牌、自家放铳、流局、横移动、他家自摸五类互斥终局
- 顺位、和牌构成、防守、立直、听牌、副露和役种统计
- 后台任务、GPU 温度/利用率/显存监测和随时取消
- 历史结果保存，以及使用连续 seed 原子追加模拟局数
- 本地 `.pth` 模型导入、SHA-256 身份记录和 CUDA 自检
- Excel 全量指标表、完整 JSON 和离线 HTML 导出

## 界面预览

### 分析台

![MortalSim 分析台](docs/images/analysis-workbench.png)

### 候选结果比较

![MortalSim 候选结果比较](docs/images/result-comparison.png)

### 终局、顺位与稳定性图表

![MortalSim 结果图表](docs/images/result-charts.png)

## 系统要求

- Windows 10 或 Windows 11 x64
- NVIDIA GPU
- 与随包 CUDA 12.4 运行时兼容的 NVIDIA 驱动
- 解压后约 4 GiB 可用磁盘空间
- 用户自行提供的兼容 Mortal `.pth` 模型

MortalSim 是 GPU 专用应用，不会在 CUDA 不可用时静默回退到 CPU。

## 从下载到完成第一次分析

下面的流程不需要安装 Python、Rust、CUDA Toolkit 或 Node.js。

### 第一步：确认显卡和驱动

按 `Win + R`，输入 `powershell` 并回车，然后运行：

```powershell
nvidia-smi
```

能够看到 NVIDIA 显卡名称、驱动版本、温度和显存，说明系统已经识别显卡。
如果命令不存在或报告驱动错误，请先从 NVIDIA 官方渠道更新驱动。这里显示的
“CUDA Version”是驱动能够支持的最高 CUDA 版本，不要求用户另外安装 CUDA
Toolkit。

### 第二步：下载完整的 Portable 包

打开 [Releases](https://github.com/QSshuyunmu/MortalSim/releases)，进入同一个
版本的 Release。必须下载以下五个文件：

```text
MortalSim-Windows-x64-CUDA-Core-<版本>.zip
MortalSim-Windows-x64-CUDA-Runtime-01-<版本>.zip
MortalSim-Windows-x64-CUDA-Runtime-02-<版本>.zip
MortalSim-Windows-x64-CUDA-Runtime-03-<版本>.zip
SHA256SUMS.txt
```

不要下载 GitHub 自动生成的 `Source code (zip)` 代替 Portable 包。源码包不含
可直接启动的 Windows CUDA 运行时。

所有 ZIP 必须来自同一个版本。不同版本的 Core 和 Runtime 不能混用。

### 第三步：校验下载文件

在下载目录打开 PowerShell，运行：

```powershell
Get-FileHash .\MortalSim-Windows-x64-CUDA-*.zip -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

逐个确认 PowerShell 显示的哈希与 `SHA256SUMS.txt` 相同。哈希不一致时不要
继续使用该文件，应删除后重新下载。

### 第四步：解压到同一个目录

新建一个具有写入权限的普通文件夹，例如：

```text
D:\Apps\MortalSim\
```

依次打开四个 ZIP，将它们的全部内容解压到这个同一个文件夹。出现“合并目录”
时选择允许；正常情况下文件之间不会互相覆盖成不同内容。

解压完成后，目录顶层至少应看到：

```text
MortalSim\
├─ Start-MortalSim.cmd
├─ Install-MortalSim.ps1
├─ MortalSim.exe
├─ RELEASE_MANIFEST.json
├─ _internal\
└─ legal\
```

不要只解压 Core。`Start-MortalSim.cmd` 会依据发布清单检查 Runtime 分卷，
缺少文件时会列出缺失项。

### 第五步：启动应用

双击：

```text
Start-MortalSim.cmd
```

启动脚本会检查文件完整性、运行 `MortalSim.exe`、选择一个空闲本地端口，
然后打开形如 `http://127.0.0.1:xxxxx/` 的页面。第一次启动因为安全软件扫描
大型 CUDA 运行时，可能比之后启动更慢。

MortalSim 只监听 `127.0.0.1`，同一局域网中的其他设备无法访问。浏览器只是
应用界面，关闭浏览器标签不会删除任务或历史数据。

启动失败时先查看：

```text
%LOCALAPPDATA%\MortalSim\logs\launcher.log
```

也可以重新双击 `Start-MortalSim.cmd`，命令窗口会提示缺失 Runtime 或 CUDA
初始化错误。

### 第六步：导入本地模型

MortalSim 的源码和 Release 都不包含模型权重。首次启动必须导入用户本机已有
的兼容 Mortal `.pth` 文件：

1. 点击左侧“设置与诊断”。
2. 确认页面显示“CUDA 就绪”。
3. 点击“导入 .pth”并选择模型文件。
4. 等待模型结构校验、严格参数加载和 CUDA AMP 前向自检。
5. 看到模型状态为“可用”后返回“分析台”。
6. 在“推理模型”下拉框中选择该模型。

导入时应用会把权重复制到 `%LOCALAPPDATA%\MortalSim\models`，之后不依赖原
文件路径。模型只保存在本机，不会上传。重复导入相同文件会依据 SHA-256
识别为同一个模型。

### 第七步：输入局面

“局面”区域填写：

- **局目**：东一局至西四局，当前版本固定自家为庄家。
- **本场**：默认 0。
- **供托**：默认 0。
- **点数**：填写自家、下家和对面，上家由应用自动计算。

点数必须为非负的 100 点整数倍，并满足：

```text
四家点数之和 + 供托 × 1000 = 100000
```

校验状态变为绿色后才能开始模拟。

### 第八步：输入手牌、宝牌和候选

手牌字符串必须恰好表示 14 张牌，最后一张固定视为第一摸。例如：

```text
4567m3477p134066s
```

牌的记号：

| 记号 | 含义 | 示例 |
| --- | --- | --- |
| `m` | 万子 | `123m` |
| `p` | 筒子 | `456p` |
| `s` | 索子 | `789s` |
| `z` | 字牌，依次为东南西北白发中 | `1234567z` |
| `0m` / `0p` / `0s` | 赤五 | `0p` |

宝牌指示只输入一张牌，例如 `9s`。

候选第一打可以用英文逗号、中文逗号或空格分隔：

```text
1s, 6s
```

也可以直接点击下方真实牌面加入或移除候选。候选必须存在于当前 14 张牌中。
如果配牌已经听牌，可以点击候选旁的“立”，表示第一打打出该牌并宣告立直。

### 第九步：设置模拟参数

- **模拟局数**：每个候选分别运行的局数，不是所有候选合计。
- **固定 seed 严格比较**：建议保持开启，让候选使用完全相同的随机 seed。
- **Seed**：位于“高级设置”，相同模型、版本、Batch 和 seed 可用于复现。
- **Batch**：越大通常吞吐越高，但显存占用也更高。
- **Rayon 线程**：控制 Rust CPU 并行线程，默认值适合当前基准机器。

第一次验证配置时可以先运行 100 局。正式比较建议至少运行 1000 局，并结合
95% 置信区间判断差异是否已经稳定。

### 第十步：运行与后台查看

点击“开始模拟”。运行期间可以看到：

- 当前候选、已完成局数和总局数
- 预计剩余时间和吞吐
- 错误局数
- GPU 温度、利用率、显存和功耗
- 当前模型、Batch、推理后端和 Rayon 线程数

任务开始后可以切换到历史页面查看其他记录。右上角“任务”入口始终保留后台
任务状态，也可以从那里取消。取消任务不会把不完整结果伪装成成功记录。

### 第十一步：阅读结果

结果页顶部先回答三个问题：

1. 当前样本推荐哪个第一打。
2. 它与参考候选平均相差多少局收支。
3. 配对差值的 95% 置信区间是否跨过 0。

“尚不明确”表示置信区间仍跨过 0。此时样本中的领先不等于已经确认的优势，
可以增加模拟局数继续观察。

总表和图表包括：

- NAGA 口径平均局收支、均值 CI 和同 seed 配对差值
- 平均终局顺位及 1 至 4 位率
- 自家和牌、自家放铳、流局、横移动、他家自摸
- 自家荣和与自家自摸细分
- 立直、副露、默听、听牌和防守指标
- 平均和牌点、素点、翻数、符数和放铳损失
- 55 槽位役种频率
- 终局、顺位、配对差值、样本稳定性和役种图表

每个完成局只进入一种终局类别。错误局单独记录，不进入终局分布。

### 第十二步：增加局数

对于当前统计协议的成功历史结果，可以点击“增加局数”：

1. 输入新增局数和本次 Batch。
2. 提交后弹窗立即关闭，扩容转为后台任务。
3. 可以继续浏览其他结果，并从“任务”抽屉查看或取消。
4. 新 seed 会从原任务已尝试局数之后连续开始。
5. 所有候选成功后才会原子合并到原分析。

取消、崩溃或任何候选失败时，原结果文件完全不变。同一分析不能同时执行两个
扩容任务。

### 第十三步：导出结果

结果页“导出结果”提供：

- **Excel**：当前指标总表出现的全部统计指标，不附加其他工作表。
- **JSON**：完整、版本化的结果协议，适合归档或程序处理。
- **HTML**：包含主要图表和指标表，可在其他电脑离线打开。

### 第十四步：历史、更新与卸载

“历史运行”可以重新打开、扩容或删除本机记录。删除前会要求确认。

更新版本时：

1. 从新的 Release 下载同版本 Core、全部 Runtime 和校验文件。
2. 解压到一个新的空目录，不要把不同版本混在原目录。
3. 启动新版本。用户数据仍从 `%LOCALAPPDATA%\MortalSim` 读取。

卸载应用时关闭 `MortalSim.exe`，然后删除解压目录。若要同时删除导入模型、
历史、日志和设置，再删除：

```text
%LOCALAPPDATA%\MortalSim
```

更深入的统计口径、历史扩容和隐私说明见
[中文使用指南](docs/USER_GUIDE.md)，常见错误见
[故障排查](docs/TROUBLESHOOTING.md)。

## 数据与模型

用户数据默认保存在：

```text
%LOCALAPPDATA%\MortalSim\
├─ config.toml
├─ models\
├─ runs\
├─ logs\
├─ telemetry\
└─ cache\
```

公开源码和 Release 均不包含、托管或下载模型权重。导入的模型会复制到本机
用户数据目录，并且不会上传。具体政策见 [MODEL_LICENSE.md](MODEL_LICENSE.md)。

## 从源码运行

```powershell
python -m pip install -r requirements-lock.txt
python -m pip install -r requirements-test.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
python run_mortalsim.py
```

验证命令：

```powershell
python -m pytest tests mortal_app/test_gpu_monitor.py -q
cargo test -p libriichi --lib
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

## 当前状态

`v0.2.0-alpha.0` 是首个公开预发布版本。正式推理路径为 Python AMP。
ONNX 仍是实验路径，在通过相同 seed 的严格逐局动作一致性验证前不会作为
公开默认引擎。

## 许可证

应用代码使用 AGPL-3.0-or-later。依赖、模型和 CUDA 运行时可能适用不同条款，
请同时阅读 [NOTICE](NOTICE)、[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)
和 [MODEL_LICENSE.md](MODEL_LICENSE.md)。

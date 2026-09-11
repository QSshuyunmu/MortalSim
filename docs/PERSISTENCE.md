# MortalSim-Bot 持久化与自愈架构

> 目标：**开机即起、挂了自愈、重启后免扫码**。任何一环失效都要能在日志里定位。
> 本文档描述的即线上落地配置，改完请同步 `bot/` 镜像目录。

## 一、四层守护结构

```
┌─ 第 1 层：Windows 计划任务 MortalSimBotAutoStart ─────────────────────┐
│  触发：开机(AtStartup) + 用户登录(AtLogOn)；Principal=当前用户/最高权限  │
│  电源策略：允许电池启动、电池时不停止、不限时(ExecutionTimeLimit=0)      │
│  失败重试：RestartCount=3 / RestartInterval=1min，StartWhenAvailable    │
│  动作：powershell -File start_all_services.ps1                          │
└────────────────────────────────────────────────────────────────────────┘
                                  │
┌─ 第 2 层：start_all_services.ps1（编排 / 幂等启动）────────────────────┐
│  1) 清理旧实例（cmdline 过滤 + PID 落盘文件兜底）                       │
│  2) MortalSim 后端 50715（已有监听则跳过）                              │
│  3) NapCat OneBot 5700/5701 → 调用 scripts/start_napcat.ps1 -Wait       │
│  4) 启动 src/daemon.py（务必绝对路径，见"历史缺陷"）                    │
│  5) 等后端就绪后打印 READY daemon/bot/ports 汇总                        │
└────────────────────────────────────────────────────────────────────────┘
                                  │
┌─ 第 3 层：src/daemon.py（Guardian，全局单例 Win32 命名互斥体）─────────┐
│  · bot.py     ：进程存在 + data/bot.heartbeat 心跳新鲜（默认 90s 超时） │
│  · 后端 50715 ：TCP 端口探测，每 15s；无监听且无残留进程则重启           │
│  · NapCat 5701：TCP 端口探测，每 20s；见"NapCat 自愈策略"               │
│  · 事件写入 logs/daemon.log，PID 落盘 data/daemon.pid                   │
└────────────────────────────────────────────────────────────────────────┘
                                  │
┌─ 第 4 层：组件自身 ────────────────────────────────────────────────────┐
│  bot.py  ：OneBot WS 断线 3s 重连；每 10s 写 data/bot.heartbeat         │
│  NapCat  ：本地快速登录票据 → 密码回退 → 二维码（三级登录兜底）          │
└────────────────────────────────────────────────────────────────────────┘
```

## 二、NapCat 掉线自愈策略（防"打扰扫码"）

守护进程对 NapCat 的判定不是简单的"端口没了就重启"，否则会把用户**正在扫码**的会话杀掉：

| 观测状态 | 判定 | 动作 |
| --- | --- | --- |
| 5701 在监听 | 健康 | 无（恢复时清零重试计数） |
| 5701 断 + QQ 进程**还活着** | 大概率正在扫码/登录中 | **宽限 300s**，只告警不重启 |
| 5701 断 + QQ 进程**已消失** | 崩溃 | 立即重启（受冷却约束） |
| 重启失败 | — | 冷却 180s；连续 3 次失败后进入 900s 长退避 |

重启动作统一交给 `scripts/start_napcat.ps1 -Force -Wait`，该脚本是**启动 NapCat 的唯一入口**（编排脚本与守护进程共用，避免两份实现行为漂移）。

脚本要点：
- 杀掉 QQ/NapCat 后**等待端口真正释放**再启动，并等到 `get_login_info` 真的返回本机 QQ 号才算就绪（只看端口会误判：旧进程退出瞬间端口可能仍在 LISTEN，而且 **5701 是 WebSocket 服务，对它发 HTTP POST 会返回 426**，必须探 5700）。
- 退出码/标记：`NAPCAT_ALREADY_RUNNING` / `NAPCAT_READY` / `NAPCAT_QR_REQUIRED <png>` / `NAPCAT_LOGIN_PENDING` / `NAPCAT_FAILED`。
- 若端口在听但未登录，返回 `NAPCAT_LOGIN_PENDING` 且**不做任何变更**。

## 三、免扫码登录（NAPCAT_QUICK_PASSWORD）

NapCat 的登录顺序是：**本地快速登录票据 → 密码回退 → 二维码**。
票据会过期（过期日志：`自动快速登录失败: 登录态已失效`），此时若不配密码就必须人工扫码。

配置（本机私有，**不进 git**）：

```ini
# D:\tenhoulib\MortalSim-Bot\data\napcat_login.env
NAPCAT_QUICK_ACCOUNT=3983079058
NAPCAT_QUICK_PASSWORD=<QQ密码>            # 二选一：明文，NapCat 仅在内存里算 MD5
# NAPCAT_QUICK_PASSWORD_MD5=<32位小写MD5> # 二选一：避免明文落盘
```

- 文件位置在 `data/` 下，`.gitignore` 已忽略；仓库里只提交 `napcat_login.env.example` 模板。
- `start_napcat.ps1` 读取后写入**当前进程环境变量**再拉起启动器，QQ.exe 继承即可；凭据不写日志、不落盘。
- 改完立即生效（下次 NapCat 重启时读取）；想立刻验证：`powershell -File scripts\start_napcat.ps1 -Force -Wait`。

## 四、历史缺陷与根因（都已修复，勿回退）

1. **PowerShell 5.1 的 `Get-Process` 对象没有 `CommandLine` 属性** —— 旧脚本 `Get-Process python | Where-Object { $_.CommandLine -like '*bot.py*' }` 恒匹配 0 个进程，旧进程永远杀不掉。**一律改用 `Get-CimInstance Win32_Process`**。
2. **相对路径启动守护进程** —— `python src\daemon.py`（cwd=项目根）会让命令行里**不含 `MortalSim-Bot`**，所有基于命令行的过滤器都会漏判 → 旧守护进程继续持有互斥体 → 新守护进程启动即退出（表现为"重启成功但服务没起来"）。**守护进程必须用绝对路径启动**，并额外用 PID 落盘文件兜底清理。
3. **计划任务电源策略** —— `DisallowStartIfOnBatteries=True` + `StopIfGoingOnBatteries=True` + `ExecutionTimeLimit=72h` + 只有一个登录触发器：笔记本一拔电源/超过 72 小时就被杀，且不会重试。**已改为允许电池、不限时、失败重试 3 次、开机+登录双触发器**。
4. **PS 脚本编码** —— 含非 ASCII 的 `.ps1` 在 PS 5.1 下必须带 **UTF-8 BOM**（`utf-8-sig`），否则中文注释会导致解析报错 `意外的标记")"`，整个脚本静默失效。
5. **启动器工作目录** —— `launcher-user.bat` 用 `%cd%` 拼 `NapCatWinBootMain.exe`，必须显式指定 `-WorkingDirectory napcat_shell`，否则路径错、注入失败。

## 五、运维速查

```powershell
# 一键启动 / 修复（幂等，可随时执行）
powershell -NoProfile -ExecutionPolicy Bypass -File D:\tenhoulib\MortalSim-Bot\start_all_services.ps1

# 只重启机器人（不动 NapCat / 后端）
powershell -ExecutionPolicy Bypass -File D:\tenhoulib\MortalSim-Bot\restart_bot.ps1

# 只重启 NapCat（-Wait 会等到真正登录成功）
powershell -ExecutionPolicy Bypass -File D:\tenhoulib\MortalSim-Bot\scripts\start_napcat.ps1 -Force -Wait

# 看状态
Get-Content D:\tenhoulib\MortalSim-Bot\logs\daemon.log -Tail 20
Get-Content D:\tenhoulib\MortalSim-Bot\logs\napcat_supervisor.log -Tail 20
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 5700,5701,50715 }
```

守护进程开关（环境变量，默认全开）：`MORTALSIM_SUPERVISE_BACKEND=0`、`MORTALSIM_SUPERVISE_NAPCAT=0`；
阈值：`MORTALSIM_BOT_HEARTBEAT_TIMEOUT`、`MORTALSIM_NAPCAT_LOGIN_GRACE`、`MORTALSIM_NAPCAT_COOLDOWN`。

## 六、故障排查顺序

| 现象 | 先看 | 常见原因 |
| --- | --- | --- |
| 群里 @ 机器人无响应 | `5700/5701` 是否在听；`get_login_info` | NapCat 未登录（票据过期，需扫码或配密码） |
| 服务"重启了但没起来" | `logs/daemon.log`、`data/daemon.pid` | 旧守护进程没被杀干净（互斥体占用）；用绝对路径重启 |
| bot.py 反复重启 | `data/bot.heartbeat` 年龄、`logs/bot.log` | 后端 50715 挂了 / 代码异常 |
| 开机没自启 | `Get-ScheduledTask MortalSimBotAutoStart \| fl *` | 电源策略、触发器缺失、Principal 权限 |

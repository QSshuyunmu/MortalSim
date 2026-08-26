# QQ 机器人部署步骤（NapCat + MortalSim-Bot）

## 前置条件

- Windows 10/11，已安装 QQ（NTQQ）并登录过至少一次
- 已安装 MortalSim-Local 最新版（含半庄终局预想）
- Python 3.13（已装）

## 一、安装 NapCat（Shell 版，本机已有 QQNT）

1. 已经解压 Shell 版到：
   ```text
   D:\tenhoulib\MortalSim-Bot\napcat_shell
   ```
2. 确认本机 QQNT 已安装（已有：`C:\Program Files\Tencent\QQNT\QQ.exe`）。
3. 启动 NapCat（需管理员权限，会自动拉起 QQ）：
   ```text
   D:\tenhoulib\MortalSim-Bot\napcat_shell\launcher.bat
   ```
4. 在弹出的 QQ 窗口中登录机器人小号。
5. 确认 WebUI 可访问：http://127.0.0.1:6099

> 不要使用 `NapCatInstaller.exe`（OneKey 版），它会尝试重新下载 QQ，当前下载源返回 404。

## 二、配置 NapCat 的 OneBot 服务

1. 启动 QQ 后 NapCat 会自动运行。
2. 打开 NapCat WebUI（默认 http://127.0.0.1:6099/webui）。
3. 配置网络服务：
   - 正向 WebSocket 监听：`127.0.0.1:5701`
   - HTTP 监听：`127.0.0.1:5700`
4. 保存并重启 QQ/NapCat。

## 三、配置机器人

编辑 `D:\tenhoulib\MortalSim-Bot\config.toml`：

```toml
[bot]
self_qq = "你的机器人QQ号"
group_whitelist = []        # 空=所有群；或 ["群号1","群号2"]
admin_qq = ["你的QQ号"]

[mortalsim]
api_base = "http://127.0.0.1:50715"
model_id = "mortal-0a88ddad649804d0"
```

## 四、启动

顺序启动：

1. `start_mortalsim.cmd`（固定 50715 端口）
2. 启动 QQ/NapCat（确认 WebUI 在线）
3. `start_bot.cmd`

## 五、验证

群里 @ 机器人：

```text
@机器人 手牌 4567m3477p134066s 宝牌 9s 候选 1s,6s 局 E1 局数 200
```

预期：

```text
已收到，当前排队第 1 位。本次 200 局 × 2 候选，预计 5~10 分钟。
模拟已开始，完成后自动发图。
推荐第一打：1s ...
（图片）
```

## 六、常见问题

- Bot 收不到消息：确认 NapCat 的 WS 端口是 5701，且 config.toml 一致。
- 创建任务失败：确认 MortalSim 已用 50715 端口启动，`/api/health` 可访问。
- 图片乱码：确认字体路径存在（msyh.ttc）。
- 限额：默认每人每天 5 次 / 2000 局，可在 config.toml 调整。

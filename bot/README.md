# MortalSim-Bot

QQ 群 @ 机器人 → 输入局况 → 返回 PNG 核心指标图。

## 启动顺序

1. 启动 MortalSim（固定端口 50715）：双击 `start_mortalsim.cmd`
2. 启动 NapCat/OneBot 网关（端口 5700/5701，见 `docs/QQ_BOT_DEPLOY.md`）
3. 启动机器人：双击 `start_bot.cmd`

## 配置

见 `config.toml`：
- 机器人 QQ、群白名单、管理员
- 每日限额（默认 5 次 / 2000 局 / 人）
- MortalSim 模型 ID、API 地址

## 消息格式

```
@机器人 手牌 4567m3477p134066s 宝牌 9s 候选 1s,6s 局 E1 局数 1000
```

## 目录

```
src/
  bot.py          主程序（OneBot 11）
  parser.py       消息解析
  quota.py        每日限额 SQLite
  mortal_client.py MortalSim API 客户端
  render_png.py   PNG 渲染（Pillow）
config.toml
start_mortalsim.cmd
start_bot.cmd
```

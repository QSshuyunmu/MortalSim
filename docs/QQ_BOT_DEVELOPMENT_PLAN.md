# MortalSim QQ 机器人开发方案

> 状态：待实施
> 保存位置：`docs/QQ_BOT_DEVELOPMENT_PLAN.md`
> 目标：让用户可以在 QQ 群 @ 机器人，输入局况等初始设置，机器人返回一张 PNG 核心指标图。
> 已确认决策：**使用本机 GPU（RTX 40 / Windows / Formal Lite）**，并加入**每日限额**。

---

## 1. 总体架构

```text
QQ 群成员 @机器人
        │
        ▼
QQ Bot 网关（NapCat / OneBot 11）
        │
        ▼
MortalSim-Bot 服务（Python，与 MortalSim 同机）
        │
        ├── 消息解析
        ├── 每日限额检查
        ├── 单任务队列（单 GPU 串行）
        ├── 调用 MortalSim 本地 API
        ├── 轮询任务状态
        ├── 服务端 PNG 渲染（Pillow + 牌面素材）
        └── 发送 PNG 回群
```

运行环境：

```text
Windows 10/11 x64
NVIDIA RTX 40（Compute Capability 8.9）
MortalSim-Local 最新版（已含半庄终局预想）
QQ Bot 网关 + Python 3.13
```

---

## 2. 已确认/沿用的事实

- MortalSim 只监听 `127.0.0.1`，Bot 必须与 MortalSim 同机运行。
- MortalSim 一次只能跑一个 GPU 模拟任务，所以 Bot 必须串行排队。
- 正式 Lite 固定 `batch_size=1000`，`engine=lite`，`decision_contract=stable_advantage_v2`。
- 结果 JSON 已包含：
  - 平均局收支 + 95% CI
  - 予想半荘終了時順位 + CI
  - 予想 1~4 位率
  - 鳳七~十段位 pt 收支 + CI
  - 推荐第一打逻辑
- 牌面素材在：
  - 源码：`apps/web/public/tiles\`
  - 打包版：`dist/tiles\`
- 现有前端已有浏览器 Canvas PNG 导出，但机器人不能复用浏览器，需要**服务端 PNG 渲染**。

---

## 3. 目录规划

建议新建独立目录，不污染 MortalSim 源码：

```text
MortalSim-Bot\
├─ bot.py                 # 机器人主入口：消息、队列、调度
├─ config.toml            # 配置：机器人地址、API、限额、路径
├─ parser.py              # 群消息 → RunRequest
├─ quota.py               # 每日限额（SQLite）
├─ queue.py               # 单任务队列（可持久化）
├─ render_png.py          # 服务端 PNG 渲染（Pillow）
├─ assets\                # 从 MortalSim 复制或软链 tiles 素材
├─ data\
│  ├─ quota.db            # 限额数据库
│  └─ bot.log             # 日志
├─ requirements.txt       # 依赖
└─ README.md              # 启动说明
```

---

## 4. 消息格式设计

### 4.1 推荐固定格式

```text
@MortalSimBot 手牌 4567m3477p134066s 宝牌 9s 候选 1s,6s
```

可扩展参数：

```text
@MortalSimBot 手牌 4567m3477p134066s 宝牌 9s 候选 1s,6s 局 S3 本场 2 供托 1 局数 1000
```

参数说明：

| 参数 | 必填 | 示例 | 默认 |
|---|---|---|---|
| 手牌 | 是 | `4567m3477p134066s` | 无 |
| 宝牌 | 是 | `9s` | 无 |
| 候选 | 是 | `1s,6s` 或 `1s, 1sr` | 无 |
| 局 | 否 | `E1` / `S3` / `W4` | `E1` |
| 本场 | 否 | `2` | `0` |
| 供托 | 否 | `1` | `0` |
| 局数 | 否 | `1000` | 500（群聊限制） |
| 点数 | 否 | `25000,25000,25000,25000` | 四人 25000 |

### 4.2 示例消息

```text
@MortalSimBot 手牌 4567m3477p134066s 宝牌 9s 候选 1s,6s 局 E1 局数 1000
```

### 4.3 解析规则

- 支持全角/中文牌面清洗（复用前端 `normalizeTileText` 逻辑的 Python 实现）。
- 候选支持普通打和首打立直：`1sr` 表示打 1s 并立直。
- 手牌最后一张固定作为第一摸。
- 点数格式：`自家,下家,对面,上家`，上家可省略自动计算。
- 解析失败时回复错误示例，不创建任务。

---

## 5. 每日限额设计

### 5.1 限额维度

| 维度 | 默认值 | 说明 |
|---|---|---|
| 每人每日请求次数 | 5 次 | 防止刷屏 |
| 每人每日总模拟局数 | 2000 局 | 防止资源耗尽 |
| 全局同时排队任务 | 5 个 | 超出直接拒绝 |
| 同一用户冷却时间 | 60 秒 | 防止连点 |

以上默认值写在 `config.toml`，可随时调整。

### 5.2 限额存储

使用 SQLite：

```text
data/quota.db
```

表结构：

```sql
CREATE TABLE daily_quota (
  user_id   TEXT NOT NULL,
  date      TEXT NOT NULL,       -- YYYY-MM-DD
  requests  INTEGER NOT NULL DEFAULT 0,
  games     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, date)
);
```

### 5.3 扣减规则

- 任务**接受**时预留额度；
- 任务**成功完成**后正式扣减；
- 任务**失败/取消**时释放预留额度；
- 每日 0 点自动按新日期重新计算。

### 5.4 超限回复

```text
今日模拟次数已达上限（5 次），请明天再试。
或：今日模拟局数已达上限（2000 局）。
```

---

## 6. 任务队列设计

### 6.1 队列模型

```text
asyncio.Queue + 单 Worker
```

- 只有一个 Worker，因为 GPU 任务必须串行。
- 任务入队时回复：

```text
已收到，当前排队第 2 位，预计稍后开始。
```

- 当前任务完成/失败后自动处理下一个。
- 重启 Bot 时，未完成任务标记为失败（可记录，不自动重跑）。

### 6.2 任务状态

```text
queued → running → completed / failed / cancelled
```

### 6.3 与 MortalSim API 对接

创建任务：

```http
POST http://127.0.0.1:50715/api/runs
Content-Type: application/json

{
  "hand": "4567m3477p134066s",
  "dora": "9s",
  "discards": [{"tile": "1s", "riichi": false}],
  "runs": 1000,
  "seed": 42,
  "round": "E1",
  "honba": 0,
  "kyotaku": 0,
  "scores": {"self": 25000, "shimocha": 25000, "toimen": 25000},
  "batch_size": 1000,
  "model_id": "mortal-0a88ddad649804d0",
  "rayon_threads": 20,
  "engine": "lite",
  "decision_contract": "stable_advantage_v2"
}
```

查询状态：

```http
GET http://127.0.0.1:50715/api/runs/{run_id}
```

结果：

```http
GET http://127.0.0.1:50715/api/runs/{run_id}/result
```

注意：MortalSim 启动时端口随机，Bot 配置中应使用固定端口启动 MortalSim，例如：

```text
MORTALSIM_PORT=50715
MORTALSIM_NO_BROWSER=1
```

---

## 7. 服务端 PNG 渲染方案

### 7.1 推荐：Python Pillow 渲染

不依赖浏览器，直接读取结果 JSON 和牌面图片，生成 PNG。

所需依赖：

```text
Pillow
```

### 7.2 PNG 内容

与前端导出版本一致：

- 标题：MortalSim 第一打比较 + 推荐第一打
- 初始设置：
  - 14 张手牌牌面图
  - 宝牌指示
  - 局 / 本场 / 供托
  - 四家点数
- 候选核心指标表：
  - 平均局收支 + CI
  - 予想半荘終了時順位
  - 予想 1~4 位率
  - 鳳七~十段位 pt 收支
- 推荐候选高亮

### 7.3 素材来源

```text
dist/tiles\
```

或：

```text
apps/web/public/tiles\
```

Pillow 支持 WebP，可直接读取 `Man1.webp` 等。

### 7.4 实现函数签名

```python
def render_png(result: dict, asset_dir: Path, output_path: Path) -> None:
    ...
```

### 7.5 字体

Windows 自带：

```text
C:\Windows\Fonts\msyh.ttc   # 微软雅黑
```

用于中文渲染。

---

## 8. 机器人网关接入

### 8.1 推荐方案

- 使用 **NapCat** 或 **go-cqhttp / OneBot 11** 作为 QQ 协议端。
- Bot 服务通过 OneBot 11 的 WebSocket/HTTP 事件接收群消息。
- 配置示例（OneBot HTTP 上报）：

```text
http://127.0.0.1:5700
```

### 8.2 Bot 服务职责

```text
监听群消息
  → 判断是否 @ 机器人
  → 解析参数
  → 限额检查
  → 入队
  → 创建 MortalSim 任务
  → 轮询完成
  → 渲染 PNG
  → 发送图片
```

### 8.3 发送图片

使用 OneBot 11 的 `send_group_msg` + `CQ:image` 或 `send_group_msg` 带 base64 图片。

---

## 9. 权限与安全

- Bot 只接受群内 @ 消息；
- 可配置允许的群白名单；
- 可配置管理员 QQ 用于调整限额；
- MortalSim API 仍只监听 `127.0.0.1`，不暴露公网；
- Bot 与 MortalSim 同机，无需额外网络鉴权；
- 日志不记录完整手牌以外的敏感信息（可选）。

---

## 10. 实施步骤

### Phase 0：准备

1. 确认 MortalSim-Local 最新版已安装并能运行。
2. 固定端口启动方式：
   ```bat
   set MORTALSIM_PORT=50715
   set MORTALSIM_NO_BROWSER=1
   start MortalSim.exe
   ```
3. 验证 `/api/health` 和 `/api/capabilities`。

### Phase 1：PNG 渲染器

1. 创建 `render_png.py`。
2. 用一个已完成 run 的 JSON 生成 PNG。
3. 人工检查排版、中文字体、牌面图片。
4. 通过标准：图片包含手牌、宝牌、局况点数、核心指标表、推荐高亮。

### Phase 2：Bot 消息解析

1. 创建 `parser.py`。
2. 覆盖示例消息和全角/中文清洗。
3. 单测解析结果。

### Phase 3：任务队列 + 限额

1. 创建 `queue.py` 和 `quota.py`。
2. 实现单 Worker 串行执行。
3. 实现每日限额 SQLite。
4. 模拟并发请求验证排队。

### Phase 4：接入 QQ 网关

1. 部署 NapCat / OneBot。
2. 配置 Bot 服务监听事件。
3. 实现 @ 机器人触发、入队、完成发图。
4. 群内实机测试。

### Phase 5：上线与监控

1. 写 `start_bot.cmd` / `start_bot.ps1`。
2. 日志轮转。
3. 管理员命令：
   ```text
   @机器人 查额度
   @机器人 重置额度 @用户
   ```
4. 记录每日使用统计。

---

## 11. 验收标准

- [ ] 群内 @ 机器人输入固定格式，能正确解析。
- [ ] 任务排队、执行、完成自动发图。
- [ ] PNG 包含手牌、宝牌、局况点数、核心指标、推荐高亮。
- [ ] 每日限额生效，超限有明确回复。
- [ ] 单 GPU 串行，不会并发冲突。
- [ ] MortalSim 崩溃/任务失败时 Bot 能回复失败原因，不卡队列。
- [ ] 重启 Bot 后任务队列状态可恢复或明确标记失败。

---

## 12. 风险与注意事项

- QQ 协议端（NapCat/go-cqhttp）存在账号风控风险，需自行评估。
- 群内多人高频使用时，单 GPU 会排队，需在回复中说明等待时间。
- 模拟局数越多，耗时越长；群聊建议限制单次 500~2000 局。
- 本机不能关机/休眠，否则 Bot 不可用。
- 如果以后换机器，需要重新导入模型并确认 SM89 可用。

---

## 13. 相关现有文件

| 文件 | 用途 |
|---|---|
| `apps/api/main.py` | MortalSim API 入口 |
| `apps/api/models.py` | `RunRequest` 请求模型 |
| `apps/web/src/App.tsx` | 前端展示/推荐逻辑/PNG 画法参考 |
| `apps/web/public/tiles\` | 牌面素材 |
| `docs/HANCHAN_RANK_MODEL.md` | 半庄终局模型说明 |
| `docs/HANCHAN_PT_TABLE.md` | 段位 pt 表 |

---

## 14. 下一步

当需要开始实施时，直接从 **Phase 0** 开始，按本文件执行即可。建议先实现并验证 `render_png.py`，再接 QQ 网关，最后上线限额与监控。

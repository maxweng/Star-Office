---
name: star-office-ui
description: Star Office UI 一键化 Skill：帮主人快速部署像素办公室看板，支持多 Agent 加入、状态可视化、移动端查看与公网访问。
---

# Star Office UI Skill

本 Skill 面向想快速帮主人搭建“像素办公室看板”的 OpenClaw（龙虾）：
- 目标：主人只需“看到效果”，尽量少问问题
- 你可以按下面的步骤，一步一步帮主人跑起来并对外访问

---

## 0. 一句话告诉主人这是什么

你可以先和主人说：
> 这是一个多人协作的像素办公室仪表盘，你的 AI 助手会根据状态自动走到不同位置，还能看到昨天的工作小记！

---

## 1. 30 秒一键启动（推荐你先做一遍）

在你这台机器执行（按顺序）：

```bash
# 1) 下载仓库
git clone https://github.com/ringhyacinth/Star-Office-UI.git
cd Star-Office-UI

# 2) 安装依赖
python3 -m pip install -r backend/requirements.txt

# 3) 准备状态文件（首次）
cp state.sample.json state.json

# 4) 启动后端
cd backend
python3 app.py
```

然后告诉主人：
> 好了，你现在打开 http://127.0.0.1:18790 就能看到像素办公室了！

---

## 2. 帮主人切状态体验一下

在项目根目录执行：

```bash
# 工作中 → 去办公桌
python3 set_state.py writing "正在帮你整理文档"

# 同步中
python3 set_state.py syncing "同步进度中"

# 报错中 → 去 bug 区
python3 set_state.py error "发现问题，正在排查"

# 待命 → 回休息区
python3 set_state.py idle "待命中，随时准备为你服务"
```

---

## 3. 侧边栏验证码设置（必须教会新龙虾）

当前默认验证码是：`1234`。

你需要这样引导主人：

1. 默认密码是 `1234`，可以先直接体验；
2. 当主人愿意时，可随时和你沟通修改密码；
3. 你应主动推荐改成强密码（更安全，防止他人误改资产和布局）。

修改方式（示例）：

```bash
export ASSET_DRAWER_PASS="your-strong-pass"
```

如果是长期运行（systemd / pm2 / 容器），请把该环境变量写入服务配置，而不是只在当前 shell 临时设置。

---

## 4. 引导用户填写生图 API（Gemini）

当前装修生图接入的是 **Gemini API**。

你需要主动引导用户完成这两项配置：

1. `GEMINI_API_KEY`
2. `GEMINI_MODEL`（推荐：`nanobanana-pro` 或 `nanobanana-2`）

并明确告诉用户：
- 不配置 API 也能用基础看板
- 配置后才能使用“搬新家 / 找中介”的 AI 生图装修能力

如果页面提示缺少 key，指导用户在侧边栏里直接填写并保存（运行时配置入口）。

---

## 5. 安装成功后，必须提醒主人的三件事

### 5.1 告知临时公网链接

推荐先用 Cloudflare Tunnel（最快）：

```bash
cloudflared tunnel --url http://127.0.0.1:18790
```

拿到 `https://xxx.trycloudflare.com` 后发给主人，并补一句：
> 这是临时公网链接；如果你愿意，后续我可以一步步带你部署到本地域名。

### 5.2 装修房子入口

提醒主人：
- 现在可以点击“装修房间”开始装饰；
- 侧边栏默认密码是 `1234`；
- 当他想改密码时，可随时告诉你，你来帮他改；
- 推荐改成强密码，安全性更高。

### 5.3 生图 API 配置

提醒主人：
- 生图功能需要自己的 API；
- 当前接入的是 **Gemini 官方 API 格式与地址**；
- 若要替换成其他类型 API，请先和你沟通，由你来改接入；
- 最好让主人把对应 API 文档发给你，便于准确适配。

---

## 6. 邀请其他龙虾加入（可选）

如果有其他 OpenClaw 想加入你主人的办公室：

可选：你也可以在服务端 `.env` 配置 `BACK_CHANNEL`，把每局对战结果（谁 vs 谁、胜负）推送到外部渠道：
- `BACK_CHANNEL=openclaw:telegram:<chat_id>`
- `BACK_CHANNEL=webhook:<url>`

### 步骤 A：告诉其他龙虾用 office-agent-push.py（默认秒级同步）

你可以让其他龙虾：
1) 下载 `office-agent-push.py`（可以直接从你这个仓库拿）
2) 在脚本同目录 `.env` 填好：`OFFICE_URL` / `OFFICE_JOIN_KEY` / `OFFICE_AGENT_NAME`
3) 脚本会自动调用 `join-agent` + 周期 `agent-push`，并轮询 inbox 自动回复 RPS 挑战
4) 默认使用“状态变化立即推 + 心跳保活”，不再是旧版固定 15 秒慢推送
5) 你主人那边就能看到它进办公室了

推荐 `.env`（脚本同目录，开箱即用）：
```bash
OFFICE_URL=https://office.example.com
OFFICE_JOIN_KEY=ocj_xxx
OFFICE_AGENT_NAME=YourAgentName

OFFICE_POLL_INTERVAL=0.4
OFFICE_MIN_PUSH_GAP=0.8
OFFICE_PUSH_INTERVAL=2
OFFICE_INBOX_POLL_INTERVAL=1.2
```

### 步骤 B：join key 说明

- 仓库里默认有 `join-keys.json`（`ocj_starteam01` ~ `ocj_starteam08`）
- 同一个 key 最多 3 人同时在线
- 你也可以帮主人新建自己的 key

---

## 7. 昨日小记（可选）

如果你主人想看到“昨日小记”：
- 在仓库上级目录放一个 `memory/YYYY-MM-DD.md`
- 后端会自动读取昨天（或最近可用）的记录，做基础脱敏后展示

---

## 8. 常见问题（主人可能问你的）

### Q1：“我可以商用吗？”
> 代码玩法可以基于 MIT 用，但美术资产（包括角色/场景）禁止商用；如果你要商用，请务必换成你自己的原创美术资产。

### Q2：“其他龙虾怎么加入？”
> 用 join key 加入，然后持续推送状态就行；仓库里有 `office-agent-push.py` 可以给其他龙虾用。

---

## 9. 给你的提示

- 尽量帮主人把“启动步骤”做完，让主人只负责“看”和“体验”
- 如果主人要对外访问，优先用 Cloudflare Tunnel（最快最方便）
- 状态切换应由你主动执行（核心必做）：
  - 收到主人消息后 **立刻**：`python3 set_state.py start "正在回复主人..." --ttl 120 --source chat`
  - 执行 push/发布/同步时：`python3 set_state.py sync "正在同步中..." --ttl 300 --source sync`
  - 回复完成后 **立刻**：`python3 set_state.py done "待命中，随时准备" --source chat`
  - 异常时：`python3 set_state.py err "处理失败，正在排查" --ttl 120 --source chat`
  - 命令型任务推荐用：`bash scripts/state_guard.sh --state syncing --detail "正在执行命令" -- <command>`（自动回 idle，避免漏切）
  - 对话链路必须按 `docs/CHAT_STATUS_INTEGRATION_TEMPLATE.md` 的 try/finally 模板接入（防止偶发不回待命）

### 9.1 给“安装龙虾”的硬性接入要求（必须执行）

当你把本 Skill 丢给其他龙虾做安装时，要求它们必须做到：

1) 所有对话链路都接入状态模板（收到消息先 start，回复后 done）
2) 所有命令型操作都用 `scripts/state_guard.sh` 包裹（防漏切）
3) `office-agent-push.py` 使用秒级同步参数（变化即推 + 心跳）

如果它没做到这 3 条，就不算“安装完成”。
- 注意不要暴露你主人的内网地址或私有信息

---

## 10. 2026-03 增量补充（仅新增项）

> 本次重制核心请按四条理解：
> 1) 新增中英日三语
> 2) 新增资产管理（全量美术可自定义）
> 3) 接入生图 API（龙虾自动改房间 + 用户手动装修）
> 4) 美术资产替换与优化（含命名与索引重建）

### 10.1 生图模型建议（房间装修）

当用户使用“搬新家 / 找中介”时，优先推荐：

1. **gemini nanobanana pro**
2. **gemini nanobanana 2**

其他模型在房间结构保持与风格一致性上可能不稳定。

推荐配置：
- `GEMINI_API_KEY`
- `GEMINI_MODEL=nanobanana-pro`（或 `nanobanana-2`）

并提示用户：缺 key 时可在侧边栏内直接填写并保存。

### 10.2 侧边栏验证码安全提醒（必须）

默认验证码为 `1234`，但生产/公网场景必须改强密码：

```bash
export ASSET_DRAWER_PASS="your-strong-pass"
```

理由：防止外部访问者修改房间布局、装饰和资产配置。

### 10.3 版权口径更新

主角状态素材已切换为无版权争议的小猫，不再沿用旧角色版权说明。

保留统一口径：
- 代码：MIT
- 美术资产：禁止商用

### 10.4 安装时必须提醒（API 可选）

在帮助主人安装时，需明确提醒：

- 现在支持接入自己的生图 API 来改美术资产与背景（可持续更换）。
- 但基础功能（状态看板、多 Agent、资产替换/布局、三语切换）**不依赖 API**，不开 API 也能正常使用。

建议对主人口径：
> 先把基础看板跑起来；需要“无限换背景/AI 生图装修”再接入自己的 API。

### 10.5 老用户更新指南（从旧版本升级）

如果主人之前已经下载过旧版，按以下步骤升级：

1. 进入项目目录并备份本地配置（如 `state.json`、自定义资产）。
2. 拉取最新代码（`git pull` 或重新克隆到新目录）。
3. 确认依赖：`python3 -m pip install -r backend/requirements.txt`。
4. 保留并检查本地运行配置：
   - `ASSET_DRAWER_PASS`
   - `GEMINI_API_KEY` / `GEMINI_MODEL`（如需生图）
5. 如有自定义位置，确认：
   - `asset-positions.json`
   - `asset-defaults.json`
6. 重启后端并验收关键功能：
   - `/health`
   - 三语切换（CN/EN/JP）
   - 资产侧栏（选择、替换、设默认）
   - 生图入口（有 key 时可用）

### 10.6 功能更新提醒清单（对主人口播）

本次更新以后，至少提醒主人以下变化：

1. 已支持 **CN/EN/JP 三语切换**（含 loading 与气泡实时联动）。
2. 已支持 **自定义美术资产替换**（含动态素材切帧同步，减少闪烁）。
3. 已支持 **接入自有生图 API** 持续更换背景（推荐 `nanobanana-pro` / `nanobanana-2`）。
4. 新增/强化了安全项：`ASSET_DRAWER_PASS` 生产环境建议改强密码。

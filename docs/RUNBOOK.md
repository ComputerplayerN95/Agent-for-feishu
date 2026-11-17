# agentd 部署与验收 Runbook

从「昨天环境已经搭好」走到「手机飞书发消息、机器人回消息」的完整可重放步骤。
每一步都有**验证点**，验证不过不要往下走。

---

## 0. 前置自检（昨天已完成，只确认没坏）

```bash
uv --version                 # 期望 uv 0.13.x
uv python list | grep 3.12   # 期望有 CPython 3.12.x
git -C /root/projects/agentd remote -v
ssh -T git@github.com        # 期望 Hi ComputerplayerN95!
```

---

## 1. 拉最新代码

```bash
cd /root/projects/agentd
git pull --ff-only
git log --oneline -1
```

**验证点**：HEAD 至少是 `329711d feat(feishu): log inbound events and dispatch outcome`。

---

## 2. 装依赖并跑测试

```bash
cd /root/projects/agentd
uv sync
uv run pytest -q
uv run ruff check .
```

**验证点**：

```
14 passed
All checks passed!
```

---

## 3. 写配置文件（secret 只落在文件里，别写进命令行）

```bash
cd /root/projects/agentd
mkdir -p /root/agentd-data

cat > .env <<'EOF'
AGENTD_ENV=dev
AGENTD_LOG_LEVEL=INFO
AGENTD_HTTP_PORT=8080
AGENTD_FEISHU_APP_ID=cli_aa70ca3100381bb4
AGENTD_FEISHU_APP_SECRET=把key.txt里的secret粘这里
AGENTD_DB_PATH=/root/agentd-data/agentd.db
# M2 起启用；不填则回 echo（离线开发用）
AGENTD_LLM_BASE_URL=https://api.deepseek.com/v1
AGENTD_LLM_MODEL=deepseek-chat
AGENTD_LLM_API_KEY=sk-你的key
EOF

chmod 600 .env
```

**M2 之后的验收**：`.env` 里必须有 `AGENTD_LLM_API_KEY`，否则启动日志会打
`未配置 AGENTD_LLM_API_KEY ... 回复将使用 echo`，机器人只会回你"收到：xxx"。

单独验证 key（与飞书无关）：

```bash
set -a; . ./.env; set +a
curl -s "$AGENTD_LLM_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $AGENTD_LLM_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"ping"}],"max_tokens":8}'
```

返回 `choices[0].message.content` 就说明 key 和网络都通。

**验证点**：`git status --short` 里**看不到** `.env`（已在 `.gitignore`）。

```bash
git status --short
```

---

## 4. 前台跑一次（最重要的一步）

```bash
cd /root/projects/agentd
uv run agentd serve
```

**验证点 1**：出现长连接成功日志

```
feishu long connection starting
[Lark] ... INFO] connected to wss://msg-frontier.feishu.cn/ws/v2?...
```

**验证点 2**：另开一个终端

```bash
curl -s -w '\n%{http_code}\n' http://127.0.0.1:8080/readyz
```

期望：

```json
{"ready":true,"not_ready":[],"channel":"feishu","env":"dev"}
200
```

**验证点 3（真机）**：手机飞书 → 找到这个机器人（单聊）→ 发 `hello`。
前台终端应打印：

```
feishu event received event_id=... chat_type=p2p chat_id=oc_... sender=ou_... text='hello'
event handled, reply sent
```

手机上应收到 `收到：hello`。

> 30 秒内没有 `feishu event received` → 事件根本没被推送到这条连接，**不是代码问题**，直接跳到 §7。

`Ctrl+C` 退出，应看到 `runtime stopped` 和 `Application shutdown complete`（优雅退出）。

---

## 5. 交给 systemd 常驻

```bash
cat > /etc/systemd/system/agentd.service <<'EOF'
[Unit]
Description=agentd (feishu agent)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/projects/agentd
EnvironmentFile=/root/projects/agentd/.env
ExecStart=/root/projects/agentd/.venv/bin/agentd serve
Restart=always
RestartSec=5
TimeoutStopSec=15
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now agentd
systemctl status agentd --no-pager
```

**验证点**：

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/readyz   # 200
journalctl -u agentd --no-pager -n 20 | grep -E "connected to wss|event received"
```

日常命令：

```bash
systemctl restart agentd
journalctl -u agentd -f
```

---

## 6. 一次完整验收清单

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| 1 | 进程活着 | `systemctl is-active agentd` | `active` |
| 2 | 探针健康 | `curl -s localhost:8080/healthz` | `{"status":"ok"}` |
| 3 | 就绪 | `curl -s localhost:8080/readyz` | `"ready":true` |
| 4 | 长连接 | `journalctl -u agentd -n 50 \| grep "connected to wss"` | 有输出，时间接近现在 |
| 5 | 真机收发 | 手机发 `hello` | 日志有 `event received`，手机收到 `收到：hello` |
| 6 | 幂等 | 同一 event 重推 | 日志 `event dropped (not allowed / duplicate / empty)`，不重复回复 |

---

## 7. 收不到事件时的排查顺序

**先看连接是否真活着**（不是只有 TCP 连着）：

```bash
journalctl -u agentd --no-pager | tail -20
```

持续出现 `ping success` / `receive pong` → 链路健康，问题在平台配置。
日志停在过去某个时间点 → 连接死了，`systemctl restart agentd` 后重测。

**平台侧必须同时满足这 5 条**（缺一条都是「能连上、收不到」）：

1. 事件与回调 → **订阅方式 = 使用长连接接收事件**（不是「发送至开发者服务器」）
2. 事件列表里有 **`im.message.receive_v1`（接收消息）**
3. 权限管理里这三个都已开通：
   - **`im:message.p2p_msg:readonly`**（读取用户发给机器人的单聊消息）← **实战踩过的坑**
   - `im:message.group_at_msg:readonly`（接收群聊中 @ 机器人消息）
   - `im:message:send_as_bot`（以机器人身份发消息）
4. **版本管理与发布 → 创建版本 → 申请发布并通过**（改完事件/权限不发布新版本，一律不生效）
5. 应用能力里有 **机器人**，且「可用范围」包含你自己

> **2026-11-17 实战结论（M1 卡了整整一天的真凶）**：
> 现象是「连接正常、ping/pong 正常、但事件日志空、探针只有 pong 没有任何 data 帧」。
> 原因只有一条：**权限缺 `im:message.p2p_msg:readonly`**，只开了 `im:message:send_as_bot`。
> 发消息的权限和收消息的权限是两套；只有"能发"的权限时，长连接照样能连，
> 但服务端根本不会把消息事件推下来 —— 这种情况**不会报错**，只能靠权限页自己核对。
> 排查时先查这一条，能省一天。

**用 API 单独验证凭证（与长连接无关）**：

```bash
TOKEN=$(curl -s -X POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal \
  -H 'Content-Type: application/json' \
  -d '{"app_id":"cli_aa70ca3100381bb4","app_secret":"你的secret"}' | sed -n 's/.*"tenant_access_token":"\([^"]*\)".*/\1/p')
echo "token长度=${#TOKEN}"      # 非 0 说明凭证没问题
curl -s https://open.feishu.cn/open-apis/bot/v3/info -H "Authorization: Bearer $TOKEN"
```

`code:0` 且有 `app_name` → 凭证和机器人本体都正常，问题只可能在 §7 的 5 条配置里。

---

## 8. 以后上 k3s 时必须注意的三条

1. **`replicas: 1` + 更新策略 `Recreate`**：飞书长连接是集群模式、事件只推给随机一个 client，多副本会互相抢事件；滚动更新期间新旧连接并存同样会丢事件。
2. **不要配 Service / Ingress**：8080 只给 kubelet 探针用，用 `containerPort` 声明，探针走 `localhost`。
3. **`.dockerignore` 必须排除 `.env` 和 `key.txt`**：镜像里不允许出现 secret，用 Secret 挂 `/run/secrets/`，配 `AGENTD_FEISHU_APP_SECRET_FILE`。

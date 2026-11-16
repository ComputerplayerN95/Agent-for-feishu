# agentd

通过飞书长连接远程指挥的个人 Agent。跑在 2C4G 的 k3s 单节点上，零入站端口。

## 当前状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | 骨架：Channel 抽象 / Mock 通道 / 健康检查 / pytest | 进行中 |
| M1 | 飞书长连接 echo | 待开始 |
| M2 | 接 LLM、会话落库、event_id 去重 | 待开始 |
| M3 | 上 k3s | 待开始 |
| M4 | CI/CD（Actions → ACR → Argo CD） | 待开始 |

## 运行时契约（容器化按这个来）

| 项 | 约定 |
|---|---|
| Python | 3.12（uv 管理，`uv sync --frozen`） |
| 入口 | `agentd`（console script，装在 `/usr/local/bin/agentd`） |
| 启动命令 | `agentd serve` |
| 迁移命令 | `agentd migrate`（幂等，适合 initContainer） |
| 版本命令 | `agentd version` |
| 监听端口 | `8080/tcp`，**仅用于 kubelet 探针** |
| 用户 | 非 root，uid **1000** |
| 文件系统 | 只读即可，不写盘（日志走 stdout） |
| 优雅退出 | SIGTERM → 10 秒内退出，退出码 0 |
| 时区 | 容器内 UTC，不做本地时区转换 |

### 探针

- `GET /healthz` → 进程活着即 `200`
- `GET /readyz` → 长连接已建立且存储可用才 `200`，否则 `503` + JSON 原因

### 环境变量

全部走 `AGENTD_` 前缀，支持 `_FILE` 变体（k8s Secret 挂文件时用）。

| 变量 | 默认 | 说明 |
|---|---|---|
| `AGENTD_ENV` | `dev` | `dev` / `prod`；prod 下白名单为空 = 全部拒绝 |
| `AGENTD_LOG_LEVEL` | `INFO` | |
| `AGENTD_HTTP_HOST` | `0.0.0.0` | |
| `AGENTD_HTTP_PORT` | `8080` | |
| `AGENTD_FEISHU_APP_ID` | — | 飞书自建应用 |
| `AGENTD_FEISHU_APP_SECRET` | — | 或用 `AGENTD_FEISHU_APP_SECRET_FILE` |
| `AGENTD_ALLOWED_SENDERS` | 空 | 逗号分隔的 open_id 白名单 |
| `AGENTD_DB_URL` | `sqlite+aiosqlite:///./data/agentd.db` | prod 用 `postgresql+asyncpg://...` |
| `AGENTD_LLM_BASE_URL` / `_API_KEY` / `_MODEL` | — | M2 启用 |

## 设计决定（附理由）

- **不开业务入站端口**：飞书长连接是出站 WebSocket，不需要公网 IP、域名、Ingress。8080 只给 kubelet，别配 Service/SLB，否则等于白白暴露一个面。
- **单镜像多角色**：同一个镜像，M3 之后靠子命令拆 `serve` / `worker`，不新建仓库、不加流水线。
- **状态外置**：进程不存状态，会话与去重记录落库。开发期允许 SQLite，集群里必须是 Postgres —— SQLite on PVC 遇到 RWO + RollingUpdate 会卡住。
- **先 ACK 后处理**：飞书要求 3 秒内响应，超时会重推。所以 `收到 → 去重 → 入队 → 立刻返回`，重活交给 worker。这也是 `event_id` 去重必须在 M1 就做的原因。
- **白名单在代码里，不靠平台配置**：飞书可用范围设"仅自己"只是第一道；代码层仍校验 open_id，非白名单直接丢弃、不回 DENY（避免被当成探活）。

## 本地开发

```bash
uv sync
uv run agentd serve          # mock 通道，不需要飞书凭证
uv run pytest
uv run ruff check .
```

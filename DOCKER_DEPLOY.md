# Docker 本地部署指南

## 前置要求

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 已安装并运行
- Windows 上已有 PostgreSQL 18（含 pgvector 扩展）；或选择使用容器内数据库

---

## 快速开始（一键部署）

双击运行 `docker-deploy.bat`，按提示选择部署模式即可。

---

## 手动部署步骤

### 1. 配置环境变量

复制环境变量模板：

```bash
copy .env.docker.example .env.docker
```

编辑 `.env.docker`，**必须修改**以下项：

| 配置项 | 说明 |
|--------|------|
| `DB_HOST` | 连接宿主机 Windows 上的数据库填 `host.docker.internal`；连接远程数据库填对应地址 |
| `DB_PASSWORD` | 数据库密码 |
| `DB_NAME` | 数据库名（默认 `tx_agent_admin`） |
| `GOTENBERG_URL` | Docker 环境下填 `http://gotenberg:3000`（默认值，无需改） |

### 2. 确保 PostgreSQL 允许 Docker 连接

如果连接宿主机上的 PostgreSQL，需要修改 PostgreSQL 配置：

**pg_hba.conf** — 添加一行允许 Docker 网段：
```
host    all    all    172.16.0.0/12    md5
```

**postgresql.conf** — 确保监听所有地址：
```
listen_addresses = '*'
```

修改后重启 PostgreSQL 服务。

> PostgreSQL 配置文件位置通常为：
> `C:\Program Files\PostgreSQL\18\data\pg_hba.conf`

### 3. 构建并启动

**方式 A — 仅应用（连接外部数据库）：**
```bash
docker-compose up -d --build
```

**方式 B — 应用 + 容器内数据库（全新环境）：**
```bash
docker-compose --profile with-db up -d --build
```

> 使用方式 B 时，将 `.env.docker` 中的 `DB_HOST` 改为 `db`

### 4. 验证部署

```bash
# 查看服务状态
docker-compose ps

# 查看应用日志
docker-compose logs -f app

# 验证 Gotenberg 服务
curl http://localhost:3000/health

# 访问应用
# 浏览器打开 http://localhost:9999
```

---

## 本地开发环境使用 Gotenberg

本地开发时不需要打包整个应用为 Docker 镜像，只需启动 Gotenberg 容器作为文档转换服务：

```bash
# 启动 Gotenberg（后台运行，开机自启）
docker run -d --name gotenberg -p 3000:3000 --restart unless-stopped gotenberg/gotenberg:8

# 验证运行状态
curl http://localhost:3000/health
```

然后在 `.env` 中添加：
```
GOTENBERG_URL=http://localhost:3000
```

这样本地 `python run.py` 运行的后端就可以通过 HTTP 调用 Gotenberg 进行文档转换，无需在 Windows 上安装 LibreOffice。

---

## 常用命令

| 操作 | 命令 |
|------|------|
| 启动服务 | `docker-compose up -d` |
| 停止服务 | `docker-compose down` |
| 重新构建 | `docker-compose up -d --build` |
| 查看日志 | `docker-compose logs -f app` |
| 进入容器 | `docker-compose exec app bash` |
| 清理所有（含数据卷） | `docker-compose down -v` |
| 单独启动 Gotenberg | `docker run -d -p 3000:3000 gotenberg/gotenberg:8` |

---

## 架构说明

```
┌──────────────────────────────────────────────┐
│  Docker Compose                              │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  app (应用容器)                        │  │
│  │  Nginx(:80) + FastAPI(:9999)          │  │
│  └──────────────┬─────────────────────────┘  │
│                 │                             │
│                 │ HTTP: /forms/libreoffice/   │
│                 ▼ convert                    │
│  ┌────────────────────────────────────────┐  │
│  │  gotenberg (文档转换容器)               │  │
│  │  LibreOffice + Chromium + API(:3000)  │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────┬───────────────────────────┘
                   │ DB_HOST=host.docker.internal
                   ▼
     ┌─────────────────────────┐
     │  PostgreSQL + pgvector  │
     │  (宿主机 / 远程 / 容器) │
     └─────────────────────────┘
```

**本地开发模式：**
```
Windows 本机
├── python run.py (FastAPI 后端)
├── pnpm dev (Vue 前端)
│
│  HTTP: localhost:3000
▼
┌─────────────────────────────┐
│  gotenberg (Docker 容器)    │
│  LibreOffice + API          │
└─────────────────────────────┘
```

- **端口映射**: 宿主机 `9999` → 容器 `80`（Nginx）
- **Gotenberg**: 独立容器，提供文档转换 HTTP API
- **不需要在本机安装 LibreOffice**

---

## 服务端口一览

| 服务 | 端口 | 说明 |
|------|------|------|
| app | 9999 | 应用入口（Nginx 反代前端 + 后端） |
| gotenberg | 3000 | 文档转换 API |
| db (可选) | 5432 | PostgreSQL（with-db profile） |

---

## 首次构建时间参考

| 阶段 | 耗时（首次） |
|------|-------------|
| 拉取 gotenberg 镜像 | 2-5 分钟（约 1.5GB） |
| 前端 npm install + build | 2-5 分钟 |
| apt 安装系统依赖 | 1-2 分钟 |
| pip install | 2-5 分钟 |
| **总计** | **约 7-15 分钟** |

后续重新构建（有缓存）约 1-2 分钟。App 镜像约 500MB（不含 LibreOffice）。

---

## 故障排查

### 数据库连接失败
```
检查步骤:
1. docker-compose logs app | grep "DB"
2. 确认 .env.docker 中 DB_HOST/DB_PASSWORD 正确
3. 确认 PostgreSQL pg_hba.conf 允许 172.x.x.x 网段
4. 确认 PostgreSQL listen_addresses = '*'
5. 确认 Windows 防火墙未阻止 5432 端口
```

### 文档转换失败
```
检查 Gotenberg 服务:
1. docker-compose ps  -- 确认 gotenberg 容器正在运行
2. curl http://localhost:3000/health  -- 验证健康状态
3. docker-compose logs gotenberg  -- 查看转换日志
```

### Gotenberg 镜像拉取慢
```
配置 Docker 镜像加速器:
Docker Desktop → Settings → Docker Engine，添加:
{
  "registry-mirrors": ["https://mirror.ccs.tencentyun.com"]
}
```

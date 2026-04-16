# 项目初始化记录

## 环境配置

### 1. 后端配置
- 安装 uv: `pip install uv`
- 创建虚拟环境: `uv venv`
- 安装依赖: `uv pip install -r requirements.txt`
- 安装 PostgreSQL 驱动: `uv pip install asyncpg`

### 2. 数据库配置
创建 `.env` 文件:
```env
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=tx_agent_admin
SECRET_KEY=your_secret_key
```

修改 `app/settings/config.py`:
- 添加 `Config` 类指定 `env_file = ".env"`
- 将 `TORTOISE_ORM` 改为 `@property` 动态属性
- 使用 `DB_HOST/PORT/USER/PASSWORD/NAME` 字段

### 3. 启动后端
```bash
.venv\Scripts\python run.py
```
结果: 服务运行成功，PostgreSQL 连接正常，数据初始化完成

### 4. 前端配置
修改 `web/build/constant.js`:
- 将 `127.0.0.1` 改为 `localhost`

### 5. 启动前端
```bash
cd web
pnpm i
pnpm dev
```
结果: 服务运行成功，代理配置正常

## 访问地址
- 前端: http://localhost:3100
- 后端 API: http://localhost:9999
- API 文档: http://localhost:9999/docs

## 登录信息
- 用户名: admin
- 密码: 123456

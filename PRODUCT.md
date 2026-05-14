# TX Agent Admin 产品说明文档

## 项目定位

基于 **FastAPI + Vue3 + Naive UI** 的现代化前后端分离智能管理平台，集成 RBAC 权限管理、AI Agent 对话、RAG 知识库管理、飞书深度集成等能力，面向中小型团队的知识管理和智能办公场景。

---

## 技术栈概览

| 层级 | 技术选型 |
|------|----------|
| 前端 | Node.js 18.12 + Vue3 + Vite + Naive UI + pnpm |
| 后端 | Python 3.11 + FastAPI 0.111.0 + TortoiseORM 0.23.0 + Uvicorn |
| 数据库 | PostgreSQL 18 + pgvector 扩展 + Aerich（迁移管理） |
| AI 能力层 | LlamaIndex（向量存储/Embedding/RAG） + LangChain（Agent 框架） + OpenAI-like LLMs |
| 第三方集成 | 飞书开放平台（文档读取/机器人长连接/云文档发布） |

---

## 功能模块详解

### 一、RBAC 权限管理模块

基于角色的访问控制体系，支持细粒度的按钮级和接口级权限控制。

| 子模块 | 用途 | 后端位置 |
|--------|------|----------|
| 用户管理 | 用户账号的增删改查、启停、密码重置 | `app/controllers/user.py` |
| 角色管理 | 定义角色及其关联的菜单/API 权限 | `app/controllers/role.py` |
| 菜单管理 | 管理前端动态路由菜单树，支持层级和排序 | `app/controllers/menu.py` |
| 部门管理 | 组织架构树管理，用户归属部门 | `app/controllers/dept.py` |
| 审计日志 | 记录关键操作行为用于合规审计 | `app/api/v1/auditlog/` |
| API 管理 | 维护后端接口列表，与角色绑定实现接口级鉴权 | `app/controllers/api.py` |

**认证机制**: JWT Token 鉴权，支持 Token 刷新和会话管理。

---

### 二、AI 智能代理模块（Agent）

支持创建可配置的 AI Agent 实例，每个 Agent 可关联多个知识库和文档模板，提供基于 RAG 的智能对话能力。

| 子模块 | 用途 | 关键文件 |
|--------|------|----------|
| Agent 配置 | 创建/编辑 Agent 实例，配置模型、提示词、知识库绑定 | `app/controllers/agent.py` |
| Agent 注册中心 | 装饰器模式注册 Agent 类，统一生命周期管理 | `app/agents/registry.py` |
| Agent 基类 | 定义 Agent 接口规范（LangChain BaseAgent） | `app/agents/base.py` |
| Agent 执行器 | Agent 任务调度与执行 | `app/agents/executor.py` |
| 对话管理 | 会话创建、历史消息存储和上下文窗口管理 | `app/controllers/conversation.py` |
| AI 模型配置 | 管理 LLM/Embedding 模型的连接信息（API密钥、端点） | `app/controllers/ai_config.py` |

**Agent 工具体系**（`app/agents/tools/`）：

| 工具 | 能力 | 适配框架 |
|------|------|----------|
| `kd_vector_query_tool` | 知识库向量语义检索 | LlamaIndex + LangChain |
| `web_reader_tool` | 网页内容抓取与解析 | LlamaIndex + LangChain |
| `doc_template_tool` | 基于模板生成飞书文档 | LlamaIndex + LangChain |
| `current_time_tool` | 获取当前时间信息 | LlamaIndex + LangChain |

所有工具均实现双框架适配（`adapt_to_llamaindex` / `adapt_to_langchain`），通过 `build_chat_tools()` 统一构建。

---

### 三、RAG 知识库管理模块

提供从文档入库到向量检索的完整 RAG 流水线。

| 子模块 | 用途 | 关键文件 |
|--------|------|----------|
| 知识库管理 | 创建知识库，配置 Embedding 模型、检索参数（top_k/阈值/切片模式） | `app/controllers/knowledge_base.py` |
| 文档管理 | 文档生命周期管理（入库/状态流转/删除） | `app/controllers/document.py` |
| 文档处理流水线 | 编排文档处理流程：获取内容→结构化→审核→向量化 | `app/services/document_pipeline.py` |
| 切片服务 | 向量切片的 CRUD（新增/编辑/删除/重新嵌入） | `app/services/chunk_service.py` |
| RAG 服务 | PGVectorStore 初始化、文档向量化入库、流式对话问答 | `app/services/rag_service.py` |
| LLM 构建器 | 根据模型配置构建 LlamaIndex LLM/EmbedModel 实例 | `app/services/llm_builder.py` |

**文档处理流程**:

```
文档来源(飞书/上传/URL) → 内容获取 → 结构化(可选) → 审核 → 向量化入库
```

**向量存储**: PGVectorStore（基于 PostgreSQL + pgvector 扩展），支持混合检索（向量 + 全文）。

**切片模式**: 支持 Sentence（语句切分）、Markdown（按标题层级）、Hierarchical（层次化）三种模式。

---

### 四、文档结构化模块

通过 LLM 对原始文档进行结构化处理，提取关键信息并格式化输出。

| 子模块 | 用途 | 关键文件 |
|--------|------|----------|
| 结构化基类 | 定义结构化处理接口和 LLM 调用方法 | `app/services/structuring/base.py` |
| 会议纪要结构化 | 提取会议的议题、结论、待办等结构化信息 | `app/services/structuring/meeting_notes.py` |
| 合作伙伴画像 | 提取合作伙伴关键信息并结构化 | `app/services/structuring/partner_profile.py` |
| 文档模板 | 管理结构化输出的 Markdown 模板 | `app/controllers/doc_template.py` |

---

### 五、飞书深度集成模块

与飞书开放平台深度对接，实现文档读取、机器人消息处理、云文档发布闭环。

| 子模块 | 用途 | 关键文件 |
|--------|------|----------|
| 飞书服务 | 飞书 API 封装（文档读取、Token 管理、文件操作） | `app/services/feishu_service.py` |
| 飞书机器人管理 | 机器人配置（app_id/secret/绑定Agent） | `app/controllers/feishu_bot.py` |
| 长连接客户端 | 通过 WebSocket 长连接接收飞书消息，独立线程+事件循环隔离 | `app/services/feishu_ws_manager.py` |
| 消息处理 | 接收飞书消息 → RAG 检索 → Agent 回复 → 卡片消息回复 | `app/services/document_pipeline.py` |

**消息处理链路**:

```
飞书WS接收 → 同步回调 → asyncio调度至主循环 → RAG对话逻辑 → 卡片消息回复
```

---

### 六、审核管理模块

文档内容审核工作流，支持批准/拒绝/编辑后通过。

| 子模块 | 用途 | 关键文件 |
|--------|------|----------|
| 审核记录 | 记录审核人、动作、意见、编辑内容 | `app/models/rag.py (ReviewRecord)` |
| 审核控制器 | 审核流程业务逻辑 | `app/controllers/review.py` |
| 前端审核页 | 文档内容预览、Markdown 编辑、审核操作 | `web/src/views/rag/review/` |

---

### 七、系统管理模块

| 子模块 | 用途 |
|--------|------|
| 全局配置 | 系统级参数配置（如默认模型、飞书应用信息等） |
| 仪表盘 | 系统概览数据展示 |
| 国际化 | 前端多语言支持 |
| 主题定制 | 亮色/暗色模式切换 |

---

### 八、基础支撑层

| 模块 | 用途 | 关键文件 |
|------|------|----------|
| JWT 认证 | Token 签发/验证/刷新 | `app/core/dependency.py` |
| CRUD 基类 | 通用的增删改查封装，减少样板代码 | `app/core/crud.py` |
| 异常处理 | 全局异常捕获和统一响应格式 | `app/core/exceptions.py` |
| 中间件 | 请求日志、CORS、权限校验 | `app/core/middlewares.py` |
| 后台任务 | 异步后台任务调度 | `app/core/bgtask.py` |
| 应用初始化 | 数据库迁移、初始数据、向量存储、飞书连接初始化 | `app/core/init_app.py` |
| 日志系统 | 基于 loguru 的结构化日志（含文件名/行号） | `app/log/` |
| 配置管理 | Pydantic Settings 管理环境变量和 .env 文件 | `app/settings/` |

---

## 项目目录结构

```
tx_agent_admin/
├── app/                        # 后端应用
│   ├── agents/                 # AI Agent 框架
│   │   ├── agents/             # 具体 Agent 实现
│   │   ├── tools/              # Agent 工具（双框架适配）
│   │   ├── base.py             # Agent 基类
│   │   ├── registry.py         # 注册中心
│   │   └── executor.py         # 执行器
│   ├── api/v1/                 # API 路由层
│   ├── controllers/            # 业务控制器层
│   ├── core/                   # 核心基础设施
│   ├── models/                 # ORM 数据模型
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── services/               # 业务服务层
│   │   ├── structuring/        # 文档结构化处理器
│   │   ├── rag_service.py      # RAG 核心服务
│   │   ├── chunk_service.py    # 切片 CRUD
│   │   ├── feishu_service.py   # 飞书 API
│   │   ├── feishu_ws_manager.py# 飞书长连接
│   │   ├── document_pipeline.py# 文档处理编排
│   │   └── llm_builder.py     # LLM 实例构建
│   ├── settings/               # 配置管理
│   └── utils/                  # 工具函数
├── web/                        # 前端应用
│   └── src/
│       ├── views/
│       │   ├── system/         # 系统管理页面
│       │   ├── rag/            # RAG 知识库管理页面
│       │   ├── workbench/      # 工作台（Agent 对话）
│       │   └── login/          # 登录页
│       ├── api/                # 接口请求封装
│       ├── store/              # Pinia 状态管理
│       └── router/             # Vue Router 动态路由
├── migrations/                 # 数据库迁移文件
├── scripts/                    # 运维脚本
├── tests/                      # 测试用例
├── pyproject.toml              # Python 依赖与构建配置
└── run.py                      # 后端启动入口
```

---

## 数据模型关系

```
LLMProviderConfig (模型配置)
    ├── KnowledgeBase.embedding_model_id (知识库使用的 Embedding 模型)
    └── Agent.chat_model_id (Agent 使用的对话模型)

KnowledgeBase (知识库)
    ├── Document (文档) [1:N]
    │   ├── StructuredResult (结构化结果) [1:1]
    │   └── ReviewRecord (审核记录) [1:N]
    └── Agent (多对多: agent_knowledge_base)

Agent (智能代理)
    ├── DocTemplate (多对多: agent_doc_template)
    ├── FeishuBotConfig (飞书机器人绑定)
    └── Conversation (对话会话) [1:N]
        └── ChatMessage (聊天消息) [1:N]
```

---

## 启动方式

- **后端**: `python run.py`（默认端口 9999）
- **前端**: `cd web && pnpm dev`（开发模式）
- **一键启动**: `start-dev.bat`（Windows 环境）
- **容器部署**: `docker run -p 9999:80`

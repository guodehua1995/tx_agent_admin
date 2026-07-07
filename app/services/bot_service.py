"""飞书机器人消息处理服务。

从 document_pipeline.py 迁出，职责独立。
"""

import json
import time
from datetime import datetime

from langchain_openai import ChatOpenAI
from pypinyin import lazy_pinyin

from app.controllers.ai_config import ai_config_controller
from app.controllers.conversation import conversation_controller
from app.controllers.feishu_bot import feishu_bot_controller
from app.models.admin import User
from app.models.rag import Agent, ChatMessage, FeishuBotConfig
from app.services.feishu_service import FeishuService
from app.utils.password import get_password_hash

from app.log import logger

DEFAULT_MAX_HISTORY_TURNS = 10


class BotService:
    """飞书机器人消息处理服务"""

    async def _get_chat_model(self):
        """获取活跃的 Chat 模型（LangChain ChatOpenAI 实例）"""
        models = await ai_config_controller.get_active_chat_models()
        if not models:
            raise RuntimeError("无可用 Chat 模型")
        cfg = models[0]
        extra = cfg.extra_config or {}
        return ChatOpenAI(
            model=cfg.model_name,
            api_key=cfg.api_key,
            base_url=cfg.api_base_url,
            temperature=extra.get("temperature", 0.7),
            max_tokens=extra.get("max_tokens") or cfg.max_tokens,
        )

    async def _route_agent(self, agent_code: str, llm):
        """按 code 路由到对应的 Agent 实例"""
        from app.agents.registry import AgentRegistry

        agent_cls = AgentRegistry.get(agent_code)
        return agent_cls(llm=llm)

    async def handle_message(
        self, bot_id: int, feishu_open_id: str, chat_id: str, question: str
    ) -> dict:
        """处理飞书机器人消息，按 agent.code 路由到对应 Agent 执行"""
        # 1. bot → agent
        bot = await feishu_bot_controller.get(id=bot_id)
        if not bot.agent_id:
            return {"answer": "该机器人尚未绑定 Agent，请联系管理员配置", "sources": []}
        agent = await Agent.get(id=bot.agent_id)
        if not agent.is_active:
            return {"answer": "该 Agent 已停用", "sources": []}
        if not agent.code:
            return {"answer": "该 Agent 未配置路由标识(code)，无法执行", "sources": []}

        logger.debug("bot get agent: name=%s, code=%s", agent.name, agent.code)

        # 2. 获取 LLM + 路由到 Agent
        try:
            llm = await self._get_chat_model()
            agent_instance = await self._route_agent(agent.code, llm)
        except RuntimeError as e:
            return {"answer": str(e), "sources": []}
        except KeyError:
            return {"answer": f"Agent '{agent.code}' 未注册，请检查 agents/ 目录", "sources": []}

        logger.debug("bot routed to agent: code=%s", agent.code)

        # 3. feishu_open_id → user（不存在则自动创建）
        user = await User.filter(feishu_open_id=feishu_open_id).first()
        if not user:
            user = await self._auto_create_user(bot, feishu_open_id)
            if not user:
                return {"answer": "自动注册失败，请联系管理员手动添加", "sources": []}
        logger.debug("bot get user")

        # 4. 获取/创建 conversation
        conv = await conversation_controller.get_or_create(agent_id=agent.id, user_id=user.id)
        logger.debug("bot get conversation")

        # 5. 加载历史消息
        history = await conversation_controller.get_messages(
            conv.id, limit=DEFAULT_MAX_HISTORY_TURNS * 2, agent_friendly=True
        )
        logger.debug("bot get history")

        # 6. 执行 Agent
        start_time = time.time()
        result = await agent_instance.execute({
            "question": question,
            "history": history,
            "user_id": user.id,
            "agent_id": agent.id,
        })
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.debug("bot agent executed")

        # 7. 保存消息记录
        logger.debug("bot create user message")
        await ChatMessage.create(
            conversation_id=conv.id, type="user", content=question, feishu_message_id=None
        )
        for tc in result.get("tool_calls", []):
            await ChatMessage.create(
                conversation_id=conv.id,
                type="tool_call",
                content=json.dumps(
                    {"tool_name": tc["tool_name"], "tool_input": tc["tool_input"]},
                    ensure_ascii=False,
                ),
            )
            await ChatMessage.create(
                conversation_id=conv.id,
                type="tool_call_result",
                content=json.dumps(
                    {"tool_name": tc["tool_name"], "result": tc["tool_output"]},
                    ensure_ascii=False,
                ),
            )

        logger.debug("bot create assistant message")
        await ChatMessage.create(
            conversation_id=conv.id,
            type="assistant",
            content=result["answer"],
            retrieved_chunks=result.get("sources", []),
            response_time_ms=elapsed_ms,
        )

        tool_msg_count = len(result.get("tool_calls", [])) * 2
        conv.message_count += 2 + tool_msg_count
        conv.last_active_at = datetime.now()
        await conv.save()

        return result

    async def _auto_create_user(self, bot: FeishuBotConfig, feishu_open_id: str) -> User | None:
        """自动创建飞书用户。

        username 取值优先级：飞书邮箱前缀 → 真实姓名拼音 → 兜底 feishu_{open_id后8位}
        """
        feishu_service = FeishuService()

        # 1. 尝试获取飞书用户信息
        user_info = None
        try:
            user_info = await feishu_service.get_user_info(bot.app_id, bot.app_secret, feishu_open_id)
        except Exception:
            logger.warning(f"获取飞书用户信息失败: open_id={feishu_open_id}")

        # 2. 生成 username
        username = self._generate_username(user_info, feishu_open_id)
        username = await self._ensure_unique_username(username)

        # 3. 生成 email
        email = user_info.get("email") if user_info else None
        if not email:
            email = f"{username}@feishu.local"
        email = await self._ensure_unique_email(email)

        # 4. 创建用户
        alias = user_info.get("name") if user_info else None
        try:
            user = await User.create(
                username=username,
                alias=alias,
                email=email,
                password=get_password_hash("123456"),
                is_active=True,
                is_superuser=False,
                feishu_open_id=feishu_open_id,
            )
            logger.info(f"自动创建用户: username={username}, alias={alias}, feishu_open_id={feishu_open_id}")
            return user
        except Exception as e:
            logger.exception(f"自动创建用户失败: open_id={feishu_open_id}: {e}")
            return None

    @staticmethod
    def _generate_username(user_info: dict | None, feishu_open_id: str) -> str:
        """生成 username：邮箱前缀 → 姓名拼音 → 兜底"""
        if user_info and user_info.get("email"):
            return user_info["email"].split("@")[0]
        if user_info and user_info.get("name"):
            return "".join(lazy_pinyin(user_info["name"]))
        return f"feishu_{feishu_open_id[-8:]}"

    @staticmethod
    async def _ensure_unique_username(username: str) -> str:
        """确保 username 唯一，重名时追加序号"""
        base = username
        counter = 1
        while await User.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
        return username

    @staticmethod
    async def _ensure_unique_email(email: str) -> str:
        """确保 email 唯一，重名时追加序号"""
        base = email
        counter = 1
        while await User.filter(email=email).exists():
            local, _, domain = base.partition("@")
            email = f"{local}{counter}@{domain}"
            counter += 1
        return email


bot_service = BotService()
"""飞书机器人消息处理服务。

从 document_pipeline.py 迁出，职责独立。
"""

import json
import time
from datetime import datetime

from app.controllers.conversation import conversation_controller
from app.controllers.feishu_bot import feishu_bot_controller
from app.models.admin import User
from app.models.rag import Agent, ChatMessage, LLMProviderConfig
from app.services.rag_service import rag_service

from app.log import logger


class BotService:
    """飞书机器人消息处理服务"""

    async def handle_message(
        self, bot_id: int, feishu_open_id: str, chat_id: str, question: str
    ) -> dict:
        """处理飞书机器人消息，返回 RAG 问答结果"""
        # 1. bot_config → agent → knowledge_bases
        bot = await feishu_bot_controller.get(id=bot_id)
        if not bot.agent_id:
            return {"answer": "该机器人尚未绑定 Agent，请联系管理员配置", "sources": []}
        agent = await Agent.get(id=bot.agent_id)
        knowledge_bases = await agent.knowledge_bases.all()
        if not knowledge_bases:
            return {"answer": "该 Agent 未关联任何知识库", "sources": []}

        logger.debug("bot get knowledge bases")

        # 2. feishu_open_id → user
        user = await User.filter(feishu_open_id=feishu_open_id).first()
        if not user:
            return {"answer": "您的账号尚未注册，请联系管理员开通后使用", "sources": []}
        logger.debug("bot get user")

        # 3. 获取/创建 conversation
        conv = await conversation_controller.get_or_create(agent_id=agent.id, user_id=user.id)
        logger.debug("bot get conversation")

        # 4. 加载历史消息
        history = await conversation_controller.get_messages(
            conv.id, limit=agent.max_history_turns * 2, agent_friendly=True
        )
        logger.debug("bot get history")

        # 5. RAG 问答
        chat_model = await LLMProviderConfig.get(id=agent.chat_model_id)
        logger.debug("bot get chat model")
        start_time = time.time()
        result = await rag_service.chat(
            question=question,
            history=history,
            knowledge_bases=list(knowledge_bases),
            chat_model_config=chat_model,
            system_prompt=agent.system_prompt,
        )
        logger.debug("bot get rag service")
        elapsed_ms = int((time.time() - start_time) * 1000)

        # 6. 保存消息记录
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
            retrieved_chunks=result["sources"],
            response_time_ms=elapsed_ms,
        )

        tool_msg_count = len(result.get("tool_calls", [])) * 2
        conv.message_count += 2 + tool_msg_count
        conv.last_active_at = datetime.now()
        await conv.save()

        return result


bot_service = BotService()
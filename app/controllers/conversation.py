import json

from app.core.crud import CRUDBase
from app.models.rag import ChatMessage, Conversation
from app.schemas.chat import ChatRequest


class ConversationController(CRUDBase[Conversation, ChatRequest, ChatRequest]):
    def __init__(self):
        super().__init__(model=Conversation)

    async def get_or_create(self, agent_id: int, user_id: int) -> Conversation:
        conv = await self.model.filter(agent_id=agent_id, user_id=user_id).first()
        if not conv:
            conv = self.model(agent_id=agent_id, user_id=user_id)
            await conv.save()
        return conv

    async def get_messages(self, conversation_id: int, limit: int = 50, agent_friendly: bool = False):
        """查询会话消息

        Args:
            conversation_id: 会话ID
            limit: 返回条数
            agent_friendly: 为 True 时将 tool_call/tool_call_result 转为 assistant 类型，
                           返回 [{"type": ..., "content": ...}] 格式的 dict 列表（按时间升序）
        """
        messages = await ChatMessage.filter(conversation_id=conversation_id).order_by("-created_at").limit(limit)
        if not agent_friendly:
            return messages

        result = []
        for msg in reversed(messages):
            msg_type = msg.type
            content = msg.content
            if msg_type in ("tool_call", "tool_call_result"):
                msg_type = "assistant"
                try:
                    data = json.loads(content)
                    if msg.type == "tool_call":
                        content = f"[调用工具: {data.get('tool_name', '')}] {data.get('tool_input', '')}"
                    else:
                        content = f"[工具结果: {data.get('tool_name', '')}] {data.get('result', '')}"
                except (json.JSONDecodeError, KeyError):
                    pass
            result.append({"type": msg_type, "content": content})
        return result


conversation_controller = ConversationController()

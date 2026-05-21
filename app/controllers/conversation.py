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

    async def get_messages(self, conversation_id: int, limit: int = 50):
        return await ChatMessage.filter(conversation_id=conversation_id).order_by("-created_at").limit(limit)


conversation_controller = ConversationController()

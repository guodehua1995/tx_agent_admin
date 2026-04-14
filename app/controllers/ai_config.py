from app.core.crud import CRUDBase
from app.models.rag import LLMProviderConfig
from app.schemas.ai_config import LLMProviderConfigCreate, LLMProviderConfigUpdate


class LLMProviderConfigController(CRUDBase[LLMProviderConfig, LLMProviderConfigCreate, LLMProviderConfigUpdate]):
    def __init__(self):
        super().__init__(model=LLMProviderConfig)

    async def get_active_chat_models(self):
        return await self.model.filter(is_active=True, is_embedding=False).all()

    async def get_active_embedding_models(self):
        return await self.model.filter(is_active=True, is_embedding=True).all()


ai_config_controller = LLMProviderConfigController()

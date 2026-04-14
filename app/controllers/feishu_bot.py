from app.core.crud import CRUDBase
from app.models.rag import FeishuBotConfig
from app.schemas.feishu import FeishuBotConfigCreate, FeishuBotConfigUpdate


class FeishuBotController(CRUDBase[FeishuBotConfig, FeishuBotConfigCreate, FeishuBotConfigUpdate]):
    def __init__(self):
        super().__init__(model=FeishuBotConfig)

    async def get_by_app_id(self, app_id: str):
        return await self.model.filter(app_id=app_id).first()


feishu_bot_controller = FeishuBotController()

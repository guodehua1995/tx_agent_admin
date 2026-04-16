from collections import defaultdict

from app.core.crud import CRUDBase
from app.models.global_config import GlobalConfig
from app.schemas.global_config import GlobalConfigCreate, GlobalConfigUpdate


class GlobalConfigController(CRUDBase[GlobalConfig, GlobalConfigCreate, GlobalConfigUpdate]):
    def __init__(self):
        super().__init__(model=GlobalConfig)

    async def get_all_grouped(self) -> dict:
        """按 config_group 分组返回所有配置"""
        objs = await self.model.all().order_by("config_group", "config_key")
        grouped = defaultdict(list)
        for obj in objs:
            grouped[obj.config_group].append(await obj.to_dict())
        return dict(grouped)

    async def batch_update(self, items: list[dict]) -> int:
        """批量更新配置值，返回更新条数"""
        count = 0
        for item in items:
            await self.update(id=item["id"], obj_in={"config_value": item["config_value"]})
            count += 1
        return count

    async def get_by_key(self, key: str):
        """根据 config_key 获取配置，供其他服务调用"""
        return await self.model.get_or_none(config_key=key)


global_config_controller = GlobalConfigController()

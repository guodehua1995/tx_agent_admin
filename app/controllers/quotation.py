from tortoise.expressions import Q

from app.core.crud import CRUDBase
from app.models.quotation import (
    Client,
    QuotationItem,
    QuotationRule,
    VersionArchive,
)
from app.schemas.quotation import ClientCreate, ClientUpdate


class ClientController(CRUDBase[Client, ClientCreate, ClientUpdate]):
    def __init__(self):
        super().__init__(model=Client)

    async def get_by_name(self, name: str):
        """精确匹配甲方名称"""
        return await self.model.filter(name=name, is_deleted=False).first()

    async def search_by_keyword(self, keyword: str, limit: int = 10):
        """模糊匹配甲方"""
        return await self.model.filter(
            Q(name__icontains=keyword) | Q(short_name__icontains=keyword),
            is_deleted=False,
        ).limit(limit)
    async def get_by_id(self, id: int):
        """精确匹配甲方ID"""
        return await self.model.filter(id=id, is_deleted=False).first()


class QuotationRuleController(CRUDBase[QuotationRule, dict, dict]):
    def __init__(self):
        super().__init__(model=QuotationRule)

    async def get_active_rule(self, client_id: int):
        """获取甲方当前生效规则"""
        return await self.model.filter(
            client_id=client_id, status="active", is_deleted=False
        ).first()

    async def get_next_version(self, client_id: int) -> int:
        """获取甲方下一个版本号"""
        last = await self.model.filter(
            client_id=client_id, is_deleted=False
        ).order_by("-version").first()
        return (last.version + 1) if last else 1


class QuotationItemController(CRUDBase[QuotationItem, dict, dict]):
    def __init__(self):
        super().__init__(model=QuotationItem)

    async def get_tree_by_rule(self, rule_id: int) -> list[dict]:
        """获取规则下的明细树（一级 → 二级）"""
        items = await self.model.filter(rule_id=rule_id, is_deleted=False).order_by("sort_order")
        top_items = [i for i in items if i.parent_id is None]
        result = []
        for top in top_items:
            d = await top.to_dict()
            d["children"] = [
                await child.to_dict()
                for child in items if child.parent_id == top.id
            ]
            result.append(d)
        return result


client_controller = ClientController()
quotation_rule_controller = QuotationRuleController()
quotation_item_controller = QuotationItemController()

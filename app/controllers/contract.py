"""合同管理 Controller 层"""

from tortoise.expressions import Q

from app.core.crud import CRUDBase
from app.models.contract import Contract, ContractClause, ContractType
from app.schemas.contract import ContractCreate, ContractUpdate


class ContractTypeController(CRUDBase[ContractType, dict, dict]):
    def __init__(self):
        super().__init__(model=ContractType)

    async def get_by_code(self, code: str):
        return await self.model.filter(code=code, is_deleted=False).first()

    async def get_by_name(self, name: str):
        return await self.model.filter(name=name, is_deleted=False).first()

    async def list_active(self):
        return await self.model.filter(is_active=True, is_deleted=False).all()

    async def search_by_keyword(self, keyword: str, limit: int = 10):
        return await self.model.filter(
            Q(name__icontains=keyword) | Q(code__icontains=keyword),
            is_deleted=False,
        ).limit(limit)


class ContractController(CRUDBase[Contract, ContractCreate, ContractUpdate]):
    def __init__(self):
        super().__init__(model=Contract)

    async def get_by_document_id(self, document_id: int):
        return await self.model.filter(
            document_id=document_id, is_deleted=False,
        ).first()

    async def search(
        self,
        keyword: str | None = None,
        party_a: str | None = None,
        party_b: str | None = None,
        contract_type_id: int | None = None,
        start_date=None,
        end_date=None,
        page: int = 1,
        page_size: int = 20,
    ):
        q = Q(is_deleted=False)
        if keyword:
            q &= Q(project_name__icontains=keyword)
        if contract_type_id:
            q &= Q(contract_type_id=contract_type_id)
        if start_date:
            q &= Q(signing_date__gte=start_date)
        if end_date:
            q &= Q(signing_date__lte=end_date)

        # 甲方/乙方通过关联查询
        if party_a or party_b:
            from app.models.quotation import Client
            client_ids = []
            client_q = Q(is_deleted=False)
            if party_a:
                client_q |= Q(name__icontains=party_a) | Q(short_name__icontains=party_a)
            if party_b:
                client_q |= Q(name__icontains=party_b) | Q(short_name__icontains=party_b)
            clients = await Client.filter(client_q).all()
            client_ids = [c.id for c in clients]
            if client_ids:
                if party_a and party_b:
                    q &= Q(party_a_client_id__in=client_ids) | Q(party_b_client_id__in=client_ids)
                elif party_a:
                    q &= Q(party_a_client_id__in=client_ids)
                elif party_b:
                    q &= Q(party_b_client_id__in=client_ids)

        total, items = await self.list(
            page=page, page_size=page_size, search=q,
            order=["-created_at"],
        )
        return total, items

    async def search_by_summary(
        self,
        keyword: str | None = None,
        party_a: str | None = None,
        party_b: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ):
        """按合同摘要搜索"""
        q = Q(is_deleted=False, summary__not_isnull=True)
        if keyword:
            q &= Q(summary__icontains=keyword)
        if party_a or party_b:
            from app.models.quotation import Client
            client_q = Q(is_deleted=False)
            if party_a:
                client_q |= Q(name__icontains=party_a) | Q(short_name__icontains=party_a)
            if party_b:
                client_q |= Q(name__icontains=party_b) | Q(short_name__icontains=party_b)
            clients = await Client.filter(client_q).all()
            client_ids = [c.id for c in clients]
            if client_ids:
                if party_a and party_b:
                    q &= Q(party_a_client_id__in=client_ids) | Q(party_b_client_id__in=client_ids)
                elif party_a:
                    q &= Q(party_a_client_id__in=client_ids)
                elif party_b:
                    q &= Q(party_b_client_id__in=client_ids)

        total, items = await self.list(
            page=page, page_size=page_size, search=q,
            order=["-created_at"],
        )
        return total, items

    async def get_expiring_contracts(self, days: int = 30):
        """获取即将到期的合同"""
        from datetime import datetime, timedelta
        now = datetime.now()
        deadline = now + timedelta(days=days)
        return await self.model.filter(
            expiry_date__gte=now,
            expiry_date__lte=deadline,
            is_deleted=False,
        ).all()


class ContractClauseController(CRUDBase[ContractClause, dict, dict]):
    def __init__(self):
        super().__init__(model=ContractClause)

    async def get_by_contract(self, contract_id: int):
        """获取合同的所有条款（按排序号，排除待删除）"""
        return await self.model.filter(
            contract_id=contract_id, is_deleted=False,
        ).exclude(summary_status="pending_delete").order_by("sort_order").all()

    async def get_tree_by_contract(self, contract_id: int):
        """获取合同的条款树"""
        clauses = await self.get_by_contract(contract_id)
        return self._build_tree(clauses)

    async def search_clauses(
        self,
        keyword: str | None = None,
        clause_title: str | None = None,
        contract_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ):
        """搜索条款"""
        q = Q(is_deleted=False)
        q &= ~Q(summary_status="pending_delete")
        if contract_id:
            q &= Q(contract_id=contract_id)
        if keyword:
            q &= Q(original_text__icontains=keyword)
        if clause_title:
            q &= Q(clause_title__icontains=clause_title)

        query = self.model.filter(q)
        total = await query.count()
        items = await query.offset((page - 1) * page_size).limit(page_size).order_by("contract_id", "sort_order")
        return total, items

    async def find_similar_clauses(
        self,
        clause_title: str,
        contract_ids: list[int] | None = None,
        party_a: str | None = None,
        party_b: str | None = None,
        limit: int = 20,
    ):
        """查找同类条款（跨合同）"""
        q = Q(is_deleted=False, clause_title__icontains=clause_title)
        q &= ~Q(summary_status="pending_delete")
        if contract_ids:
            q &= Q(contract_id__in=contract_ids)
        if party_a or party_b:
            from app.models.quotation import Client
            client_q = Q(is_deleted=False)
            if party_a:
                client_q &= Q(name__icontains=party_a) | Q(short_name__icontains=party_a)
            if party_b:
                client_q &= Q(name__icontains=party_b) | Q(short_name__icontains=party_b)
            clients = await Client.filter(client_q).all()
            client_ids = [c.id for c in clients]
            if client_ids:
                # 需要关联 Contract 表
                from app.models.contract import Contract
                contracts = await Contract.filter(
                    Q(party_a_client_id__in=client_ids) | Q(party_b_client_id__in=client_ids),
                    is_deleted=False,
                ).all()
                c_ids = [c.id for c in contracts]
                if c_ids:
                    q &= Q(contract_id__in=c_ids)
                else:
                    return 0, []

        query = self.model.filter(q)
        total = await query.count()
        items = await query.limit(limit).order_by("contract_id", "sort_order")
        return total, items

    async def get_clause_with_context(self, clause_id: int, context_size: int = 2):
        """获取条款及其上下文（前后相邻条款）"""
        clause = await self.model.get(id=clause_id, is_deleted=False)
        if not clause or clause.summary_status == "pending_delete":
            return None, [], []

        sort_order = clause.sort_order
        contract_id = clause.contract_id

        prev_clauses = await self.model.filter(
            contract_id=contract_id, is_deleted=False,
            sort_order__lt=sort_order,
        ).exclude(summary_status="pending_delete").order_by("-sort_order").limit(context_size)

        next_clauses = await self.model.filter(
            contract_id=contract_id, is_deleted=False,
            sort_order__gt=sort_order,
        ).exclude(summary_status="pending_delete").order_by("sort_order").limit(context_size)

        return clause, list(prev_clauses), list(next_clauses)

    def _build_tree(self, clauses: list) -> list[dict]:
        """构建条款树"""
        clause_map = {c.id: c for c in clauses}
        roots = []
        for c in clauses:
            if c.parent_id and c.parent_id in clause_map:
                parent = clause_map[c.parent_id]
                if not hasattr(parent, "_children"):
                    parent._children = []
                parent._children.append(c)
            else:
                roots.append(c)
        return roots


contract_type_controller = ContractTypeController()
contract_controller = ContractController()
contract_clause_controller = ContractClauseController()
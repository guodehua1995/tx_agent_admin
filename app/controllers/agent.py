from typing import List

from app.core.crud import CRUDBase
from app.models.rag import Agent, KnowledgeBase
from app.schemas.agents import AgentCreate, AgentUpdate


class AgentController(CRUDBase[Agent, AgentCreate, AgentUpdate]):
    def __init__(self):
        super().__init__(model=Agent)

    async def update_knowledge_bases(self, agent: Agent, kb_ids: List[int]) -> None:
        await agent.knowledge_bases.clear()
        for kb_id in kb_ids:
            kb_obj = await KnowledgeBase.filter(id=kb_id).first()
            if kb_obj:
                await agent.knowledge_bases.add(kb_obj)

    async def create(self, obj_in) -> Agent:
        if isinstance(obj_in, dict):
            obj_dict = obj_in
        else:
            obj_dict = obj_in.model_dump(exclude={"knowledge_base_ids"})
        obj = self.model(**obj_dict)
        await obj.save()
        return obj


agent_controller = AgentController()

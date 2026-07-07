from app.core.crud import CRUDBase
from app.models.rag import Agent
from app.schemas.agents import AgentCreate, AgentUpdate


class AgentController(CRUDBase[Agent, AgentCreate, AgentUpdate]):
    def __init__(self):
        super().__init__(model=Agent)


agent_controller = AgentController()

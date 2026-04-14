from app.core.crud import CRUDBase
from app.models.rag import KnowledgeBase
from app.schemas.knowledge_bases import KnowledgeBaseCreate, KnowledgeBaseUpdate


class KnowledgeBaseController(CRUDBase[KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseUpdate]):
    def __init__(self):
        super().__init__(model=KnowledgeBase)


knowledge_base_controller = KnowledgeBaseController()

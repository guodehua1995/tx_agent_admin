from app.core.crud import CRUDBase
from app.models.rag import Document
from app.schemas.documents import DocumentCreate, DocumentUpdate


class DocumentController(CRUDBase[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self):
        super().__init__(model=Document)

    async def get_by_status(self, status: str):
        return await self.model.filter(status=status).all()


document_controller = DocumentController()

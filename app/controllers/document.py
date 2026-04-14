from app.core.crud import CRUDBase
from app.models.rag import Document, DocumentType
from app.schemas.documents import DocumentCreate, DocumentTypeCreate, DocumentTypeUpdate, DocumentUpdate


class DocumentTypeController(CRUDBase[DocumentType, DocumentTypeCreate, DocumentTypeUpdate]):
    def __init__(self):
        super().__init__(model=DocumentType)

    async def get_by_code(self, code: str):
        return await self.model.filter(code=code).first()


class DocumentController(CRUDBase[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self):
        super().__init__(model=Document)

    async def get_by_status(self, status: str):
        return await self.model.filter(status=status).all()


document_type_controller = DocumentTypeController()
document_controller = DocumentController()

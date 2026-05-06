from app.core.crud import CRUDBase
from app.models.rag import DocTemplate
from app.schemas.doc_templates import DocTemplateCreate, DocTemplateUpdate


class DocTemplateController(CRUDBase[DocTemplate, DocTemplateCreate, DocTemplateUpdate]):
    def __init__(self):
        super().__init__(model=DocTemplate)

    async def soft_delete(self, id: int) -> None:
        obj = await self.get(id=id)
        obj.is_deleted = True
        await obj.save()


doc_template_controller = DocTemplateController()

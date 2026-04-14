from app.core.crud import CRUDBase
from app.models.rag import ReviewRecord
from app.schemas.reviews import ReviewSubmit


class ReviewController(CRUDBase[ReviewRecord, ReviewSubmit, ReviewSubmit]):
    def __init__(self):
        super().__init__(model=ReviewRecord)

    async def get_by_document(self, document_id: int):
        return await self.model.filter(document_id=document_id).order_by("-created_at").all()


review_controller = ReviewController()

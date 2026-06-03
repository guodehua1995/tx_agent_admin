"""飞书文件夹监听 Controller"""

from app.core.crud import CRUDBase
from app.models.rag import FeishuFolderWatch
from app.schemas.feishu_folders import FeishuFolderCreate, FeishuFolderUpdate


class FeishuFolderController(
    CRUDBase[FeishuFolderWatch, FeishuFolderCreate, FeishuFolderUpdate]
):
    def __init__(self):
        super().__init__(model=FeishuFolderWatch)

    async def soft_delete(self, id: int) -> None:
        obj = await self.get(id=id)
        obj.is_deleted = True
        obj.is_active = False
        await obj.save()


feishu_folder_controller = FeishuFolderController()

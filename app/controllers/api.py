from fastapi.routing import APIRoute

from app.core.crud import CRUDBase
from app.log import logger
from app.models.admin import Api
from app.schemas.apis import ApiCreate, ApiUpdate


class ApiController(CRUDBase[Api, ApiCreate, ApiUpdate]):
    def __init__(self):
        super().__init__(model=Api)

    async def refresh_api(self):
        """扫描 FastAPI 路由，同步到 Api 表（RBAC 权限绑定用）。

        优化：一次查询全量 API，内存 diff，仅变更项写入，避免 N+1。
        """
        from app import app

        # 1. 收集当前所有有鉴权的路由
        current: dict[tuple[str, str], dict] = {}
        for route in app.routes:
            if not isinstance(route, APIRoute) or len(route.dependencies) == 0:
                continue
            method = list(route.methods)[0]
            path = route.path_format
            tags = list(route.tags)[0] if route.tags else (
                path.split("/")[1] if len(path.split("/")) > 1 else "未分类"
            )
            current[(method, path)] = {
                "method": method,
                "path": path,
                "summary": route.summary,
                "tags": tags,
            }

        # 2. 一次查询全量已有 API
        existing = await Api.all()
        existing_map: dict[tuple[str, str], Api] = {
            (api.method, api.path): api for api in existing
        }

        created = 0
        updated = 0
        deleted = 0

        # 3. 新增 / 更新
        for key, data in current.items():
            api_obj = existing_map.get(key)
            if api_obj is None:
                await Api.create(**data)
                created += 1
                logger.debug(f"[refresh_api] created {data['method']} {data['path']}")
            elif api_obj.summary != data["summary"] or api_obj.tags != data["tags"]:
                await api_obj.update_from_dict(data).save()
                updated += 1
                logger.debug(f"[refresh_api] updated {data['method']} {data['path']}")

        # 4. 删除废弃 API
        for key, api_obj in existing_map.items():
            if key not in current:
                await api_obj.delete()
                deleted += 1
                logger.debug(f"[refresh_api] deleted {api_obj.method} {api_obj.path}")

        if created or updated or deleted:
            logger.info(
                f"[refresh_api] routes={len(current)} created={created} "
                f"updated={updated} deleted={deleted}"
            )
        else:
            logger.debug(f"[refresh_api] no changes, routes={len(current)}")


api_controller = ApiController()

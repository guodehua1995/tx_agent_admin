from contextlib import asynccontextmanager

from fastapi import FastAPI
from tortoise import Tortoise

from app.core.exceptions import SettingNotFound
from app.core.init_app import (
    init_data,
    make_middlewares,
    register_exceptions,
    register_routers,
)

try:
    from app.settings.config import settings
except ImportError:
    raise SettingNotFound("Can not import settings")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_data()
    yield
    from app.services.feishu_ws_manager import feishu_ws_manager
    await feishu_ws_manager.stop_all()
    await Tortoise.close_connections()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_TITLE,
        description=settings.APP_DESCRIPTION,
        version=settings.VERSION,
        openapi_url="/openapi.json",
        middleware=make_middlewares(),
        lifespan=lifespan,
    )
    register_exceptions(app)
    register_routers(app, prefix="/api")

    # 挂载静态文件目录，提供 /media/ 下的文件 HTTP 访问
    from pathlib import Path
    from starlette.staticfiles import StaticFiles

    media_dir = Path(settings.MEDIA_ROOT)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount(settings.MEDIA_URL_PREFIX, StaticFiles(directory=str(media_dir)), name="media")

    return app


app = create_app()

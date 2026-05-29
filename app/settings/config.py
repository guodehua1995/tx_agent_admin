import os
import typing

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 环境标识
    ENV: str = "development"
    DEBUG: bool = True

    VERSION: str = "0.1.0"
    APP_TITLE: str = "Vue FastAPI Admin"
    PROJECT_NAME: str = "Vue FastAPI Admin"
    APP_DESCRIPTION: str = "Description"

    CORS_ORIGINS: typing.List = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: typing.List = ["*"]
    CORS_ALLOW_HEADERS: typing.List = ["*"]
    CORS_EXPOSE_HEADERS: typing.List = ["*"]  # SSE 需要暴露 headers

    PROJECT_ROOT: str = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    BASE_DIR: str = os.path.abspath(os.path.join(PROJECT_ROOT, os.pardir))
    LOGS_ROOT: str = os.path.join(BASE_DIR, "app/logs")
    SECRET_KEY: str = "3488a63e1765035d386f05409663f55c83bfae3b3c61a932744b20ad14244dcf"  # openssl rand -hex 32
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 day

    # 数据库配置 - 从环境变量读取
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_NAME: str = "tx_agent_admin"

    @property
    def TORTOISE_ORM(self) -> dict:
        return {
            "connections": {
                "postgres": {
                    "engine": "tortoise.backends.asyncpg",
                    "credentials": {
                        "host": self.DB_HOST,
                        "port": self.DB_PORT,
                        "user": self.DB_USER,
                        "password": self.DB_PASSWORD,
                        "database": self.DB_NAME,
                    },
                },
            },
            "apps": {
                "models": {
                    "models": ["app.models", "aerich.models"],
                    "default_connection": "postgres",
                },
            },
            "use_tz": False,
            "timezone": "Asia/Shanghai",
        }

    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # 飞书
    FEISHU_BASE_URL: str = "https://open.feishu.cn/open-apis"
    FEISHU_STRUCTURED_FOLDER_TOKEN: str = ""
    FEISHU_VERIFY_SSL: bool = True
    FEISHU_DOC_BOT_APPID: str = ""
    FEISHU_DOC_BOT_APPSECRET: str = ""
    

    # Gotenberg 文档转换服务
    GOTENBERG_URL: str = "http://localhost:3001"

    # 文件存储
    FILE_STORAGE_BACKEND: str = "tos"  # local | tos
    MEDIA_ROOT: str = os.path.join(BASE_DIR, "media")
    MEDIA_URL_PREFIX: str = "/media"

    # 火山引擎 TOS 对象存储（FILE_STORAGE_BACKEND=tos 时启用）
    TOS_ENDPOINT: str = ""          # e.g. tos-cn-beijing.volces.com
    TOS_REGION: str = ""            # e.g. cn-beijing
    TOS_ACCESS_KEY: str = ""
    TOS_SECRET_KEY: str = ""
    TOS_BUCKET: str = ""

    # 飞书 IM 图片 image_key 缓存（避免同一截图重复上传）
    IMAGE_KEY_CACHE_BACKEND: str = "memory"  # memory | redis（redis 待实现）
    IMAGE_KEY_CACHE_MAX_SIZE: int = 1024
    IMAGE_KEY_CACHE_TTL: int = 7 * 24 * 3600  # 0 表示不过期

    # LlamaIndex / RAG
    VECTOR_STORE_TABLE_NAME: str = "knowledge_chunks"
    DEFAULT_EMBEDDING_DIMENSION: int = 2048

    # LangChain / LLM
    LLM_PROVIDER: str = "openai"
    LLM_MODEL_NAME: str = "gpt-4"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

from enum import Enum, StrEnum


class EnumBase(Enum):
    @classmethod
    def get_member_values(cls):
        return [item.value for item in cls._member_map_.values()]

    @classmethod
    def get_member_names(cls):
        return [name for name in cls._member_names_]


class MethodType(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


# ========== RAG 模块枚举 ==========


class DocumentSourceType(StrEnum):
    FEISHU_DOC = "feishu_doc"
    FILE_UPLOAD = "file_upload"
    WEB_URL = "web_url"


class DocumentStatus(StrEnum):
    PENDING_FETCH = "pending_fetch"
    FETCHED = "fetched"
    STRUCTURING = "structuring"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    VECTORIZING = "vectorizing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class FeishuPublishStatus(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class LLMProviderType(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    VOLCENGINE = "volcengine"
    AZURE_OPENAI = "azure_openai"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class RetrievalMode(StrEnum):
    VECTOR = "vector"
    HYBRID = "hybrid"


class ChunkMode(StrEnum):
    SENTENCE = "sentence"
    MARKDOWN = "markdown"
    HIERARCHICAL = "hierarchical"

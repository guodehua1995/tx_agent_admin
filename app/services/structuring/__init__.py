import logging
from dataclasses import dataclass, field
from typing import Optional

from app.models.rag import LLMProviderConfig

logger = logging.getLogger(__name__)

STRUCTURING_HANDLERS: dict[str, type] = {}


@dataclass
class StructuringResult:
    content: str
    prompt_used: Optional[str] = None
    token_usage: Optional[dict] = field(default_factory=dict)


def register_handler(code: str):
    """装饰器: 注册结构化处理函数"""

    def decorator(cls):
        STRUCTURING_HANDLERS[code] = cls
        return cls

    return decorator


async def run_structuring(doc_type_code: str, raw_content: str, model_config: LLMProviderConfig) -> StructuringResult:
    """根据文档类型 code 分发到对应处理函数"""
    handler_cls = STRUCTURING_HANDLERS.get(doc_type_code)
    if not handler_cls:
        raise ValueError(f"未注册的结构化处理器: {doc_type_code}")
    handler = handler_cls(model_config)
    return await handler.process(raw_content)


# 导入处理器以触发注册
from . import meeting_notes, partner_profile  # noqa: E402, F401

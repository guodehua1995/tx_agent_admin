"""切片层 (slicing)

将审核通过的整篇文档内容切分为入库单元（条款/段落/页等），按 doc_type_code 路由到对应处理器。
注意：本层属于「切片」，与「提取（按页提取原文）」是两个独立阶段。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.models.rag import DocumentPage, LLMProviderConfig

logger = logging.getLogger(__name__)

SLICING_HANDLERS: dict[str, type] = {}


@dataclass
class SlicingResult:
    content: str
    prompt_used: Optional[str] = None
    token_usage: Optional[dict] = field(default_factory=dict)


def register_handler(code: str):
    """装饰器: 注册切片处理函数"""

    def decorator(cls):
        SLICING_HANDLERS[code] = cls
        return cls

    return decorator


async def run_slicing(
    doc_type_code: str,
    raw_content: str,
    model_config: LLMProviderConfig,
    pages: Optional[list[DocumentPage]] = None,
) -> SlicingResult:
    """根据文档类型 code 分发到对应切片处理器"""
    handler_cls = SLICING_HANDLERS.get(doc_type_code)
    if not handler_cls:
        raise ValueError(f"未注册的切片处理器: {doc_type_code}")
    handler = handler_cls(model_config)
    return await handler.process(raw_content, pages=pages)


# 导入处理器以触发注册
from . import meeting_notes, partner_profile, contract  # noqa: E402, F401

"""提取层 (extraction)

文档上传后的"提取内容"阶段：根据 doc_type_code 路由到对应处理器，将原始来源（飞书/上传文件/网页）
转换为 doc.content (markdown) 与可选的 DocumentPage 记录。

注意：本层属于「提取」，与「切片」是两个独立阶段。
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from app.models.rag import Document

logger = logging.getLogger(__name__)

EXTRACTION_HANDLERS: dict[str, type] = {}


@dataclass
class ExtractionResult:
    content: str                                  # 提取后的整文 markdown（写入 doc.content）
    pages: list[Any] = field(default_factory=list)  # ConvertedPage 列表（已落库则可不再返回）
    source_meta_patch: dict = field(default_factory=dict)  # 增量回写到 doc.source_meta 的字段


def register_extractor(code: str):
    """装饰器: 注册提取处理函数（按 doc_type_code）"""

    def decorator(cls):
        EXTRACTION_HANDLERS[code] = cls
        return cls

    return decorator


async def run_extraction(doc: Document) -> ExtractionResult:
    """根据 doc.doc_type_code 分发到对应提取处理器"""
    handler_cls = EXTRACTION_HANDLERS.get(doc.doc_type_code)
    if not handler_cls:
        raise ValueError(f"未注册的提取处理器: {doc.doc_type_code}")
    return await handler_cls().extract(doc)


# 导入处理器以触发注册
from . import contract, feishu_doc, ppt  # noqa: E402, F401

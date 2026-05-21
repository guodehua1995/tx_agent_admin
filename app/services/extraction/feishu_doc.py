"""飞书文档提取器：拉取 docx/wiki/sheet 文本 → agent 转 markdown。"""

from app.models.enums import DocumentSourceType
from app.models.rag import Document
from app.services.agent_service import agent_service
from app.services.feishu_service import feishu_service

from . import ExtractionResult, register_extractor
from .base import BaseExtractor


@register_extractor("feishu_doc")
class FeishuDocExtractor(BaseExtractor):
    """飞书文档提取：调飞书 API 拉取文本 → agent 转 markdown"""

    async def extract(self, doc: Document) -> ExtractionResult:
        if doc.source_type != DocumentSourceType.FEISHU_DOC:
            raise ValueError(
                f"feishu_doc 类型仅支持飞书来源，当前 source_type={doc.source_type}"
            )

        meta = doc.source_meta or {}
        feishu_url = meta.get("feishu_url", "")
        doc_token, doc_type = feishu_service.parse_feishu_url(feishu_url)

        # file 类型应改用合同/PPT 等具体提取器（按 doc_type_code 路由）；slides 不支持
        if doc_type == "slide":
            raise ValueError(
                "飞书云文档PPT(slides类型)不支持通过API导出。"
                "请使用飞书文件格式的链接(https://xxx.feishu.cn/file/xxx)"
            )
        if doc_type == "file":
            raise ValueError(
                "飞书 file 类型链接请使用对应的文档类型（合同/PPT 等），"
                "feishu_doc 类型仅处理 docx/wiki/sheet。"
            )

        access_token, _ = await self._get_feishu_access_token()
        content = await feishu_service.fetch_document_content(doc_token, doc_type, access_token)
        agent_result = await agent_service.run_agent(
            "doc_to_markdown", {"document_content": content}
        )
        if not agent_result["success"]:
            raise ValueError("Agent execution failed: agent_name=doc_to_markdown")

        return ExtractionResult(
            content=agent_result["markdown_content"],
            source_meta_patch={
                "feishu_doc_token": doc_token,
                "feishu_doc_type": doc_type,
            },
        )

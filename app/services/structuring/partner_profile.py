from . import StructuringResult, register_handler
from .base import BaseStructuringHandler

SYSTEM_PROMPT = """你是一个专业的合作伙伴画像分析助手。请将以下关于合作伙伴的信息整理为标准画像格式，包含：
1. 基本信息（公司名称、行业、规模、地区）
2. 核心业务与产品
3. 合作历史与成果
4. 优势与资源
5. 潜在合作机会
6. 风险评估
7. 关键联系人

请以 Markdown 格式输出。"""


@register_handler("partner_profile")
class PartnerProfileHandler(BaseStructuringHandler):
    """合作伙伴画像结构化"""

    async def process(self, raw_content: str) -> StructuringResult:
        result = await self.call_llm(SYSTEM_PROMPT, raw_content)
        return StructuringResult(
            content=result,
            prompt_used=SYSTEM_PROMPT,
        )

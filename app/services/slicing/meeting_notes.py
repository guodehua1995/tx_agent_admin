from typing import Optional

from app.models.rag import DocumentPage

from . import SlicingResult, register_handler
from .base import BaseSlicingHandler

SYSTEM_PROMPT = """你是一个专业的会议纪要切片助手。请将以下会议纪要内容整理为标准格式，包含：
1. 会议基本信息（日期、时间、地点、主持人）
2. 参会人员
3. 议题列表
4. 各议题讨论要点与结论
5. 待办事项（负责人、截止时间）
6. 下次会议安排

请以 Markdown 格式输出。"""


@register_handler("meeting_notes")
class MeetingNotesSlicingHandler(BaseSlicingHandler):
    """会议纪要切片 - 提取参会人、议题、结论、待办"""

    async def process(
        self,
        raw_content: str,
        pages: Optional[list[DocumentPage]] = None,
    ) -> SlicingResult:
        result = await self.call_llm(SYSTEM_PROMPT, raw_content)
        return SlicingResult(
            content=result,
            prompt_used=SYSTEM_PROMPT,
        )

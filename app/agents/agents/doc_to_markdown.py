"""
文档转 Markdown Agent

将飞书云文档的原始纯文本内容转换为标准 Markdown 格式
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from app.log import logger

from ..base import BaseAgent
from ..registry import register_agent

SYSTEM_PROMPT = """你是一个专业的文档格式化专家。你的任务将飞书云文档的原始纯文本内容转换为标准 Markdown 格式。

要求：
1. 识别并保持文档的层级结构（标题、子标题等）
2. 正确格式化列表（有序、无序）
3. 识别并格式化表格
4. 保持代码块的语法高亮标记
5. 正确处理引用、链接等元素
6. 去除冗余的空行和空白字符
7. 保持原文的语义完整性，不要删改内容

输出要求：
- 只输出 Markdown 格式的内容
- 不要添加额外解释
- 确保 Markdown 语法正确"""



@register_agent
class DocToMarkdownAgent(BaseAgent):
    """文档转 Markdown Agent"""

    name = "doc_to_markdown"
    description = "将飞书文档原始内容转换为标准 Markdown 格式"
    version = "1.0.0"

    def _build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                (
                    "human",
                    "请将以下文档内容转换为标准 Markdown 格式：\n\n{document_content}",
                ),
            ]
        )

    async def execute(self, input_data: dict, **kwargs) -> dict:

        document_content = input_data.get("document_content", "")

        if not document_content:
            raise ValueError("document_content is required")
        logger.debug(f"Document Content: {document_content}")
        # 构建链
        chain = self.prompt | self.llm | StrOutputParser()

        # 执行
        markdown_content = await chain.ainvoke({"document_content": document_content})
        logger.debug(f"Markdown Content: {markdown_content}")
        return {
            "success": True,
            "markdown_content": markdown_content,
            "original_length": len(document_content),
            "markdown_length": len(markdown_content),
        }

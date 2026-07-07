"""
Agent 基类定义

所有 Agent 都需要继承此基类并实现相应方法
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import ChatPromptTemplate


class BaseAgent(ABC):
    """Agent 基类"""

    name: str = ""  # Agent 唯一标识
    description: str = ""  # Agent 描述
    version: str = "1.0.0"

    def __init__(self, llm: Optional[BaseLanguageModel] = None):
        self.llm = llm
        self.prompt = self._build_prompt()

    def _build_prompt(self) -> ChatPromptTemplate:
        """构建提示词模板（默认空实现，子类可按需覆盖）"""
        return ChatPromptTemplate.from_messages([
            ("system", ""),
        ])

    @abstractmethod
    async def execute(self, input_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """执行 Agent 任务"""
        pass

    def set_llm(self, llm: BaseLanguageModel):
        """动态设置 LLM"""
        self.llm = llm

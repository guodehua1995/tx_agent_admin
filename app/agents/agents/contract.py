"""合同 Agent（Deep Agent）

合同管理对话 Agent，负责合同搜索、统计、条款查询、摘要搜索、条款对比等。
与飞书 Bot 绑定，提供合同答疑能力。
"""

from typing import Any

from deepagents import create_deep_agent
from langchain_core.prompts import ChatPromptTemplate

from app.log import logger
from app.agents.tools.contract_tools import (
    CompareClauseFulltextToolProvider,
    CompareClauseSummariesToolProvider,
    ContractClauseSearchToolProvider,
    ContractSearchToolProvider,
    ContractStatsToolProvider,
    ContractSummarySearchToolProvider,
    FindSimilarContractsToolProvider,
)

from ..base import BaseAgent
from ..registry import register_agent

SYSTEM_PROMPT = """你是一个专业的合同管理助手。你可以帮助用户查询、搜索和分析合同信息。

## 你的能力
1. **合同搜索**：根据关键词、合同名称、编号等搜索合同
2. **合同统计**：统计合同数量、金额、状态等
3. **条款搜索**：在合同中搜索特定条款内容
4. **摘要搜索**：搜索合同摘要信息
5. **条款对比**：对比不同合同的条款摘要或全文
6. **相似合同查找**：查找与指定合同相似的其他合同

## 工作原则
- 先理解用户意图，再选择合适的工具
- 回答应简洁、准确，基于工具返回的实际数据
- 如果搜索无结果，如实告知用户并建议调整搜索条件
- 涉及合同金额、条款等敏感信息时，确保数据准确
- 不要臆造不存在的合同数据

## 输出格式
- 回答使用 Markdown 格式，便于阅读
- 列表和表格有助于展示查询结果
- 重要信息可使用加粗突出"""


@register_agent
class ContractAgent(BaseAgent):
    """合同管理对话 Agent"""

    name = "contract"
    description = "合同管理助手，支持合同搜索、统计、条款查询、对比分析"
    version = "1.0.0"

    def _build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
        ])

    async def _build_contract_tools(self) -> list:
        """构建合同管理工具列表（LangChain StructuredTool）"""
        providers = [
            ContractSearchToolProvider(),
            ContractStatsToolProvider(),
            ContractClauseSearchToolProvider(),
            ContractSummarySearchToolProvider(),
            CompareClauseSummariesToolProvider(),
            CompareClauseFulltextToolProvider(),
            FindSimilarContractsToolProvider(),
        ]
        tools = []
        for provider in providers:
            tools.extend(await provider.build_langchain_tools())
        return tools

    async def execute(self, input_data: dict, **kwargs) -> dict:
        """执行合同对话

        Args:
            input_data: {
                "question": str,
                "history": list[dict],  # [{"role": "user"|"assistant", "content": str}]
                "user_id": int,
                "agent_id": int,
            }

        Returns:
            {"answer": str, "sources": list, "tool_calls": list}
        """
        question = input_data.get("question", "")
        history = input_data.get("history", [])

        logger.debug(
            "[ContractAgent] question=%s, history_turns=%d",
            question[:50], len(history),
        )

        try:
            # 构建合同工具
            contract_tools = await self._build_contract_tools()
            logger.debug("[ContractAgent] tools count=%d", len(contract_tools))

            # 构建历史消息
            messages = []
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant"):
                    messages.append({"role": role, "content": content})

            # 添加当前问题
            messages.append({"role": "user", "content": question})

            # 创建 Deep Agent
            agent = create_deep_agent(
                model=self.llm,
                tools=contract_tools,
                system_prompt=SYSTEM_PROMPT,
            )

            # 执行
            result = await agent.ainvoke({"messages": messages})

            # 提取最终输出
            all_messages = result.get("messages", [])
            final_output = all_messages[-1].content if all_messages else ""

            # 提取工具调用信息
            tool_calls = []
            for msg in all_messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls.append({
                            "tool_name": tc.get("name", ""),
                            "tool_input": tc.get("args", {}),
                            "tool_output": "",  # deepagents 可能不直接暴露 tool output
                        })

            logger.debug(
                "[ContractAgent] Done: answer_len=%d, tool_calls=%d",
                len(final_output), len(tool_calls),
            )

            return {
                "answer": final_output,
                "sources": [],
                "tool_calls": tool_calls,
            }

        except Exception as e:
            logger.error(
                "[ContractAgent] Failed: question=%s, error=%s",
                question[:50], e, exc_info=True,
            )
            return {
                "answer": f"抱歉，处理您的问题时出现错误：{e}",
                "sources": [],
                "tool_calls": [],
            }
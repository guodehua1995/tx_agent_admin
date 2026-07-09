"""合同 Agent（Deep Agent）

合同管理对话 Agent，负责合同搜索、统计、条款查询、摘要搜索、条款对比等。
与飞书 Bot 绑定，提供合同答疑能力。
"""

from typing import Any

from deepagents import create_deep_agent
from langchain_core.prompts import ChatPromptTemplate

from app.log import logger
from app.core.checkpointer import get_checkpointer
from app.agents.tools.contract_tools import (
    CompareClauseFulltextToolProvider,
    CompareClauseSummariesToolProvider,
    ContractClauseSearchToolProvider,
    ContractSearchToolProvider,
    ContractStatsToolProvider,
    FindSimilarContractsToolProvider,
)

from ..base import BaseAgent
from ..registry import register_agent

SYSTEM_PROMPT = """你是一个专业的合同管理助手。你可以帮助用户查询、搜索和分析合同信息。

## 你的能力
1. **合同搜索**：根据关键词、合同名称、编号等搜索合同；设置 include_summary=True 可获取合同完整摘要
2. **合同统计**：统计合同数量、金额、状态等
3. **条款搜索**：在合同中搜索特定条款内容
4. **条款对比**：对比不同合同的条款摘要或全文
5. **相似合同查找**：查找与指定合同相似的其他合同

## 工作原则
- 先理解用户意图，再选择合适的工具
- 回答应简洁、准确，基于工具返回的实际数据
- 如果搜索无结果，如实告知用户并建议调整搜索条件
- 涉及合同金额、条款等敏感信息时，确保数据准确
- 不要臆造不存在的合同数据

## 参考资料
- 当回答涉及具体合同时，必须将工具返回的 document_url 作为参考资料链接附在回答末尾
- 格式：\n\n**参考资料：**\n- [合同名称](document_url)

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
                "conversation_id": int,   # 用于 thread_id，自动恢复上下文
                "user_id": int,
                "agent_id": int,
            }

        Returns:
            {"answer": str, "sources": list, "tool_calls": list}
        """
        question = input_data.get("question", "")
        conversation_id = input_data.get("conversation_id", 0)

        logger.debug(
            f"[ContractAgent] question={question[:50]}, conv_id={conversation_id}"
        )

        try:
            # 构建合同工具
            contract_tools = await self._build_contract_tools()
            logger.debug(f"[ContractAgent] tools count={len(contract_tools)}")

            # 创建 Deep Agent，注入 PostgreSQL checkpointer
            agent = create_deep_agent(
                model=self.llm,
                tools=contract_tools,
                system_prompt=SYSTEM_PROMPT,
                checkpointer=get_checkpointer(),
            )

            # 执行：thread_id 使用 conversation_id，checkpointer 自动恢复上下文
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": question}]},
                config={"configurable": {"thread_id": str(conversation_id)}},
            )

            # 提取最终输出
            all_messages = result.get("messages", [])
            final_output = all_messages[-1].content if all_messages else ""

            # 提取工具调用信息（AIMessage.tool_calls + ToolMessage.content 匹配）
            tool_calls = []
            tool_results = {}  # tool_call_id → content
            for msg in all_messages:
                # 收集 AIMessage 中的 tool_calls
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tc_id = tc.get("id", "")
                        tool_calls.append({
                            "tool_name": tc.get("name", ""),
                            "tool_input": tc.get("args", {}),
                            "tool_call_id": tc_id,
                            "tool_output": "",
                        })
                # 收集 ToolMessage 中的结果
                if hasattr(msg, "tool_call_id") and hasattr(msg, "content"):
                    tool_results[msg.tool_call_id] = msg.content

            # 匹配结果回填 tool_output
            for tc in tool_calls:
                tc_id = tc.pop("tool_call_id", "")
                if tc_id in tool_results:
                    tc["tool_output"] = tool_results[tc_id]

            logger.debug(
                f"[ContractAgent] Done: answer_len={len(final_output)}, tool_calls={len(tool_calls)}"
            )

            return {
                "answer": final_output,
                "sources": [],
                "tool_calls": tool_calls,
            }

        except Exception as e:
            logger.error(
                f"[ContractAgent] Failed: question={question[:50]}, error={e}"
            )
            return {
                "answer": f"抱歉，处理您的问题时出现错误：{e}",
                "sources": [],
                "tool_calls": [],
            }
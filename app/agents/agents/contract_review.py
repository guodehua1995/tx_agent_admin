"""合同条款审查 Agent（Deep Agent）

对单个条款进行法律风险 + 商业风险审查。
配备 query_contract_clause 工具，支持跨条款引用对比。
由定时任务 per-clause 并行调用。
"""

from deepagents import create_deep_agent
from langchain_core.tools import StructuredTool

from app.log import logger
from app.agents.tools.contract_tools import (
    ContractClauseQueryToolProvider,
)

from ..base import BaseAgent
from ..registry import register_agent

SYSTEM_PROMPT = """你是一名资深合同审查专家。你需要审查当前这个合同条款，识别法律风险和商业风险。

## 审查规则
1. 仔细阅读条款原文，分析其法律合规性和商业合理性
2. 如果条款中引用了其他条款（如"按第七条执行"、"依据前款约定"、"参见XX条款"），**必须调用 query_contract_clause 工具查询被引用条款的原文**
3. 对比被引用条款，判断是否存在逻辑矛盾、定义缺失、责任不对等
4. 查询不到被引用条款时，在报告中标注"⚠️ 引用缺失：条款引用了XX，但未找到对应原文"
5. 风险评估应基于条款本身，不臆测不存在的风险

## 输出格式
请严格按以下格式输出审查结果（Markdown）：

### {clause_title}
> **原文：**
> {引用条款原文}

**风险等级：** 🔴高风险 / 🟡中风险 / 🟢低风险
**关联条款：** （如有查询，列出被引用条款的标题和摘要；如无关联则写"无"）
**法律意见：** （从法律合规角度分析，指出潜在问题）
**修改建议：** （给出具体的修改方向或措辞建议）

注意：
- 风险等级标在"风险等级："同一行，不要换行
- 只输出审查结果，不要输出任何额外解释
- 如果查询了关联条款，必须在"关联条款"中体现"""


@register_agent
class ContractClauseReviewAgent(BaseAgent):
    """单条款审查 Agent（Deep Agent）"""

    name = "contract_clause_review"
    description = "审查单个合同条款，支持跨条款引用对比"
    version = "1.0.0"

    async def _build_clause_query_tool(self) -> StructuredTool:
        """构建条款查询工具"""
        provider = ContractClauseQueryToolProvider()
        tools = await provider.build_langchain_tools()
        return tools[0]

    async def execute(self, input_data: dict, **kwargs) -> dict:
        """执行单条款审查

        Args:
            input_data: {
                "contract_id": int,
                "clause_title": str,
                "clause_level": int,
                "original_text": str,
                "children_text": str,
            }

        Returns:
            {"success": bool, "review_result": str, "error": str | None}
        """
        clause_title = input_data.get("clause_title", "")
        contract_id = input_data.get("contract_id", 0)

        logger.debug(
            f"[ContractClauseReview] contract_id={contract_id}, "
            f"clause_title={clause_title}"
        )

        try:
            # 构建查询工具
            clause_query_tool = await self._build_clause_query_tool()

            # 构建用户消息
            user_message = (
                f"请审查以下合同条款：\n\n"
                f"**合同ID：** {contract_id}\n"
                f"**条款标题：** {clause_title}\n"
                f"**条款层级：** {input_data.get('clause_level', 1)}\n"
                f"**条款原文：**\n{input_data.get('original_text', '')}\n\n"
                f"**子条款：**\n{input_data.get('children_text', '无')}\n\n"
                f"请开始审查。"
            )

            # 创建 Deep Agent
            agent = create_deep_agent(
                model=self.llm,
                tools=[clause_query_tool],
                system_prompt=SYSTEM_PROMPT,
            )

            # 执行（官方推荐 dict 格式）
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]}
            )

            # 提取最终输出
            messages = result.get("messages", [])
            final_output = messages[-1].content if messages else ""

            logger.debug(
                f"[ContractClauseReview] Done: contract_id={contract_id}, "
                f"clause_title={clause_title}, "
                f"output_len={len(final_output)}"
            )

            return {
                "success": True,
                "review_result": final_output,
                "error": None,
            }

        except Exception as e:
            logger.error(
                f"[ContractClauseReview] Failed: contract_id={contract_id}, "
                f"clause_title={clause_title}, error={e}",
                exc_info=True,
            )
            return {
                "success": False,
                "review_result": "",
                "error": str(e),
            }
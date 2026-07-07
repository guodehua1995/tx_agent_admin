"""
具体 Agent 实现模块
"""

# 导入所有 Agent 以触发注册
from .contract import ContractAgent
from .contract_review import ContractClauseReviewAgent
from .doc_to_markdown import DocToMarkdownAgent

__all__ = [
    "ContractAgent",
    "ContractClauseReviewAgent",
    "DocToMarkdownAgent",
]

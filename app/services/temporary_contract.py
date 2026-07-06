"""临时合同对比通道

用户上传合同文件后，不经入库流水线，直接将合同内容切片解析，
返回条款列表用于与现有合同进行对比。合同数据仅存内存，不持久化。
"""

import json
import logging
from typing import Optional

from app.models.rag import LLMProviderConfig
from app.controllers.ai_config import ai_config_controller
from app.services.slicing import run_slicing
from app.services.extraction import run_extraction
from app.models.enums import DocumentTypeCode

logger = logging.getLogger(__name__)


class TemporaryContractProcessor:
    """临时合同处理器 — 不上传、不入库、不向量化，仅解析条款用于对比"""

    async def process(
        self, content: str, file_name: str = "临时合同",
    ) -> dict:
        """处理临时合同内容，返回解析后的条款列表

        Args:
            content: 合同文本内容
            file_name: 文件名（用于日志）

        Returns:
            {
                "meta": {"party_a": "...", "party_b": "...", "contract_type": "..."},
                "clauses": [
                    {"clause_index": 0, "clause_title": "合同概要", "content": "..."},
                    ...
                ],
                "clause_count": 10,
            }
        """
        # 获取可用的 Chat 模型
        chat_models = await ai_config_controller.get_active_chat_models()
        if not chat_models:
            raise ValueError("没有可用的 Chat 模型配置")

        model_config = chat_models[0]

        # 执行合同切片
        try:
            result = await run_slicing(
                DocumentTypeCode.CONTRACT, content, model_config, pages=None,
            )
        except Exception as e:
            logger.exception("[TempContract] Slicing failed: %s", e)
            raise ValueError(f"合同解析失败: {e}")

        # 解析切片结果
        try:
            data = json.loads(result.content)
        except json.JSONDecodeError:
            raise ValueError("合同切片结果解析失败")

        meta = data.get("meta") or {}
        clauses = data.get("clauses") or []

        return {
            "meta": meta,
            "clauses": clauses,
            "clause_count": len(clauses),
            "file_name": file_name,
        }

    async def compare_with_existing(
        self,
        temp_content: str,
        clause_title: str,
        contract_ids: list[int],
        file_name: str = "临时合同",
    ) -> dict:
        """将临时合同与现有合同进行同类条款对比

        Args:
            temp_content: 临时合同文本
            clause_title: 要对比的条款标题关键词
            contract_ids: 现有合同ID列表
            file_name: 临时合同文件名

        Returns:
            {
                "temp_contract": {...},
                "existing_clauses": [...],
            }
        """
        from app.services.contract_service import contract_service

        # 1. 解析临时合同
        temp_result = await self.process(temp_content, file_name)

        # 2. 查找临时合同中匹配的条款
        temp_clauses = temp_result.get("clauses", [])
        matched_temp = [
            {
                "clause_index": c.get("clause_index"),
                "clause_title": c.get("clause_title"),
                "content": c.get("content", "")[:500],
            }
            for c in temp_clauses
            if clause_title in (c.get("clause_title") or "")
        ]

        # 3. 查找现有合同中的同类条款
        existing = await contract_service.compare_clause_fulltext(
            clause_title=clause_title,
            contract_ids=contract_ids,
        )

        return {
            "temp_contract": {
                "file_name": file_name,
                "meta": temp_result.get("meta"),
                "matched_clauses": matched_temp,
            },
            "existing_clauses": existing,
        }


temporary_contract_processor = TemporaryContractProcessor()
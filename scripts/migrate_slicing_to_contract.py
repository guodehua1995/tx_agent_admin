"""SlicingResult → Contract / ContractClause 迁移脚本

将现有 contract 类型文档的切片结果迁移到新的合同管理表。

用法：
    python scripts/migrate_slicing_to_contract.py [--dry-run]

迁移逻辑：
1. 查询所有 doc_type_code='contract' 的 Document
2. 找到对应的 SlicingResult.sliced_content JSON
3. 解析 meta(party_a/party_b/contract_type) + clauses 数组
4. 匹配/创建 Client、ContractType
5. 创建 Contract + ContractClause（含父子层级关系）
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tortoise import Tortoise
from app.settings import settings
from app.models.rag import Document, SlicingResult
from app.models.contract import Contract, ContractClause, ContractType
from app.models.quotation import Client
from app.models.enums import DocumentTypeCode
from app.log import logger


async def _init_db():
    await Tortoise.init(config=settings.TORTOISE_ORM)


async def _get_or_create_client(name: str) -> int | None:
    """根据名称匹配 Client，未匹配则创建占位"""
    if not name or not name.strip():
        return None

    name = name.strip()
    # 精确匹配
    client = await Client.filter(name=name, is_deleted=False).first()
    if client:
        return client.id

    # 简称匹配
    client = await Client.filter(short_name=name, is_deleted=False).first()
    if client:
        return client.id

    # 模糊匹配（name 包含关系）
    from tortoise.expressions import Q
    client = await Client.filter(
        Q(name__icontains=name) | Q(short_name__icontains=name),
        is_deleted=False,
    ).first()
    if client:
        return client.id

    # 未匹配：创建占位 Client
    client = await Client.create(
        name=name,
        short_name=name,
        client_type="企业",
        is_active=True,
    )
    logger.info(f"[migrate] 创建占位 Client: id={client.id}, name={name}")
    return client.id


async def _get_or_create_contract_type(type_name: str) -> int | None:
    """根据合同类型名称匹配 ContractType"""
    if not type_name or not type_name.strip():
        return None

    type_name = type_name.strip()
    ct = await ContractType.filter(name=type_name, is_deleted=False).first()
    if ct:
        return ct.id

    # 模糊匹配
    ct = await ContractType.filter(name__icontains=type_name, is_deleted=False).first()
    if ct:
        return ct.id

    # 未匹配：归入"其他"
    ct = await ContractType.filter(code="other", is_deleted=False).first()
    if ct:
        logger.info(f"[migrate] 合同类型 '{type_name}' 未匹配，归入'其他'")
        return ct.id

    return None


def _parse_clause_hierarchy(clause_title: str | None) -> tuple[int, list[str]]:
    """解析条款标题的层级

    clause_title 格式: "一级-二级-三级"，用 "-" 分隔层级路径。
    返回 (level, path_parts)，如 "合作范围-服务内容-软件开发" → (2, ["合作范围", "服务内容", "软件开发"])
    """
    if not clause_title:
        return (0, [])

    parts = [p.strip() for p in clause_title.split("-") if p.strip()]
    return (len(parts) - 1, parts)


async def _build_clause_tree(
    contract: Contract,
    clauses: list[dict],
) -> int:
    """构建条款树并写入 ContractClause 表

    返回创建的条款总数。
    """
    # 用于 parent_id 查找：key = (contract_id, full_path) → clause_id
    parent_map: dict[str, int] = {}

    total = 0
    for clause in clauses:
        clause_index = clause.get("clause_index", 0)
        clause_title = clause.get("clause_title") or ""
        original_text = clause.get("content") or ""

        level, path_parts = _parse_clause_hierarchy(clause_title)

        # 确定 parent_id
        parent_id = None
        if level > 0 and len(path_parts) > 1:
            parent_path = "-".join(path_parts[:-1])
            parent_id = parent_map.get(parent_path)

        # 确定 summary（clause_index=0 的概要不设 summary，原文即为概要）
        summary = None
        if clause_index == 0:
            summary = original_text[:500] if original_text else None

        clause_obj = await ContractClause.create(
            contract=contract,
            parent_id=parent_id,
            clause_index=clause_index,
            clause_title=clause_title if clause_title else None,
            clause_level=level,
            original_text=original_text,
            summary=summary,
            sort_order=clause_index,
        )

        # 记录当前路径用于子条款查找
        full_path = "-".join(path_parts) if path_parts else str(clause_index)
        parent_map[full_path] = clause_obj.id

        total += 1

    return total


async def migrate(dry_run: bool = False):
    """执行迁移"""
    await _init_db()

    # 1. 查询所有 contract 类型的 document
    docs = await Document.filter(
        doc_type_code=DocumentTypeCode.CONTRACT,
        is_deleted=False,
    ).all()

    logger.info(f"[migrate] 找到 {len(docs)} 个合同文档")

    migrated = 0
    skipped = 0
    errors = []

    for doc in docs:
        try:
            # 检查是否已迁移
            existing = await Contract.filter(document_id=doc.id, is_deleted=False).first()
            if existing:
                logger.info(f"[migrate] 跳过已迁移: doc_id={doc.id}, title={doc.title}")
                skipped += 1
                continue

            # 2. 获取 SlicingResult
            slicing = await SlicingResult.filter(document_id=doc.id).first()
            if not slicing or not slicing.sliced_content:
                logger.warning(f"[migrate] 无切片数据: doc_id={doc.id}, title={doc.title}")
                skipped += 1
                continue

            try:
                data = json.loads(slicing.sliced_content)
            except json.JSONDecodeError:
                logger.warning(f"[migrate] 切片内容非 JSON: doc_id={doc.id}")
                skipped += 1
                continue

            meta = data.get("meta") or {}
            clauses = data.get("clauses") or []

            if not clauses:
                logger.warning(f"[migrate] 无条款数据: doc_id={doc.id}")
                skipped += 1
                continue

            if dry_run:
                logger.info(
                    f"[dry-run] 将迁移: doc_id={doc.id}, title={doc.title}, "
                    f"party_a={meta.get('party_a')}, party_b={meta.get('party_b')}, "
                    f"type={meta.get('contract_type')}, clauses={len(clauses)}"
                )
                migrated += 1
                continue

            # 3. 匹配/创建 Client
            party_a_id = await _get_or_create_client(meta.get("party_a", ""))
            party_b_id = await _get_or_create_client(meta.get("party_b", ""))

            # 4. 匹配 ContractType
            contract_type_id = await _get_or_create_contract_type(meta.get("contract_type", ""))

            # 5. 创建 Contract
            contract = await Contract.create(
                document_id=doc.id,
                contract_type_id=contract_type_id,
                party_a_client_id=party_a_id or 0,
                party_b_client_id=party_b_id,
                project_name=doc.title,
                summary=doc.summary,
                clause_count=0,  # 先占位，后续更新
            )

            # 6. 创建 ContractClause 树
            clause_count = await _build_clause_tree(contract, clauses)

            # 更新条款计数
            contract.clause_count = clause_count
            await contract.save(update_fields=["clause_count"])

            logger.info(
                f"[migrate] 迁移成功: doc_id={doc.id}, title={doc.title}, "
                f"contract_id={contract.id}, clauses={clause_count}"
            )
            migrated += 1

        except Exception as e:
            logger.exception(f"[migrate] 迁移失败: doc_id={doc.id}, title={doc.title}")
            errors.append({"doc_id": doc.id, "title": doc.title, "error": str(e)})

    logger.info(f"[migrate] 完成: 迁移={migrated}, 跳过={skipped}, 错误={len(errors)}")

    if errors:
        logger.warning(f"[migrate] 错误详情: {json.dumps(errors, ensure_ascii=False, indent=2)}")

    await Tortoise.close_connections()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(migrate(dry_run=dry_run))
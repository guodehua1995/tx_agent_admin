"""补偿切片失败的合同条款

从文档原文中模糊匹配找到对应条款，替换切片结果中的失败占位内容。

用法：
    # 仅统计（不修改）
    python -c "import asyncio; from app.scripts.compensate_slicing import run; print(asyncio.run(run(dry_run=True)))"

    # 执行补偿（限制数量，先试几个）
    python -c "import asyncio; from app.scripts.compensate_slicing import run; print(asyncio.run(run(dry_run=False, limit=5)))"

    # 全量执行
    python -c "import asyncio; from app.scripts.compensate_slicing import run; print(asyncio.run(run(dry_run=False, limit=0)))"
"""

import json
import re
from difflib import SequenceMatcher
from typing import Optional

from tortoise import Tortoise

from app.log import logger
from app.models.enums import DocumentStatus
from app.models.rag import Document, SlicingResult, DocumentPage
from app.models.contract import Contract, ContractClause
from app.settings.config import settings

# 标题相似度阈值（80% 字符匹配视为匹配）
TITLE_SIMILARITY_THRESHOLD = 0.8


async def run(dry_run: bool = True, limit: int = 10) -> str:
    """执行补偿脚本。

    Args:
        dry_run: True 仅统计不修改，False 执行补偿
        limit: 最多处理多少条切片结果，0 表示不限制（全量执行）
    """
    await Tortoise.init(config=settings.TORTOISE_ORM)

    try:
        # 使用原始 SQL 查询，避免 ORM 的 LIKE 扫描超时
        from tortoise import connections
        conn = connections.get("postgres")
        
        # 临时放宽 statement_timeout，避免大文本 LIKE 查询超时
        await conn.execute_query("SET LOCAL statement_timeout = 300000")  # 5分钟
        
        # 分页查询，每页 10 条
        page_size = 10
        offset = 0
        failed_rows = []
        while True:
            rows = await conn.execute_query_dict(
                "SELECT id, document_id, sliced_content FROM slicing_result "
                "WHERE sliced_content LIKE '%该条款解析失败%' "
                "OR sliced_content LIKE '%该条款自动解析失败%' "
                f"ORDER BY id LIMIT {page_size} OFFSET {offset}"
            )
            if not rows:
                break
            failed_rows.extend(rows)
            offset += page_size
        
        if not failed_rows:
            return "没有找到有问题的切片结果"

        # 应用数量限制
        total_found = len(failed_rows)
        if limit > 0:
            failed_rows = failed_rows[:limit]

        lines = [
            "=" * 60,
            f"合同条款切片补偿（{'预览模式' if dry_run else '执行模式'}）",
            "=" * 60,
            f"发现 {total_found} 个有问题的切片结果",
        ]
        if limit > 0 and total_found > limit:
            lines.append(f"本次处理前 {limit} 条（设置 limit=0 全量执行）")
        lines.append("-" * 60)

        fixed_count = 0
        unfixed_docs = []  # [(doc, unfixed_count)] 无法自动修复的文档
        for row in failed_rows:
            slicing = await SlicingResult.get(id=row["id"])
            doc = await Document.get(id=row["document_id"])
            result = await _compensate_one(slicing, doc, dry_run)
            if result["fixed_clauses"]:
                fixed_count += 1
                lines.append(f"\n[文档 {doc.id}] {doc.title}")
                lines.append(f"  修复条款数: {len(result['fixed_clauses'])}")
                for clause in result["fixed_clauses"]:
                    lines.append(f"    - {clause['title']}: 匹配到原文 {clause['matched_length']} 字")
            if result["unfixed_count"] > 0:
                unfixed_docs.append((doc, result["unfixed_count"]))
                lines.append(f"\n[文档 {doc.id}] {doc.title}")
                lines.append(f"  未能自动修复（{result['unfixed_count']} 个条款无匹配）")

        # ── 处理无法自动修复的文档：清理全部数据 → 重置为待提取 ──
        if unfixed_docs:
            lines.append("\n" + "=" * 60)
            lines.append(f"无法自动修复的文档: {len(unfixed_docs)} 个")
            lines.append("这些文档将清理全部关联数据，重置为待提取状态重新走完整流程")
            lines.append("-" * 60)
            reset_count = 0
            for doc, unfixed_n in unfixed_docs:
                lines.append(f"  [文档 {doc.id}] {doc.title} （{unfixed_n} 个条款无法修复）")
                if not dry_run:
                    await _reset_for_reextract(doc)
                    reset_count += 1
            if dry_run:
                lines.append(f"（预览模式，未重置）")
            else:
                lines.append(f"已重置 {reset_count} 个文档为待提取状态")

        lines.append("\n" + "-" * 60)
        lines.append(f"总计: {fixed_count}/{len(failed_rows)} 个文档有条款被修复")
        lines.append(f"无法修复: {len(unfixed_docs)} 个文档将重新提取")

        if not dry_run:
            lines.append("已执行补偿，相关文档状态已更新")
        else:
            lines.append("（预览模式，未做任何修改）")

        lines.append("=" * 60)
        return "\n".join(lines)

    finally:
        await Tortoise.close_connections()


async def _compensate_one(
    slicing: SlicingResult, doc: Document, dry_run: bool
) -> dict:
    """补偿单个文档的切片结果。

    Returns:
        {"fixed_clauses": [...], "unfixed_count": int}
    """
    # 解析切片结果 JSON
    try:
        data = json.loads(slicing.sliced_content)
    except json.JSONDecodeError:
        return {"fixed_clauses": [], "unfixed_count": 0}

    clauses = data.get("clauses", [])
    if not clauses:
        return {"fixed_clauses": [], "unfixed_count": 0}

    # 从文档原文中提取所有标题及其内容
    doc_headings = _extract_headings_with_content(doc.content or "")

    fixed_clauses = []
    unfixed_count = 0

    for clause in clauses:
        content = clause.get("content", "")
        # 检查是否是失败的条款（包含警告文本或只是原文片段）
        if not _is_failed_clause(content):
            continue

        clause_title = clause.get("clause_title", "")
        if not clause_title:
            unfixed_count += 1
            continue

        # 在文档标题中模糊匹配
        matched = _fuzzy_match_heading(clause_title, doc_headings)
        if matched:
            fixed_clauses.append({
                "title": clause_title,
                "matched_length": len(matched),
            })
            if not dry_run:
                clause["content"] = matched
        else:
            unfixed_count += 1

    if fixed_clauses and not dry_run:
        # 更新切片结果
        data["clauses"] = clauses
        # 移除或更新 processing_warnings
        if "processing_warnings" in data:
            data["processing_warnings"] = [
                w for w in data["processing_warnings"]
                if not any(fc["title"] in w for fc in fixed_clauses)
            ]
        slicing.sliced_content = json.dumps(data, ensure_ascii=False)
        await slicing.save()

        # 删除旧的 Contract + ContractClause，让向量化流程重新创建
        existing_contract = await Contract.filter(document_id=doc.id, is_deleted=False).first()
        if existing_contract:
            # 先删除条款（无级联删除）
            await ContractClause.filter(contract_id=existing_contract.id).delete()
            # 再删除合同
            await existing_contract.delete()
            logger.info(f"Deleted old contract for doc_id={doc.id}")

        # 删除旧向量数据
        from app.services.chunk_service import chunk_service
        await chunk_service.delete_by_doc_id(doc.id)

        # 更新文档状态为 APPROVED，等待定时任务执行向量化
        doc.status = DocumentStatus.APPROVED
        await doc.save()

    return {"fixed_clauses": fixed_clauses, "unfixed_count": unfixed_count}


async def _reset_for_reextract(doc: Document) -> None:
    """清理文档全部关联数据，重置为待提取状态重新走完整流程。

    清理顺序：向量 → 切片 → 合同/条款 → 页面/截图 → 重置文档
    """
    from app.services.chunk_service import chunk_service

    # 1. 删除向量数据
    await chunk_service.delete_by_doc_id(doc.id)

    # 2. 删除切片结果
    await SlicingResult.filter(document_id=doc.id).delete()

    # 3. 删除合同 + 条款（重新走流程时会重新创建）
    existing_contract = await Contract.filter(document_id=doc.id, is_deleted=False).first()
    if existing_contract:
        await ContractClause.filter(contract_id=existing_contract.id).delete()
        await existing_contract.delete()
        logger.info(f"Deleted old contract for re-extract: contract_id={existing_contract.id}")

    # 4. 删除页面记录及截图
    pages = await DocumentPage.filter(document_id=doc.id).all()
    for page in pages:
        if page.screenshot_url:
            try:
                from app.services.file_storage import file_storage
                await file_storage.delete(page.screenshot_url)
            except Exception:
                pass
    await DocumentPage.filter(document_id=doc.id).delete()

    # 5. 重置文档状态为待提取
    doc.content = None
    doc.summary = None
    doc.status = DocumentStatus.PENDING_EXTRACT
    doc.error_message = None
    await doc.save()
    logger.info(f"Document reset to PENDING_EXTRACT: id={doc.id}")


def _is_failed_clause(content: str) -> bool:
    """判断条款内容是否是失败占位。"""
    if not content:
        return True
    # 包含警告标记
    if "该条款解析失败" in content:
        return True
    if "该条款自动解析失败" in content:
        return True
    # 内容很短且以 ⚠️ 开头
    if content.startswith("⚠️") and len(content) < 200:
        return True
    return False


def _extract_headings_with_content(text: str) -> list[dict]:
    """从文档原文中提取所有标题及其对应内容。

    返回 [{"heading": "第一条 定义", "content": "完整条款内容"}, ...]
    """
    # 匹配 markdown 标题（# 第X条、## 第X条 等）
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    
    headings = []
    matches = list(heading_pattern.finditer(text))
    
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        headings.append({"heading": heading, "content": content})
    
    return headings


def _fuzzy_match_heading(clause_title: str, doc_headings: list[dict]) -> Optional[str]:
    """在文档标题中模糊匹配条款标题。

    返回匹配到的条款内容，或 None。
    """
    best_match = None
    best_score = 0

    for item in doc_headings:
        heading = item["heading"]
        # 计算相似度
        score = SequenceMatcher(None, clause_title, heading).ratio()
        
        # 也尝试去掉编号后匹配（如 "第一条 定义" -> "定义"）
        heading_no_num = re.sub(r'^第[一二三四五六七八九十\d]+条\s*', '', heading)
        clause_no_num = re.sub(r'^第[一二三四五六七八九十\d]+条\s*', '', clause_title)
        if heading_no_num and clause_no_num:
            score_no_num = SequenceMatcher(None, clause_no_num, heading_no_num).ratio()
            score = max(score, score_no_num)
        
        if score >= TITLE_SIMILARITY_THRESHOLD and score > best_score:
            best_score = score
            best_match = item["content"]

    return best_match

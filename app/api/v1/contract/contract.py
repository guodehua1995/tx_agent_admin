"""合同管理 API 路由"""

import logging

from fastapi import APIRouter, Query
from tortoise.expressions import Q

from app.controllers.contract import (
    contract_clause_controller,
    contract_controller,
    contract_type_controller,
)
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.contract import (
    ClauseCompareParams,
    ClauseFulltextCompareParams,
    ContractClauseCreate,
    ContractClauseSearchParams,
    ContractClauseUpdate,
    ContractSearchParams,
    ContractSummarySearchParams,
    ContractTypeCreate,
    ContractTypeUpdate,
    ContractUpdate,
    SimilarContractParams,
)
from app.services.contract_service import contract_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 合同类型管理 ──────────────────────────────────────────────────


@router.get("/type/list", summary="合同类型列表")
async def list_contract_types():
    types = await contract_service.list_contract_types()
    data = [await t.to_dict() for t in types]
    return Success(data=data)


@router.post("/type/create", summary="新增合同类型")
async def create_contract_type(body: ContractTypeCreate):
    try:
        obj = await contract_service.create_contract_type(
            name=body.name, code=body.code, description=body.description,
        )
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=await obj.to_dict())


@router.put("/type/update", summary="修改合同类型")
async def update_contract_type(id: int = Query(...), body: ContractTypeUpdate = None):
    obj = await contract_type_controller.update(id=id, obj_in=body.model_dump(exclude_unset=True))
    return Success(data=await obj.to_dict())


@router.delete("/type/delete", summary="删除合同类型(软删)")
async def delete_contract_type(id: int = Query(...)):
    await contract_type_controller.update(id=id, obj_in={"is_deleted": True})
    return Success(msg="已删除")


# ── 合同 CRUD ─────────────────────────────────────────────────────


@router.get("/list", summary="合同列表")
async def list_contracts(
    page: int = Query(1),
    page_size: int = Query(20),
    keyword: str = Query(""),
    party_a: str = Query(""),
    party_b: str = Query(""),
    contract_type_id: int = Query(None),
):
    result = await contract_service.search_contracts({
        "keyword": keyword or None,
        "party_a": party_a or None,
        "party_b": party_b or None,
        "contract_type_id": contract_type_id,
        "page": page,
        "page_size": page_size,
    })
    return SuccessExtra(
        data=result["items"], total=result["total"], page=page, page_size=page_size,
    )


@router.get("/detail", summary="合同详情(含条款树)")
async def get_contract_detail(contract_id: int = Query(...)):
    try:
        data = await contract_service.get_contract_detail(contract_id)
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=data)


@router.put("/update", summary="修改合同信息")
async def update_contract(id: int = Query(...), body: ContractUpdate = None):
    try:
        contract = await contract_service.update_contract(
            id, **body.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=await contract.to_dict())


@router.delete("/delete", summary="删除合同(软删)")
async def delete_contract(id: int = Query(...)):
    await contract_service.soft_delete_contract(id)
    return Success(msg="已删除")


# ── 条款编辑 ──────────────────────────────────────────────────────


@router.put("/clause/update", summary="编辑条款原文(即刻生效)")
async def update_clause(id: int = Query(..., description="条款ID"), body: ContractClauseUpdate = None):
    try:
        clause = await contract_service.update_clause(
            clause_id=id, original_text=body.original_text,
        )
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=await clause.to_dict())


@router.post("/clause/create", summary="新增条款(即刻生效)")
async def create_clause(body: ContractClauseCreate):
    try:
        clause = await contract_service.create_clause(
            contract_id=body.contract_id,
            clause_title=body.clause_title,
            original_text=body.original_text,
            parent_id=body.parent_id,
        )
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=await clause.to_dict())


@router.delete("/clause/delete", summary="删除条款(即刻生效)")
async def delete_clause(id: int = Query(..., description="条款ID")):
    try:
        await contract_service.delete_clause(id)
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(msg="条款已删除，向量库已同步清理")


# ── 合同搜索 ──────────────────────────────────────────────────────


@router.get("/search", summary="结构化搜索合同")
async def search_contracts(
    page: int = Query(1),
    page_size: int = Query(20),
    keyword: str = Query(""),
    party_a: str = Query(""),
    party_b: str = Query(""),
    contract_type_id: int = Query(None),
):
    result = await contract_service.search_contracts({
        "keyword": keyword or None,
        "party_a": party_a or None,
        "party_b": party_b or None,
        "contract_type_id": contract_type_id,
        "page": page,
        "page_size": page_size,
    })
    return SuccessExtra(
        data=result["items"], total=result["total"], page=page, page_size=page_size,
    )


@router.get("/summary/search", summary="搜索合同摘要")
async def search_contract_summaries(
    page: int = Query(1),
    page_size: int = Query(20),
    keyword: str = Query(""),
    party_a: str = Query(""),
    party_b: str = Query(""),
):
    result = await contract_service.search_contract_summaries({
        "keyword": keyword or None,
        "party_a": party_a or None,
        "party_b": party_b or None,
        "page": page,
        "page_size": page_size,
    })
    return SuccessExtra(
        data=result["items"], total=result["total"], page=page, page_size=page_size,
    )


@router.get("/clause/search", summary="搜索条款")
async def search_clauses(
    page: int = Query(1),
    page_size: int = Query(20),
    keyword: str = Query(""),
    clause_title: str = Query(""),
    contract_id: int = Query(None),
):
    result = await contract_service.search_clauses({
        "keyword": keyword or None,
        "clause_title": clause_title or None,
        "contract_id": contract_id,
        "page": page,
        "page_size": page_size,
    })
    return SuccessExtra(
        data=result["items"], total=result["total"], page=page, page_size=page_size,
    )


@router.get("/clause/context", summary="获取条款及其上下文")
async def get_clause_context(clause_id: int = Query(...), context_size: int = Query(2)):
    clause, prev, next_clauses = await contract_clause_controller.get_clause_with_context(
        clause_id, context_size,
    )
    if not clause:
        return Fail(msg="条款不存在")
    return Success(data={
        "clause": await clause.to_dict(),
        "prev": [await c.to_dict() for c in prev],
        "next": [await c.to_dict() for c in next_clauses],
    })


# ── 合同对比 ──────────────────────────────────────────────────────


@router.post("/compare/summaries", summary="对比同类条款摘要")
async def compare_clause_summaries(body: ClauseCompareParams):
    result = await contract_service.compare_clause_summaries(
        clause_title=body.clause_title,
        contract_ids=body.contract_ids,
        party_a=body.party_a,
        party_b=body.party_b,
    )
    return Success(data=result)


@router.post("/compare/fulltext", summary="对比同类条款全文")
async def compare_clause_fulltext(body: ClauseFulltextCompareParams):
    result = await contract_service.compare_clause_fulltext(
        clause_title=body.clause_title,
        contract_ids=body.contract_ids,
    )
    return Success(data=result)


@router.post("/similar", summary="查找相似合同")
async def find_similar_contracts(body: SimilarContractParams):
    result = await contract_service.find_similar_contracts(
        contract_id=body.contract_id, limit=body.limit,
    )
    return Success(data=result)


# ── 合同统计 ──────────────────────────────────────────────────────


@router.get("/stats", summary="合同统计")
async def get_contract_stats():
    stats = await contract_service.get_contract_stats()
    return Success(data=stats)


@router.get("/stats/sql", summary="合同统计(SQL直接查询)")
async def get_contract_stats_sql():
    stats = await contract_service.get_contract_stats_sql()
    return Success(data=stats)


@router.get("/expiring", summary="即将到期合同")
async def get_expiring_contracts(days: int = Query(30)):
    contracts = await contract_controller.get_expiring_contracts(days)
    data = [await c.to_dict() for c in contracts]
    return Success(data=data)


# ── 合同审查 ──────────────────────────────────────────────────────


@router.post("/review/trigger", summary="触发合同审查")
async def trigger_contract_review(
    contract_id: int = Query(..., description="合同ID"),
    focus_areas: str = Query(None, description="分析维度，如'法律合规,商业风险'"),
):
    """创建审查记录并加入队列，定时任务会异步执行审查"""
    from app.models.contract import ContractRiskReport

    # 检查是否已有审查记录
    existing = await ContractRiskReport.filter(
        contract_id=contract_id,
        status__in=["pending", "analyzing"],
    ).first()
    if existing:
        return Fail(msg=f"该合同正在审查中（状态：{existing.status}），请稍后再试")

    # 解析 focus_areas
    areas = None
    if focus_areas:
        areas = [a.strip() for a in focus_areas.split(",") if a.strip()]

    report = await ContractRiskReport.create(
        contract_id=contract_id,
        focus_areas=areas,
        status="pending",
    )

    logger.info(f"[ContractReview] Triggered: contract_id={contract_id}, report_id={report.id}")
    return Success(data={
        "report_id": report.id,
        "contract_id": contract_id,
        "status": "pending",
        "message": "已加入审查队列，完成后会生成飞书文档",
    })


@router.get("/review/result", summary="获取审查结果")
async def get_review_result(contract_id: int = Query(..., description="合同ID")):
    """获取合同的最新审查报告"""
    from app.models.contract import ContractRiskReport

    report = await ContractRiskReport.filter(
        contract_id=contract_id,
    ).order_by("-created_at").first()

    if not report:
        return Fail(msg="该合同暂无审查记录")

    return Success(data={
        "id": report.id,
        "contract_id": report.contract_id,
        "status": report.status,
        "focus_areas": report.focus_areas,
        "feishu_doc_url": report.feishu_doc_url,
        "risk_summary": report.risk_summary,
        "report_content": report.report_content,
        "error_message": report.error_message,
        "analyzed_at": report.analyzed_at.isoformat() if report.analyzed_at else None,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    })


@router.delete("/review/result", summary="删除审查结果")
async def delete_review_result(report_id: int = Query(..., description="审查报告ID")):
    """删除指定的审查报告"""
    from app.models.contract import ContractRiskReport

    report = await ContractRiskReport.filter(id=report_id).first()
    if not report:
        return Fail(msg="审查报告不存在")

    await report.delete()
    logger.info(f"[ContractReview] Deleted: report_id={report_id}")
    return Success(msg="审查报告已删除")
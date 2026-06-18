import logging

from fastapi import APIRouter, File, Query, UploadFile
from tortoise.expressions import Q

from app.controllers.quotation import (
    client_controller,
    quotation_item_controller,
    quotation_rule_controller,
)
from app.core.ctx import CTX_USER_ID
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.quotation import (
    ApprovalAction,
    ClientCreate,
    ClientUpdate,
    QuotationRuleCreate,
    QuotationRuleEditDraft,
    QuotationRuleEditNewVersion,
    QuotationRuleIdOnly,
    QuotationRuleSubmit,
)
from app.services.excel_parser import ExcelParseError, parse_quotation_excel
from app.services.quotation_service import quotation_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 甲方管理 ─────────────────────────────────────────────────────


@router.get("/client/list", summary="甲方列表")
async def list_clients(
    page: int = Query(1), page_size: int = Query(10), keyword: str = Query(""),
):
    q = Q(is_deleted=False)
    if keyword:
        q &= Q(name__icontains=keyword) | Q(short_name__icontains=keyword)
    total, objs = await client_controller.list(page=page, page_size=page_size, search=q)
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post("/client/create", summary="新增甲方")
async def create_client(body: ClientCreate):
    existing = await client_controller.get_by_name(body.name)
    if existing:
        return Fail(msg="该甲方名称已存在")
    obj = await client_controller.create(body)
    return Success(data=await obj.to_dict())


@router.put("/client/update", summary="修改甲方")
async def update_client(id: int = Query(...), body: ClientUpdate = None):
    obj = await client_controller.update(id=id, obj_in=body)
    return Success(data=await obj.to_dict())


@router.delete("/client/delete", summary="删除甲方(软删)")
async def delete_client(id: int = Query(...)):
    await client_controller.update(id=id, obj_in={"is_deleted": True})
    return Success(msg="已删除")


# ── 报价规则 ─────────────────────────────────────────────────────


@router.get("/rule/list", summary="报价规则列表")
async def list_rules(
    page: int = Query(1),
    page_size: int = Query(10),
    client_id: int = Query(None),
    status: str = Query(""),
):
    q = Q(is_deleted=False)
    if client_id:
        q &= Q(client_id=client_id)
    if status:
        q &= Q(status=status)
    else:
        # 默认排除已归档规则（已归档规则只在归档页面展示）
        q &= ~Q(status="archived")
    total, objs = await quotation_rule_controller.list(
        page=page, page_size=page_size, search=q, order=["-created_at"]
    )
    data = [await obj.to_dict() for obj in objs]

    # 填充甲方名称
    for item in data:
        item["client_name"] = (await client_controller.get_by_id(item["client_id"])).name

    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/rule/detail", summary="报价规则详情(含明细树)")
async def get_rule_detail(rule_id: int = Query(...)):
    rule = await quotation_rule_controller.get(id=rule_id)
    data = await rule.to_dict()
    data["items"] = await quotation_item_controller.get_tree_by_rule(rule_id)
    return Success(data=data)


@router.post("/rule/create", summary="新增报价规则(草稿)")
async def create_rule(body: QuotationRuleCreate):
    user_id = CTX_USER_ID.get()
    items = [item.model_dump() for item in body.items]
    rule = await quotation_service.create_rule(
        client_id=body.client_id, creator_id=user_id, items=items, source_type=body.source_type
    )
    return Success(data=await rule.to_dict())


@router.post("/rule/submit", summary="提交审批")
async def submit_rule(body: QuotationRuleSubmit):
    user_id = CTX_USER_ID.get()
    rule = await quotation_service.submit_for_approval(body.rule_id, user_id)
    return Success(data=await rule.to_dict())


@router.put("/rule/edit_draft", summary="编辑草稿(原地修改)")
async def edit_draft(body: QuotationRuleEditDraft):
    items = [item.model_dump() for item in body.items]
    try:
        rule = await quotation_service.edit_draft(body.rule_id, items)
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=await rule.to_dict())


@router.post("/rule/edit_new_version", summary="从生效/失效版本派生新版本")
async def edit_new_version(body: QuotationRuleEditNewVersion):
    user_id = CTX_USER_ID.get()
    items = [item.model_dump() for item in body.items]
    try:
        rule = await quotation_service.edit_as_new_version(
            source_rule_id=body.source_rule_id, items=items, user_id=user_id, source_type=body.source_type
        )
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=await rule.to_dict())


@router.post("/rule/cancel", summary="取消生效版本")
async def cancel_rule(body: QuotationRuleIdOnly):
    user_id = CTX_USER_ID.get()
    try:
        rule = await quotation_service.cancel_rule(body.rule_id, user_id)
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(data=await rule.to_dict())


@router.delete("/rule/delete", summary="删除草稿")
async def delete_rule(id: int = Query(...)):
    try:
        await quotation_service.delete_draft(id)
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(msg="已删除")


# ── 审批（仅配置的审批人可操作）────────────────────────────────────


@router.get("/approval/list", summary="待审批列表")
async def list_pending_approvals(
    page: int = Query(1), page_size: int = Query(10),
):
    """查询待审批的报价规则"""
    q = Q(status="pending_approval", is_deleted=False)
    total, objs = await quotation_rule_controller.list(
        page=page, page_size=page_size, search=q, order=["-updated_at"]
    )
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post("/approval/action", summary="执行审批(通过/驳回)")
async def do_approval(body: ApprovalAction):
    user_id = CTX_USER_ID.get()
    # 校验审批人权限
    if not await quotation_service.check_approver(user_id):
        return Fail(msg="您没有审批权限")
    try:
        if body.action == "approve":
            await quotation_service.approve(body.rule_id, user_id)
        elif body.action == "reject":
            if not body.comment:
                return Fail(msg="驳回必须填写原因")
            await quotation_service.reject(body.rule_id, user_id, body.comment)
        else:
            return Fail(msg=f"不支持的操作: {body.action}")
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(msg="操作成功")


# ── Excel 导入 ────────────────────────────────────────────────────


@router.post("/excel/parse", summary="解析Excel报价单(预览)")
async def parse_excel(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")):
        return Fail(msg="仅支持 .xlsx / .xls 格式")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        return Fail(msg="文件大小不能超过 20MB")
    try:
        result = parse_quotation_excel(content)
    except ExcelParseError as e:
        return Fail(msg=str(e))
    return Success(data=result)


@router.post("/excel/import", summary="确认导入Excel解析结果")
async def import_excel(body: QuotationRuleCreate):
    """用户确认解析结果后提交，等同于创建规则"""
    user_id = CTX_USER_ID.get()
    items = [item.model_dump() for item in body.items]
    rule = await quotation_service.create_rule(
        client_id=body.client_id, creator_id=user_id, items=items, source_type="excel_import"
    )
    return Success(data=await rule.to_dict())


# ── 版本归档 ─────────────────────────────────────────────────────


@router.get("/archive/list", summary="归档版本列表")
async def list_archives(client_id: int = Query(None)):
    from app.models.quotation import VersionArchive

    q = Q()
    if client_id:
        q = Q(client_id=client_id)
    archives = await VersionArchive.filter(q).order_by("-version")
    data = [await a.to_dict() for a in archives]
    return Success(data=data)


@router.get("/archive/detail", summary="归档版本详情(快照)")
async def get_archive_detail(archive_id: int = Query(...)):
    from app.models.quotation import VersionArchive

    archive = await VersionArchive.get(id=archive_id)
    return Success(data=await archive.to_dict())

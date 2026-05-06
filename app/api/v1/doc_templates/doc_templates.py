import logging

from fastapi import APIRouter, Query
from tortoise.expressions import Q

from app.controllers.doc_template import doc_template_controller
from app.models.rag import Agent, DocTemplate
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.doc_templates import (
    DocTemplateCreate,
    DocTemplateUpdate,
    GenerateDocRequest,
    ParseUrlRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="文档模板列表")
async def list_doc_templates(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    naming_format: str = Query("", description="命名格式搜索"),
    folder_token: str = Query("", description="文件夹Token搜索"),
):
    q = Q(is_deleted=False)
    if naming_format:
        q &= Q(naming_format__contains=naming_format)
    if folder_token:
        q &= Q(folder_token__contains=folder_token)
    total, objs = await doc_template_controller.list(
        page=page, page_size=page_size, search=q, order=["-created_at"]
    )
    data = [await obj.to_dict(exclude_fields=["markdown_content"]) for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="文档模板详情")
async def get_doc_template(template_id: int = Query(..., description="模板ID")):
    obj = await doc_template_controller.get(id=template_id)
    if obj.is_deleted:
        return Fail(msg="模板不存在或已删除")
    return Success(data=await obj.to_dict())


@router.post("/create", summary="新增文档模板")
async def create_doc_template(template_in: DocTemplateCreate):
    obj = await doc_template_controller.create(template_in)
    logger.info("[DocTemplate] Created: name=%s, id=%s", template_in.name, obj.id)
    return Success(msg="创建成功", data={"id": obj.id})


@router.post("/update", summary="修改文档模板")
async def update_doc_template(template_in: DocTemplateUpdate):
    obj = await doc_template_controller.get(id=template_in.id)
    if obj.is_deleted:
        return Fail(msg="模板不存在或已删除")
    await doc_template_controller.update(
        id=template_in.id,
        obj_in=template_in.model_dump(exclude_unset=True, exclude={"id"}),
    )
    logger.info("[DocTemplate] Updated: id=%s", template_in.id)
    return Success(msg="更新成功")


@router.delete("/delete", summary="删除文档模板")
async def delete_doc_template(template_id: int = Query(..., description="模板ID")):
    await doc_template_controller.soft_delete(id=template_id)
    logger.info("[DocTemplate] Soft deleted: id=%s", template_id)
    return Success(msg="删除成功")


@router.post("/parse_url", summary="解析飞书云文档URL为Markdown")
async def parse_feishu_url(body: ParseUrlRequest):
    from app.controllers.feishu_bot import feishu_bot_controller
    from app.models.global_config import GlobalConfig
    from app.services.agent_service import agent_service
    from app.services.feishu_service import feishu_service

    try:
        # 解析URL
        doc_token, doc_type = feishu_service.parse_feishu_url(body.url)
    except ValueError as e:
        return Fail(msg=str(e))

    try:
        # 获取飞书bot凭证
        config = await GlobalConfig.filter(config_key="feishu_pull_bot").first()
        if not config:
            return Fail(msg="请先在全局配置中设置 feishu_pull_bot")
        bot = await feishu_bot_controller.get_by_app_id(app_id=config.config_value)
        access_token = await feishu_service.get_tenant_access_token(bot.app_id, bot.app_secret)

        # 拉取文档内容
        content = await feishu_service.fetch_document_content(doc_token, doc_type, access_token)
        if not content:
            return Fail(msg="文档内容为空")

        # LLM转Markdown
        result = await agent_service.run_agent("doc_to_markdown", {"document_content": content})
        if not result.get("success"):
            return Fail(msg="文档解析失败，请重试")

        return Success(data={"markdown_content": result["markdown_content"]})
    except Exception as e:
        logger.error("[DocTemplate] parse_url error: %s", e)
        return Fail(msg=f"解析失败: {str(e)}")


@router.get("/options", summary="获取模板下拉列表")
async def get_doc_template_options():
    objs = await DocTemplate.filter(is_deleted=False).all()
    data = [{"id": obj.id, "name": obj.name} for obj in objs]
    return Success(data=data)


@router.get("/by_agent", summary="根据AgentID查询绑定模板详情")
async def get_templates_by_agent(agent_id: int = Query(..., description="Agent ID")):
    agent = await Agent.get(id=agent_id)
    templates = await agent.doc_templates.filter(is_deleted=False).all()
    data = [await tpl.to_dict() for tpl in templates]
    return Success(data=data)


@router.post("/generate", summary="根据模板生成飞书云文档")
async def generate_feishu_doc(body: GenerateDocRequest):
    from app.controllers.feishu_bot import feishu_bot_controller
    from app.models.global_config import GlobalConfig
    from app.services.feishu_service import feishu_service

    # 获取模板信息验证
    tpl = await DocTemplate.filter(id=body.template_id, is_deleted=False).first()
    if not tpl:
        return Fail(msg="模板不存在或已删除")

    try:
        # 获取飞书bot凭证
        config = await GlobalConfig.filter(config_key="feishu_pull_bot").first()
        if not config:
            return Fail(msg="请先在全局配置中设置 feishu_pull_bot")
        bot = await feishu_bot_controller.get_by_app_id(app_id=config.config_value)
        access_token = await feishu_service.get_tenant_access_token(bot.app_id, bot.app_secret)

        # 调用飞书导入API创建文档
        doc_url = await feishu_service.import_markdown_to_folder(
            folder_token=tpl.folder_token,
            title=body.doc_name,
            markdown_content=body.markdown_content,
            access_token=access_token,
        )
        logger.info("[DocTemplate] Generated doc: template_id=%s, url=%s", body.template_id, doc_url)
        return Success(data={"url": doc_url, "name": body.doc_name})
    except Exception as e:
        logger.error("[DocTemplate] generate error: %s", e)
        return Fail(msg=f"文档生成失败: {str(e)}")

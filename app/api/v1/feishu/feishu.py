import json
import logging

from fastapi import APIRouter, BackgroundTasks, Query, Request
from tortoise.expressions import Q

from app.controllers.conversation import conversation_controller
from app.controllers.feishu_bot import feishu_bot_controller
from app.models.rag import Agent
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.feishu import FeishuBotConfigCreate, FeishuBotConfigUpdate
from app.services.bot_service import bot_service
from app.services.document_pipeline import document_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


def mask_secret(value: str) -> str:
    """脱敏: 保留前3后3字符，中间用*代替"""
    if not value or len(value) <= 6:
        return "******"
    return value[:3] + "*" * (len(value) - 6) + value[-3:]


# ========== 飞书机器人配置 CRUD ==========


@router.get("/bot/list", summary="飞书机器人列表")
async def list_feishu_bot(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
):
    total, objs = await feishu_bot_controller.list(page=page, page_size=page_size, order=["-created_at"])
    data = []
    for obj in objs:
        d = await obj.to_dict()
        d["app_secret"] = mask_secret(d.get("app_secret", ""))
        data.append(d)
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/bot/get", summary="飞书机器人详情")
async def get_feishu_bot(bot_id: int = Query(..., description="机器人ID")):
    obj = await feishu_bot_controller.get(id=bot_id)
    data = await obj.to_dict()
    data["app_secret"] = mask_secret(data.get("app_secret", ""))
    return Success(data=data)


@router.post("/bot/create", summary="创建飞书机器人配置")
async def create_feishu_bot(bot_in: FeishuBotConfigCreate):
    if bot_in.agent_id is not None and not await Agent.exists(id=bot_in.agent_id):
        return Fail(msg="绑定的Agent不存在")
    await feishu_bot_controller.create(bot_in)
    logger.info("[FeishuBot] Created: name=%s", bot_in.name)
    return Success(msg="创建成功")


@router.post("/bot/update", summary="更新飞书机器人配置")
async def update_feishu_bot(bot_in: FeishuBotConfigUpdate):
    if bot_in.agent_id is not None and not await Agent.exists(id=bot_in.agent_id):
        return Fail(msg="绑定的Agent不存在")
    update_data = bot_in.model_dump(exclude_unset=True, exclude={"id"})
    # 脱敏值含*号，说明用户未修改，不更新app_secret
    if "app_secret" in update_data and "*" in (update_data["app_secret"] or ""):
        del update_data["app_secret"]
    await feishu_bot_controller.update(id=bot_in.id, obj_in=update_data)
    logger.info("[FeishuBot] Updated: id=%s", bot_in.id)
    return Success(msg="更新成功")


@router.delete("/bot/delete", summary="删除飞书机器人配置")
async def delete_feishu_bot(bot_id: int = Query(..., description="机器人ID")):
    await feishu_bot_controller.remove(id=bot_id)
    logger.info("[FeishuBot] Deleted: id=%s", bot_id)
    return Success(msg="删除成功")


# ========== 会话/消息查询 ==========


@router.get("/conversations", summary="会话列表")
async def list_conversations(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    agent_id: int = Query(None, description="Agent ID"),
):
    q = Q()
    if agent_id is not None:
        q &= Q(agent_id=agent_id)
    total, objs = await conversation_controller.list(page=page, page_size=page_size, search=q, order=["-last_active_at"])
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/messages", summary="会话消息列表")
async def list_messages(
    conversation_id: int = Query(..., description="会话ID"),
    limit: int = Query(50, description="消息数量"),
):
    messages = await conversation_controller.get_messages(conversation_id, limit=limit)
    data = [await msg.to_dict() for msg in messages]
    return Success(data=data)


# ========== Webhook（无认证）==========


webhook_router = APIRouter()


@webhook_router.post("/webhook/{bot_id}", summary="飞书Webhook回调")
async def feishu_webhook(bot_id: int, request: Request, background_tasks: BackgroundTasks):
    body = await request.json()

    # URL 验证
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    # 获取机器人配置
    try:
        bot = await feishu_bot_controller.get(id=bot_id)
    except Exception:
        logger.warning("Webhook: bot not found, id=%s", bot_id)
        return {"code": 404, "msg": "bot not found"}

    if not bot.is_active:
        return {"code": 403, "msg": "bot disabled"}

    # 验证 token
    from app.services.feishu_service import feishu_service

    if not feishu_service.verify_webhook(body, bot.verification_token, bot.encrypt_key):
        logger.warning("Webhook: token verification failed, bot_id=%s", bot_id)
        return {"code": 401, "msg": "verification failed"}

    # 解析事件
    event = body.get("event", {})
    message = event.get("message", {})
    msg_type = message.get("message_type", "")
    chat_id = message.get("chat_id", "")
    sender = event.get("sender", {})
    feishu_open_id = sender.get("sender_id", {}).get("open_id", "")

    if msg_type != "text":
        return {"code": 200, "msg": "unsupported message type"}

    # 解析文本内容
    content_str = message.get("content", "{}")
    try:
        content_obj = json.loads(content_str)
        question = content_obj.get("text", "").strip()
    except json.JSONDecodeError:
        question = content_str.strip()

    if not question:
        return {"code": 200, "msg": "empty message"}

    # 去重: 检查 message_id
    feishu_message_id = message.get("message_id", "")
    from app.models.rag import ChatMessage

    existing = await ChatMessage.filter(feishu_message_id=feishu_message_id).first()
    if existing:
        return {"code": 200, "msg": "duplicate message"}

    # 将耗时的 RAG 处理 + 消息发送移入后台任务
    background_tasks.add_task(
        _process_webhook_message,
        bot_id=bot_id,
        bot=bot,
        feishu_open_id=feishu_open_id,
        chat_id=chat_id,
        question=question,
    )

    return {"code": 200, "msg": "ok"}


async def _process_webhook_message(
    bot_id: int, bot, feishu_open_id: str, chat_id: str, question: str
):
    """后台处理 webhook 消息: RAG 问答 + 飞书回复"""
    from app.services.feishu_service import feishu_service

    try:
        result = await bot_service.handle_message(
            bot_id=bot_id,
            feishu_open_id=feishu_open_id,
            chat_id=chat_id,
            question=question,
        )

        sources = result.get("sources", [])
        image_keys = await feishu_service.upload_image_keys_from_sources(
            bot.app_id, bot.app_secret, sources
        )
        card = await feishu_service.build_answer_card(result["answer"], sources, image_keys=image_keys)
        await feishu_service.send_message(
            app_id=bot.app_id,
            app_secret=bot.app_secret,
            chat_id=chat_id,
            content=json.dumps(card),
            msg_type="interactive",
        )
    except Exception as e:
        logger.exception(f"Webhook background processing failed: bot_id={bot_id}")

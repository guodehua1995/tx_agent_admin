import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from tortoise.expressions import Q

from app.controllers.agent import agent_controller
from app.controllers.conversation import conversation_controller
from app.core.ctx import CTX_USER_ID
from app.models.rag import ChatMessage, LLMProviderConfig
from app.schemas.agents import AgentCreate, AgentUpdate, UpdateKnowledgeBases
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="Agent列表")
async def list_agent(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    name: str = Query("", description="名称搜索"),
):
    q = Q()
    if name:
        q &= Q(name__contains=name)
    total, objs = await agent_controller.list(page=page, page_size=page_size, search=q, order=["-created_at"])
    data = [await obj.to_dict(m2m=True) for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="Agent详情")
async def get_agent(agent_id: int = Query(..., description="Agent ID")):
    obj = await agent_controller.get(id=agent_id)
    return Success(data=await obj.to_dict(m2m=True))


@router.post("/create", summary="创建Agent")
async def create_agent(agent_in: AgentCreate):
    if not await LLMProviderConfig.exists(id=agent_in.chat_model_id):
        return Fail(msg="对话模型配置不存在")
    obj = await agent_controller.create(agent_in)
    if agent_in.knowledge_base_ids:
        await agent_controller.update_knowledge_bases(obj, agent_in.knowledge_base_ids)
    logger.info("[Agent] Created: name=%s, id=%s", agent_in.name, obj.id)
    return Success(msg="创建成功")


@router.post("/update", summary="更新Agent")
async def update_agent(agent_in: AgentUpdate):
    if agent_in.chat_model_id is not None and not await LLMProviderConfig.exists(id=agent_in.chat_model_id):
        return Fail(msg="对话模型配置不存在")
    obj = await agent_controller.update(id=agent_in.id, obj_in=agent_in.model_dump(exclude_unset=True, exclude={"id", "knowledge_base_ids"}))
    if agent_in.knowledge_base_ids is not None:
        await agent_controller.update_knowledge_bases(obj, agent_in.knowledge_base_ids)
    logger.info("[Agent] Updated: id=%s", agent_in.id)
    return Success(msg="更新成功")


@router.delete("/delete", summary="删除Agent")
async def delete_agent(agent_id: int = Query(..., description="Agent ID")):
    await agent_controller.remove(id=agent_id)
    logger.info("[Agent] Deleted: id=%s", agent_id)
    return Success(msg="删除成功")


@router.post("/update_knowledge_bases", summary="更新Agent关联知识库")
async def update_agent_knowledge_bases(update_in: UpdateKnowledgeBases):
    agent = await agent_controller.get(id=update_in.agent_id)
    await agent_controller.update_knowledge_bases(agent, update_in.knowledge_base_ids)
    logger.info("[Agent] KBs updated: agent_id=%s, kb_ids=%s", update_in.agent_id, update_in.knowledge_base_ids)
    return Success(msg="更新成功")


@router.post("/chat", summary="与Agent对话（非流式）")
async def chat_with_agent(chat_in: ChatRequest):
    from app.services.rag_service import rag_service

    user_id = CTX_USER_ID.get()

    agent = await agent_controller.get(id=chat_in.agent_id)
    if not agent.is_active:
        return Fail(msg="该Agent已停用")

    knowledge_bases = await agent.knowledge_bases.all()
    if not knowledge_bases:
        return Fail(msg="该Agent未关联任何知识库")

    conv = await conversation_controller.get_or_create(agent_id=agent.id, user_id=user_id)

    recent_messages = await conversation_controller.get_messages(
        conv.id, limit=agent.max_history_turns * 2
    )
    history = [{"role": msg.role, "content": msg.content} for msg in reversed(list(recent_messages))]

    chat_model = await LLMProviderConfig.get(id=agent.chat_model_id)

    start_time = time.time()
    result = await rag_service.chat(
        question=chat_in.question,
        history=history,
        knowledge_bases=list(knowledge_bases),
        chat_model_config=chat_model,
        system_prompt=agent.system_prompt,
    )
    elapsed_ms = int((time.time() - start_time) * 1000)

    await ChatMessage.create(
        conversation_id=conv.id, role="user", content=chat_in.question
    )
    await ChatMessage.create(
        conversation_id=conv.id,
        role="assistant",
        content=result["answer"],
        retrieved_chunks=result["sources"],
        response_time_ms=elapsed_ms,
    )
    conv.message_count += 2
    conv.last_active_at = datetime.now()
    await conv.save()

    logger.info(
        "[Agent] Chat: agent_id=%s, user_id=%s, elapsed=%dms",
        chat_in.agent_id, user_id, elapsed_ms,
    )
    return Success(data=result)


@router.post("/chat/stream", summary="与Agent对话（流式SSE）")
async def chat_with_agent_stream(chat_in: ChatRequest):
    """流式对话接口，使用 SSE 格式返回
    
    连接超时：5秒
    流式请求超时：10秒
    """
    from app.services.rag_service import rag_service
    import asyncio

    user_id = CTX_USER_ID.get()

    agent = await agent_controller.get(id=chat_in.agent_id)
    if not agent.is_active:
        return Fail(msg="该Agent已停用")

    knowledge_bases = await agent.knowledge_bases.all()
    if not knowledge_bases:
        return Fail(msg="该Agent未关联任何知识库")

    conv = await conversation_controller.get_or_create(agent_id=agent.id, user_id=user_id)

    recent_messages = await conversation_controller.get_messages(
        conv.id, limit=agent.max_history_turns * 2
    )
    history = [{"role": msg.role, "content": msg.content} for msg in reversed(list(recent_messages))]

    chat_model = await LLMProviderConfig.get(id=agent.chat_model_id)

    start_time = time.time()
    full_answer = ""
    sources_data = []

    async def event_generator():
        nonlocal full_answer, sources_data
        try:
            logger.debug("[Agent] Chat stream started: agent_id=%s, user_id=%s", chat_in.agent_id, user_id)
            async for chunk in rag_service.chat_stream(
                question=chat_in.question,
                history=history,
                knowledge_bases=list(knowledge_bases),
                chat_model_config=chat_model,
                system_prompt=agent.system_prompt,
            ):
                chunk_type = chunk.get("type")
                content = chunk.get("content", "")
                
                if chunk_type == "delta":
                    full_answer += content
                    # SSE 格式：data: {...}\n\n
                    yield f"data: {json.dumps({'type': 'delta', 'content': content}, ensure_ascii=False)}\n\n"
        
                elif chunk_type == "sources":
                    sources_data = content if content else []
                    yield f"data: {json.dumps({'type': 'sources', 'content': sources_data}, ensure_ascii=False)}\n\n"
                  
                elif chunk_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': content}, ensure_ascii=False)}\n\n"
                  
                    return
                    
            # 发送完成标记
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"[Agent] Chat stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            # 保存对话记录
            try:
                elapsed_ms = int((time.time() - start_time) * 1000)
                await ChatMessage.create(
                    conversation_id=conv.id, role="user", content=chat_in.question
                )
                await ChatMessage.create(
                    conversation_id=conv.id,
                    role="assistant",
                    content=full_answer or "（无响应）",
                    retrieved_chunks=sources_data,
                    response_time_ms=elapsed_ms,
                )
                conv.message_count += 2
                conv.last_active_at = datetime.now()
                await conv.save()
                
                logger.info(
                    "[Agent] Chat stream completed: agent_id=%s, user_id=%s, elapsed=%dms",
                    chat_in.agent_id, user_id, elapsed_ms,
                )
            except Exception as save_err:
                logger.error(f"[Agent] Failed to save chat message: {save_err}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )

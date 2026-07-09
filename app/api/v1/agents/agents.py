import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from tortoise.expressions import Q

from app.controllers.agent import agent_controller
from app.controllers.ai_config import ai_config_controller
from app.controllers.conversation import conversation_controller
from app.core.ctx import CTX_USER_ID
from app.models.rag import ChatMessage
from app.schemas.agents import AgentCreate, AgentUpdate
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_chat_model():
    """获取活跃的 Chat 模型（LangChain ChatOpenAI 实例）"""
    from langchain_openai import ChatOpenAI

    models = await ai_config_controller.get_active_chat_models()
    if not models:
        raise RuntimeError("无可用 Chat 模型")
    cfg = models[0]
    extra = cfg.extra_config or {}
    return ChatOpenAI(
        model=cfg.model_name,
        api_key=cfg.api_key,
        base_url=cfg.api_base_url,
        temperature=extra.get("temperature", 0.7),
        max_tokens=extra.get("max_tokens") or cfg.max_tokens,
    )


async def _route_agent(agent_code: str, llm):
    """按 code 路由到对应的 Agent 实例"""
    from app.agents.registry import AgentRegistry

    agent_cls = AgentRegistry.get(agent_code)
    return agent_cls(llm=llm)


async def _save_chat_messages(
    conv, question: str, result: dict, elapsed_ms: int,
):
    """保存对话消息到数据库"""
    await ChatMessage.create(
        conversation_id=conv.id, type="user", content=question,
    )
    for tc in result.get("tool_calls", []):
        await ChatMessage.create(
            conversation_id=conv.id,
            type="tool_call",
            content=json.dumps(
                {"tool_name": tc["tool_name"], "tool_input": tc["tool_input"]},
                ensure_ascii=False,
            ),
        )
        await ChatMessage.create(
            conversation_id=conv.id,
            type="tool_call_result",
            content=json.dumps(
                {"tool_name": tc["tool_name"], "result": tc["tool_output"]},
                ensure_ascii=False,
            ),
        )
    await ChatMessage.create(
        conversation_id=conv.id,
        type="assistant",
        content=result["answer"],
        retrieved_chunks=result.get("sources", []),
        response_time_ms=elapsed_ms,
    )
    tool_msg_count = len(result.get("tool_calls", [])) * 2
    conv.message_count += 2 + tool_msg_count
    conv.last_active_at = datetime.now()
    await conv.save()


# ── CRUD ──────────────────────────────────────────────────────────


@router.get("/list", summary="Agent列表")
async def list_agent(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    name: str = Query("", description="名称搜索"),
):
    q = Q()
    if name:
        q &= Q(name__contains=name)
    total, objs = await agent_controller.list(
        page=page, page_size=page_size, search=q, order=["-created_at"],
    )
    # 不再有 M2M 字段，m2m=False
    data = [await obj.to_dict(m2m=False) for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="Agent详情")
async def get_agent(agent_id: int = Query(..., description="Agent ID")):
    obj = await agent_controller.get(id=agent_id)
    return Success(data=await obj.to_dict(m2m=False))


@router.post("/create", summary="创建Agent")
async def create_agent(agent_in: AgentCreate):
    obj = await agent_controller.create(agent_in)
    logger.info("[Agent] Created: name=%s, code=%s, id=%s", agent_in.name, agent_in.code, obj.id)
    return Success(msg="创建成功")


@router.post("/update", summary="更新Agent")
async def update_agent(agent_in: AgentUpdate):
    await agent_controller.update(
        id=agent_in.id,
        obj_in=agent_in.model_dump(exclude_unset=True, exclude={"id"}),
    )
    logger.info("[Agent] Updated: id=%s", agent_in.id)
    return Success(msg="更新成功")


@router.delete("/delete", summary="删除Agent")
async def delete_agent(agent_id: int = Query(..., description="Agent ID")):
    await agent_controller.remove(id=agent_id)
    logger.info("[Agent] Deleted: id=%s", agent_id)
    return Success(msg="删除成功")


# ── 对话 ──────────────────────────────────────────────────────────


@router.post("/chat", summary="与Agent对话（非流式）")
async def chat_with_agent(chat_in: ChatRequest):
    user_id = CTX_USER_ID.get()

    agent = await agent_controller.get(id=chat_in.agent_id)
    if not agent.is_active:
        return Fail(msg="该Agent已停用")
    if not agent.code:
        return Fail(msg="该Agent未配置路由标识(code)，无法执行")

    try:
        llm = await _get_chat_model()
        agent_instance = await _route_agent(agent.code, llm)
    except RuntimeError as e:
        return Fail(msg=str(e))
    except KeyError:
        return Fail(msg=f"Agent '{agent.code}' 未注册，请检查 agents/ 目录")

    conv = await conversation_controller.get_or_create(
        agent_id=agent.id, user_id=user_id,
    )

    start_time = time.time()
    result = await agent_instance.execute({
        "question": chat_in.question,
        "conversation_id": conv.id,
        "user_id": user_id,
        "agent_id": agent.id,
    })
    elapsed_ms = int((time.time() - start_time) * 1000)

    await _save_chat_messages(conv, chat_in.question, result, elapsed_ms)

    logger.info(
        "[Agent] Chat: agent_id=%s, code=%s, user_id=%s, elapsed=%dms",
        chat_in.agent_id, agent.code, user_id, elapsed_ms,
    )
    return Success(data=result)


@router.post("/chat/stream", summary="与Agent对话（流式SSE）")
async def chat_with_agent_stream(chat_in: ChatRequest):
    user_id = CTX_USER_ID.get()

    agent = await agent_controller.get(id=chat_in.agent_id)
    if not agent.is_active:
        return Fail(msg="该Agent已停用")
    if not agent.code:
        return Fail(msg="该Agent未配置路由标识(code)，无法执行")

    try:
        llm = await _get_chat_model()
        agent_instance = await _route_agent(agent.code, llm)
    except RuntimeError as e:
        return Fail(msg=str(e))
    except KeyError:
        return Fail(msg=f"Agent '{agent.code}' 未注册，请检查 agents/ 目录")

    conv = await conversation_controller.get_or_create(
        agent_id=agent.id, user_id=user_id,
    )

    start_time = time.time()
    full_answer = ""
    sources_data = []
    tool_calls_data = []

    async def event_generator():
        nonlocal full_answer, sources_data, tool_calls_data
        try:
            logger.debug(
                "[Agent] Chat stream started: agent_id=%s, code=%s, user_id=%s",
                chat_in.agent_id, agent.code, user_id,
            )

            # 如果 Agent 支持流式执行，走流式；否则走非流式
            if hasattr(agent_instance, 'execute_stream'):
                async for chunk in agent_instance.execute_stream({
                    "question": chat_in.question,
                    "conversation_id": conv.id,
                    "user_id": user_id,
                    "agent_id": agent.id,
                }):
                    chunk_type = chunk.get("type")
                    content = chunk.get("content", "")

                    if chunk_type == "delta":
                        full_answer += content
                        yield f"data: {json.dumps({'type': 'delta', 'content': content}, ensure_ascii=False)}\n\n"
                    elif chunk_type == "tool_calls":
                        tool_calls_data = content if content else []
                    elif chunk_type == "sources":
                        sources_data = content if content else []
                        yield f"data: {json.dumps({'type': 'sources', 'content': sources_data}, ensure_ascii=False)}\n\n"
                    elif chunk_type == "error":
                        yield f"data: {json.dumps({'type': 'error', 'content': content}, ensure_ascii=False)}\n\n"
                        return
            else:
                result = await agent_instance.execute({
                    "question": chat_in.question,
                    "conversation_id": conv.id,
                    "user_id": user_id,
                    "agent_id": agent.id,
                })
                full_answer = result.get("answer", "")
                sources_data = result.get("sources", [])
                tool_calls_data = result.get("tool_calls", [])
                yield f"data: {json.dumps({'type': 'delta', 'content': full_answer}, ensure_ascii=False)}\n\n"
                if sources_data:
                    yield f"data: {json.dumps({'type': 'sources', 'content': sources_data}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"[Agent] Chat stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            try:
                elapsed_ms = int((time.time() - start_time) * 1000)
                await _save_chat_messages(
                    conv, chat_in.question,
                    {"answer": full_answer or "（无响应）", "sources": sources_data, "tool_calls": tool_calls_data},
                    elapsed_ms,
                )
                logger.info(
                    "[Agent] Chat stream completed: agent_id=%s, code=%s, user_id=%s, elapsed=%dms",
                    chat_in.agent_id, agent.code, user_id, elapsed_ms,
                )
            except Exception as save_err:
                logger.error(f"[Agent] Failed to save chat message: {save_err}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

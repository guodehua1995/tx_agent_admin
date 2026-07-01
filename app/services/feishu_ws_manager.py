"""
飞书机器人长连接客户端管理器

为每个启用的飞书机器人创建 WebSocket 长连接，实时接收消息。
"""

import asyncio
import os
import ssl
import threading
from typing import Dict, Optional

import json
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from app.controllers.feishu_bot import feishu_bot_controller
from app.log import logger
from app.models.rag import FeishuBotConfig
from app.services.bot_service import bot_service
from app.services.document_pipeline import document_pipeline
from app.services.feishu_service import FeishuService
from app.settings import settings

# 开发环境跳过飞书 SSL 证书验证（Mac 本地证书链问题）
if not settings.FEISHU_VERIFY_SSL:
    os.environ["CURL_CA_BUNDLE"] = ""
    os.environ["REQUESTS_CA_BUNDLE"] = ""

    import websockets

    _original_connect_cls = websockets.connect

    class _InsecureConnect(_original_connect_cls):
        def __init__(self, *args, **kwargs):
            if "ssl" not in kwargs:
                kwargs["ssl"] = ssl._create_unverified_context()
            super().__init__(*args, **kwargs)

    websockets.connect = _InsecureConnect


class FeishuBotClientManager:
    """飞书机器人 WS 客户端管理器（单例）"""

    _instance: Optional["FeishuBotClientManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "FeishuBotClientManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        # bot_id -> Client 实例
        self._clients: Dict[int, object] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._feishu_service = FeishuService()
        # 所有飞书机器人共享同一个 WS event loop（lark_oapi.ws.client 使用模块级全局 loop 变量，
        # 多机器人各自创建 loop 会互相覆盖导致连接异常）
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """设置 asyncio 事件循环，用于从同步回调中调用异步业务逻辑"""
        self._loop = loop

    async def start_all(self):
        """启动所有启用的飞书机器人长连接"""
        bots = await FeishuBotConfig.filter(is_active=True).all()
        logger.info(f"[FeishuWS] 发现 {len(bots)} 个启用的飞书机器人")

        for bot in bots:
            self._start_bot_client(bot)

    def _ensure_ws_loop(self):
        """确保共享 WS event loop 已创建并运行

        lark_oapi.ws.client 模块使用模块级全局变量 `loop`，多个机器人各自创建 event loop
        会互相覆盖该全局变量，导致先启动的机器人连接异常。
        解决方案：所有机器人共享同一个 event loop。
        """
        if self._ws_loop is not None and self._ws_loop.is_running():
            return

        self._ws_loop = asyncio.new_event_loop()
        import lark_oapi.ws.client as ws_client
        ws_client.loop = self._ws_loop

        def _run_ws_loop():
            asyncio.set_event_loop(self._ws_loop)
            try:
                logger.info("[FeishuWS] 启动共享 WS event loop")
                self._ws_loop.run_forever()
            except Exception as e:
                logger.exception(f"[FeishuWS] WS event loop 异常: {e}")
            finally:
                self._ws_loop.close()

        self._ws_thread = threading.Thread(target=_run_ws_loop, name="feishu-ws-loop", daemon=True)
        self._ws_thread.start()

    def _start_bot_client(self, bot: FeishuBotConfig):
        """为单个机器人启动 WS 客户端（在共享 WS event loop 上运行）"""
        if bot.id in self._clients:
            logger.warning(f"[FeishuWS] 机器人 {bot.name}(id={bot.id}) 已存在连接，跳过")
            return

        def on_message(data: P2ImMessageReceiveV1) -> None:
            """同步回调：收到飞书消息"""
            try:
                event = data.event
                message = event.message
                sender = event.sender

                # 只处理文本消息
                if message.message_type != "text":
                    return

                # 不处理群聊消息
                if message.chat_type == "group":
                    return

                # 提取消息内容（JSON 字符串需要解析）
                content = json.loads(message.content)
                text = content.get("text", "").strip()
                if not text:
                    return

                chat_id = message.chat_id
                sender_id = sender.sender_id.open_id
                bot_id = bot.id
                message_id = message.message_id

                # TODO 通过open_id获取用户信息 如果用户不存在则返回card 提示用户无权限
                

                logger.debug(f"[FeishuWS] 收到消息: bot={bot.name}, sender={sender_id}, text={text[:50]}...")

                # 从同步回调中调度异步处理
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._handle_message_async(bot_id, sender_id, chat_id, text, message_id),
                        self._loop,
                    )
                else:
                    logger.error("[FeishuWS] 事件循环未就绪，无法处理消息")
            except Exception as e:
                logger.exception(f"[FeishuWS] 消息处理异常: bot={bot.name}", e)

        # 构建事件处理器
        # 空处理已读消息事件，防止 keepalive ping timeout
        def on_message_read(data) -> None:
            pass  # 已读事件无需处理，仅用于维持连接活跃

        event_handler = (
            lark.EventDispatcherHandler.builder(bot.verification_token or "", bot.encrypt_key or "")
            .register_p2_im_message_receive_v1(on_message)
            .register_p2_im_message_message_read_v1(on_message_read)
            .build()
        )

        # 创建 WS 客户端
        cli = lark.ws.Client(
            app_id=bot.app_id,
            app_secret=bot.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.ERROR,
            auto_reconnect=True,  # 断线自动重连
        )

    
        # 确保共享 WS event loop 已启动（所有机器人共用一个 loop）
        self._ensure_ws_loop()

        # 在共享 loop 上异步启动连接
        async def _start_bot_connection():
            try:
                logger.info(f"[FeishuWS] 启动连接: bot={bot.name}(id={bot.id})")
                await cli._connect()
                self._ws_loop.create_task(cli._ping_loop())
            except Exception as e:
                logger.error(f"[FeishuWS] 连接异常: bot={bot.name}(id={bot.id}): {e}")
                if cli._auto_reconnect:
                    self._ws_loop.create_task(cli._reconnect())

        asyncio.run_coroutine_threadsafe(_start_bot_connection(), self._ws_loop)

        self._clients[bot.id] = cli
        logger.info(f"[FeishuWS] 已启动: bot={bot.name}(id={bot.id})")

    async def _handle_message_async(
        self, bot_id: int, sender_open_id: str, chat_id: str, question: str, message_id: str
    ):
        """异步处理消息：加 THINKING 表情 → 调用 RAG 问答 → 回复 → 换成 DONE 表情"""
        # 提前获取 bot 配置，reaction 和 reply 都需要
        bot = await feishu_bot_controller.get(id=bot_id)

        # 1. 添加"处理中"表情
        reaction_id = None
        try:
            reaction_id = await self._feishu_service.add_message_reaction(
                bot.app_id, bot.app_secret, message_id, "THINKING"
            )
        except Exception:
            pass  # reaction 失败不阻塞主流程

        try:
            # 2. 调用业务逻辑处理消息
            result = await bot_service.handle_message(
                bot_id=bot_id,
                feishu_open_id=sender_open_id,
                chat_id=chat_id,
                question=question,
            )

            answer = result.get("answer", "抱歉，暂时无法回答您的问题。")
            sources = result.get("sources", [])

            # 3. 构建回复卡片并发送
            image_keys = await self._feishu_service.upload_image_keys_from_sources(
                bot.app_id, bot.app_secret, sources
            )
            card = await self._feishu_service.build_answer_card(answer, sources, image_keys=image_keys)

            await self._feishu_service.send_message(
                app_id=bot.app_id,
                app_secret=bot.app_secret,
                chat_id=chat_id,
                content=json.dumps(card),
                msg_type="interactive",
            )
            logger.info(f"[FeishuWS] 已回复: bot_id={bot_id}, chat_id={chat_id}")

            # 4. 处理成功 → 换成 DONE
            if reaction_id:
                try:
                    await self._feishu_service.change_message_reaction(
                        bot.app_id, bot.app_secret, message_id, reaction_id, "DONE"
                    )
                except Exception:
                    pass

        except ValueError as e:
            logger.error(f"[FeishuWS] 处理消息失败: bot_id={bot_id}: {e}")
            # 错误 → 换成 ERROR 表情
            if reaction_id:
                try:
                    await self._feishu_service.change_message_reaction(
                        bot.app_id, bot.app_secret, message_id, reaction_id, "ERROR"
                    )
                except Exception:
                    pass
            await self._feishu_service.send_message(
                app_id=bot.app_id,
                app_secret=bot.app_secret,
                chat_id=chat_id,
                content=json.dumps({"text": str(e)}),
                msg_type="text",
            )
        except Exception as e:
            logger.exception(f"[FeishuWS] 处理消息失败: bot_id={bot_id}")
            # 错误 → 换成 ERROR 表情
            if reaction_id:
                try:
                    await self._feishu_service.change_message_reaction(
                        bot.app_id, bot.app_secret, message_id, reaction_id, "ERROR"
                    )
                except Exception:
                    pass
            # 尝试发送错误提示
            try:
                await self._feishu_service.send_message(
                    app_id=bot.app_id,
                    app_secret=bot.app_secret,
                    chat_id=chat_id,
                    content=json.dumps({"text": "抱歉，处理消息时出现错误，请稍后重试。"}),
                    msg_type="text",
                )
            except Exception:
                pass

    async def add_bot(self, bot_id: int):
        """动态添加一个机器人连接（如新建机器人后）"""
        bot = await FeishuBotConfig.get_or_none(id=bot_id, is_active=True)
        if not bot:
            logger.warning(f"[FeishuWS] 机器人不存在或未启用: id={bot_id}")
            return
        self._start_bot_client(bot)

    async def remove_bot(self, bot_id: int):
        """移除一个机器人连接（如删除或停用机器人时）"""
        if bot_id not in self._clients:
            return

        cli = self._clients.pop(bot_id)
        try:
            if self._ws_loop and self._ws_loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(cli._disconnect(), self._ws_loop)
                fut.result(timeout=5)
            logger.info(f"[FeishuWS] 移除连接: bot_id={bot_id}")
        except Exception as e:
            logger.exception(f"[FeishuWS] 移除连接异常: bot_id={bot_id}")

    async def stop_all(self):
        """停止所有连接"""
        logger.info(f"[FeishuWS] 停止所有连接, 数量={len(self._clients)}")
        for bot_id in list(self._clients.keys()):
            await self.remove_bot(bot_id)
        self._clients.clear()

        # 停止共享 WS event loop
        if self._ws_loop and self._ws_loop.is_running():
            self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
            if self._ws_thread:
                self._ws_thread.join(timeout=5)
            self._ws_loop = None
            self._ws_thread = None
            logger.info("[FeishuWS] 共享 WS event loop 已停止")

    def list_active(self) -> Dict[int, str]:
        """列出当前活跃的连接"""
        return {bot_id: "connected" for bot_id in self._clients.keys()}


# 全局单例
feishu_ws_manager = FeishuBotClientManager()

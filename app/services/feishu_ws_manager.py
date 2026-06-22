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

        # bot_id -> (client_thread, client_instance)
        self._clients: Dict[int, tuple] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._feishu_service = FeishuService()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """设置 asyncio 事件循环，用于从同步回调中调用异步业务逻辑"""
        self._loop = loop

    async def start_all(self):
        """启动所有启用的飞书机器人长连接"""
        bots = await FeishuBotConfig.filter(is_active=True).all()
        logger.info(f"[FeishuWS] 发现 {len(bots)} 个启用的飞书机器人")

        for bot in bots:
            self._start_bot_client(bot)

    def _start_bot_client(self, bot: FeishuBotConfig):
        """为单个机器人启动 WS 客户端（在线程中运行）"""
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

                # 提取消息内容（JSON 字符串需要解析）
                content = json.loads(message.content)
                text = content.get("text", "").strip()
                if not text:
                    return

                chat_id = message.chat_id
                sender_id = sender.sender_id.open_id
                bot_id = bot.id

                # TODO 通过open_id获取用户信息 如果用户不存在则返回card 提示用户无权限
                

                logger.debug(f"[FeishuWS] 收到消息: bot={bot.name}, sender={sender_id}, text={text[:50]}...")

                # 从同步回调中调度异步处理
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._handle_message_async(bot_id, sender_id, chat_id, text),
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

    
        def run_client():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                logger.info(f"[FeishuWS] 启动连接: bot={bot.name}(id={bot.id})")
                import lark_oapi.ws.client as ws_client
                ws_client.loop = new_loop
                cli.start()
            except Exception as e:
                logger.exception(f"[FeishuWS] 连接异常: bot={bot.name}")
            finally:
                new_loop.close()

        thread = threading.Thread(target=run_client, name=f"feishu-ws-{bot.id}", daemon=True)
        thread.start()

        self._clients[bot.id] = (thread, cli)
        logger.info(f"[FeishuWS] 已启动: bot={bot.name}(id={bot.id})")

    async def _handle_message_async(self, bot_id: int, sender_open_id: str, chat_id: str, question: str):
        """异步处理消息：调用 RAG 问答并回复"""
        try:
            # 调用业务逻辑处理消息
            result = await bot_service.handle_message(
                bot_id=bot_id,
                feishu_open_id=sender_open_id,
                chat_id=chat_id,
                question=question,
            )

            answer = result.get("answer", "抱歉，暂时无法回答您的问题。")
            sources = result.get("sources", [])

            # 构建回复卡片
            bot = await feishu_bot_controller.get(id=bot_id)
            image_keys = await self._feishu_service.upload_image_keys_from_sources(
                bot.app_id, bot.app_secret, sources
            )
            card = await self._feishu_service.build_answer_card(answer, sources, image_keys=image_keys)

            # 发送回复
            await self._feishu_service.send_message(
                app_id=bot.app_id,
                app_secret=bot.app_secret,
                chat_id=chat_id,
                content=json.dumps(card),
                msg_type="interactive",
            )
            logger.info(f"[FeishuWS] 已回复: bot_id={bot_id}, chat_id={chat_id}")
        except ValueError as e:
            logger.error(f"[FeishuWS] 处理消息失败: bot_id={bot_id}: {e}")
            await self._feishu_service.send_message(
                app_id=bot.app_id,
                app_secret=bot.app_secret,
                chat_id=chat_id,
                content=json.dumps({"text": str(e)}),
                msg_type="text",
            )
        except Exception as e:
            logger.exception(f"[FeishuWS] 处理消息失败: bot_id={bot_id}")
            # 尝试发送错误提示
            try:
                bot = await feishu_bot_controller.get(id=bot_id)
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

        thread, cli = self._clients.pop(bot_id)
        try:
            # lark.ws.Client 没有显式 stop 方法，依赖线程终止
            logger.info(f"[FeishuWS] 移除连接: bot_id={bot_id}")
        except Exception as e:
            logger.exception(f"[FeishuWS] 移除连接异常: bot_id={bot_id}")

    async def stop_all(self):
        """停止所有连接"""
        logger.info(f"[FeishuWS] 停止所有连接, 数量={len(self._clients)}")
        for bot_id in list(self._clients.keys()):
            await self.remove_bot(bot_id)
        self._clients.clear()

    def list_active(self) -> Dict[int, str]:
        """列出当前活跃的连接"""
        return {
            bot_id: f"thread_alive={thread.is_alive()}"
            for bot_id, (thread, _) in self._clients.items()
        }


# 全局单例
feishu_ws_manager = FeishuBotClientManager()

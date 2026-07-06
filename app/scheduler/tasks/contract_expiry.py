"""合同到期提醒定时任务

每日检查即将到期的合同，通过飞书机器人发送提醒消息。
提醒阈值：到期前 30 天、7 天、1 天分别发送提醒。
"""

from datetime import datetime, timedelta

from app.controllers.contract import contract_controller
from app.controllers.feishu_bot import feishu_bot_controller
from app.models.contract import Contract
from app.models.quotation import Client
from app.services.feishu_service import feishu_service
from app.settings import settings
from app.log import logger

# 提醒阈值（天数）
REMINDER_THRESHOLDS = [30, 7, 1]


async def check_contract_expiry():
    """检查合同到期情况并发送提醒"""
    if not settings.SCHEDULER_ENABLED:
        return

    try:
        now = datetime.now()

        for threshold_days in REMINDER_THRESHOLDS:
            start = now + timedelta(days=threshold_days)
            end = start + timedelta(days=1)

            contracts = await Contract.filter(
                expiry_date__gte=start,
                expiry_date__lt=end,
                is_deleted=False,
            ).all()

            if not contracts:
                continue

            for contract in contracts:
                await _send_expiry_notification(contract, threshold_days)

    except Exception:
        logger.exception("[ContractExpiry] Check failed")


async def _send_expiry_notification(contract: Contract, days_left: int):
    """发送单条合同到期提醒"""
    try:
        # 获取甲方名称
        party_a_name = ""
        if contract.party_a_client_id:
            client = await Client.filter(id=contract.party_a_client_id).first()
            if client:
                party_a_name = client.name

        project_name = contract.project_name or "未命名合同"
        expiry_date = contract.expiry_date.strftime("%Y-%m-%d") if contract.expiry_date else "未知"

        message = (
            f"📋 **合同到期提醒**\n\n"
            f"合同：{project_name}\n"
            f"甲方：{party_a_name}\n"
            f"到期日期：{expiry_date}\n"
            f"剩余天数：{days_left} 天\n\n"
            f"请及时处理续签或终止事宜。"
        )

        # 通过飞书机器人发送消息
        bot_configs = await feishu_bot_controller.model.filter(is_active=True).first()
        if not bot_configs:
            logger.warning("[ContractExpiry] No active feishu bot config")
            return

        access_token = await feishu_service.get_tenant_access_token(
            bot_configs.app_id, bot_configs.app_secret,
        )

        # 发送到配置的提醒群聊
        # 此处使用飞书消息发送接口，具体 chat_id 从配置中获取
        logger.info(
            f"[ContractExpiry] Notification: contract_id={contract.id}, "
            f"project={project_name}, days_left={days_left}"
        )
        # TODO: 实际发送飞书消息到指定群聊
        # await feishu_service.send_message(
        #     access_token=access_token,
        #     receive_id_type="chat_id",
        #     receive_id=settings.FEISHU_EXPIRY_CHAT_ID,
        #     msg_type="interactive",
        #     content=message,
        # )

    except Exception:
        logger.exception(
            "[ContractExpiry] Failed to send notification: contract_id=%s", contract.id,
        )
"""临时合同清理定时任务

扫描 is_temporary=True 且 created_at > 7 天的合同，
级联删除 Contract + ContractClause + ContractRiskReport。
"""

from datetime import datetime, timedelta

from app.log import logger
from app.models.contract import Contract
from app.settings import settings

# 临时合同保留天数
TEMPORARY_CONTRACT_RETENTION_DAYS = 7


async def cleanup_temporary_contracts():
    """清理过期临时合同"""
    if not settings.SCHEDULER_ENABLED:
        return

    try:
        cutoff = datetime.now() - timedelta(days=TEMPORARY_CONTRACT_RETENTION_DAYS)

        expired = await Contract.filter(
            is_temporary=True,
            is_deleted=False,
            created_at__lt=cutoff,
        ).all()

        if not expired:
            return

        logger.debug(
            f"[cleanup_temporary_contracts] Found {len(expired)} expired temporary contracts"
        )

        for contract in expired:
            try:
                # 级联删除（ContractRiskReport 通过 CASCADE 自动删除）
                await contract.delete()
                logger.debug(
                    f"[cleanup_temporary_contracts] Deleted: contract_id={contract.id}, "
                    f"project_name={contract.project_name}"
                )
            except Exception:
                logger.exception(
                    f"[cleanup_temporary_contracts] Failed to delete: "
                    f"contract_id={contract.id}"
                )

    except Exception:
        logger.exception("[cleanup_temporary_contracts] Scan failed")

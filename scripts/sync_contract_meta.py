"""一次性脚本：从合同摘要中提取签约日期/到期日期/金额，回填到 Contract 表。

仅用于同步旧数据，执行完可删除。

用法：在项目根目录执行
    python scripts/sync_contract_meta.py
"""

import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from tortoise import Tortoise
from app.settings.config import settings
from app.models.contract import Contract
from app.models.rag import LLMProviderConfig

logger = logging.getLogger(__name__)


# ── 解析工具（复用 slicing/contract.py 中的逻辑）──────────────────────────

def _parse_date(date_str: str) -> Optional[datetime]:
    """解析日期字符串为 datetime，支持多种格式；解析失败返回 None"""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _parse_amount(amount_val) -> Optional[Decimal]:
    """解析金额，返回 Decimal；解析失败返回 None"""
    if amount_val is None:
        return None
    try:
        val = Decimal(str(amount_val))
        return val if val >= 0 else None
    except Exception:
        return None


# ── LLM 调用 ──────────────────────────────────────────────────────────────

EXTRACT_FROM_SUMMARY_PROMPT = """你是合同解析助手。从以下合同摘要中提取关键签约数据。

返回 JSON（不要包裹代码块，不要任何额外说明）：
{"signing_date": "YYYY-MM-DD", "expiry_date": "YYYY-MM-DD", "total_amount": 数字}

要求：
1. signing_date 为合同签订日期，expiry_date 为合同到期日期，格式统一为 YYYY-MM-DD；
2. total_amount 为合同总金额（数字，不含货币符号），如无法识别填 null；
3. 若合同未明确约定到期日（如"长期有效"），expiry_date 填空字符串；
4. 若摘要中未提及，对应字段填空字符串或 null。"""


async def call_llm(model_config: LLMProviderConfig, system_prompt: str, user_content: str) -> str:
    """调用 LLM，返回响应文本"""
    from llama_index.core.llms import ChatMessage as LiChatMessage
    from llama_index.llms.openai_like import OpenAILike

    extra = model_config.extra_config or {}
    llm = OpenAILike(
        api_base=model_config.api_base_url,
        api_key=model_config.api_key,
        model=model_config.model_name,
        max_tokens=model_config.max_tokens,
        temperature=extra.get("temperature", 0.3),
        is_chat_model=True,
    )

    messages = [
        LiChatMessage(role="system", content=system_prompt),
        LiChatMessage(role="user", content=user_content),
    ]

    response = await llm.achat(messages)
    return (response.message.content or "").strip()


# ── 主逻辑 ────────────────────────────────────────────────────────────────

async def main():
    # 初始化数据库
    await Tortoise.init(config=settings.TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)

    # 获取活跃的 Chat 模型
    chat_model = await LLMProviderConfig.filter(is_active=True, is_embedding=False).first()
    if not chat_model:
        print("[ERROR] 没有可用的 Chat 模型配置，请先配置 AI 模型。")
        await Tortoise.close_connections()
        return

    print(f"[INFO] 使用模型: {chat_model.model_name}")

    # 查询需要回填的合同：有摘要但缺少任一目标字段
    from tortoise.expressions import Q
    contracts = await Contract.filter(
        Q(is_deleted=False),
        Q(summary__not_isnull=True),
        Q(summary__not=""),
        Q(signing_date__isnull=True) | Q(expiry_date__isnull=True) | Q(total_amount__isnull=True),
    ).all()

    print(f"[INFO] 找到 {len(contracts)} 条需要回填的合同")

    if not contracts:
        print("[INFO] 无需处理，退出。")
        await Tortoise.close_connections()
        return

    updated = 0
    skipped = 0
    failed = 0

    for contract in contracts:
        summary = (contract.summary or "").strip()
        if not summary:
            skipped += 1
            continue

        print(f"[INFO] 处理: id={contract.id}, project_name={contract.project_name}")

        try:
            raw = await call_llm(chat_model, EXTRACT_FROM_SUMMARY_PROMPT, summary)
            # 剥离可能的代码块包裹
            raw = re.sub(r'^```(?:json)?\s*', '', raw.strip())
            raw = re.sub(r'\s*```$', '', raw)
            data = json.loads(raw)

            signing_date = _parse_date(data.get("signing_date", ""))
            expiry_date = _parse_date(data.get("expiry_date", ""))
            total_amount = _parse_amount(data.get("total_amount"))

            # 只更新非空值，避免覆盖已有数据
            update_fields = []
            if signing_date and contract.signing_date is None:
                contract.signing_date = signing_date
                update_fields.append("signing_date")
            if expiry_date and contract.expiry_date is None:
                contract.expiry_date = expiry_date
                update_fields.append("expiry_date")
            if total_amount is not None and contract.total_amount is None:
                contract.total_amount = total_amount
                update_fields.append("total_amount")

            if update_fields:
                await contract.save(update_fields=update_fields)
                print(f"  [OK] 更新了: {', '.join(update_fields)}")
                updated += 1
            else:
                print(f"  [SKIP] 无需更新（LLM 未提取到有效值或字段已有值）")
                skipped += 1

        except Exception as e:
            logger.exception(f"处理合同 id={contract.id} 失败: {e}")
            print(f"  [FAIL] {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"完成！更新: {updated}, 跳过: {skipped}, 失败: {failed}")
    print(f"{'='*50}")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
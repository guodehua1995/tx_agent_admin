"""合同风险审查定时任务

扫描 status=pending 的审查记录，逐合同执行审查：
1. 组装条款目录树（一级条款 + 子条款）
2. Semaphore(2) 并发控制，每个一级条款启动审查 Agent
3. 汇总所有条款审查结果 → Markdown 报告
4. 写入飞书云文档
5. 更新审查记录 + 通知用户
"""

import asyncio
import json
from datetime import datetime

from app.log import logger
from app.models.contract import Contract, ContractRiskReport
from app.controllers.ai_config import ai_config_controller
from app.settings import settings
from app.services.contract_service import contract_service
from app.services.feishu_service import feishu_service
from app.controllers.feishu_bot import feishu_bot_controller
from app.agents.executor import agent_executor

# 并发控制：单机环境，同时最多 2 个条款审查
_REVIEW_SEMAPHORE = asyncio.Semaphore(2)


async def review_contracts():
    """扫描并执行合同审查任务"""
    if not settings.SCHEDULER_ENABLED:
        return

    try:
        # 获取待处理的审查记录
        pending_reports = await ContractRiskReport.filter(
            status="pending",
        ).order_by("created_at").limit(5)

        if not pending_reports:
            return

        logger.debug(f"[review_contracts] Found {len(pending_reports)} pending reports")

        for report in pending_reports:
            try:
                await _process_review(report)
            except Exception:
                logger.exception(
                    f"[review_contracts] Report {report.id} failed"
                )

    except Exception:
        logger.exception("[review_contracts] Scan failed")


async def _process_review(report: ContractRiskReport):
    """处理单个审查记录"""
    report_id = report.id
    contract_id = report.contract_id
    logger.debug(f"[_process_review] report_id={report_id}, contract_id={contract_id}")

    # 1. 标记为 analyzing
    report.status = "analyzing"
    await report.save(update_fields=["status"])

    try:
        # 2. 获取合同信息
        contract = await Contract.filter(id=contract_id, is_deleted=False).first()
        if not contract:
            await _mark_failed(report, "合同不存在或已删除")
            return

        # 3. 获取条款目录树
        clause_tree = await contract_service.get_clause_tree(contract_id)
        if not clause_tree:
            await _mark_failed(report, "合同无条款数据")
            return

        logger.debug(
            f"[_process_review] contract_id={contract_id}, "
            f"clause_count={len(clause_tree)}"
        )

        # 4. 获取 LLM（LangChain ChatOpenAI，供 ReAct Agent 使用）
        chat_models = await ai_config_controller.get_active_chat_models()
        if not chat_models:
            await _mark_failed(report, "无可用 Chat 模型")
            return
        model_config = chat_models[0]

        from langchain_openai import ChatOpenAI
        extra = model_config.extra_config or {}
        llm = ChatOpenAI(
            model=model_config.model_name,
            api_key=model_config.api_key,
            base_url=model_config.api_base_url,
            temperature=extra.get("temperature", 0.7),
            max_tokens=extra.get("max_tokens") or model_config.max_tokens,
        )

        # 5. 并行审查每个条款
        results = await _review_clauses_parallel(
            contract_id=contract_id,
            clause_tree=clause_tree,
            llm=llm,
        )

        # 6. 汇总报告
        contract_name = contract.project_name or f"合同{contract_id}"
        report_md, risk_summary = _build_report(contract_name, results)

        logger.debug(
            f"[_process_review] Report built: contract_id={contract_id}, "
            f"risk_summary={risk_summary}"
        )

        # 7. 写入飞书云文档
        feishu_doc_url = await _create_feishu_doc(contract_name, report_md, report)

        # 8. 更新审查记录
        report.status = "completed"
        report.report_content = report_md
        report.feishu_doc_url = feishu_doc_url
        report.risk_summary = risk_summary
        report.analyzed_at = datetime.now()
        await report.save(update_fields=[
            "status", "report_content", "feishu_doc_url",
            "risk_summary", "analyzed_at",
        ])

        logger.debug(
            f"[_process_review] Completed: report_id={report_id}, "
            f"feishu_doc_url={feishu_doc_url}"
        )

        # 9. 通知用户
        await _notify_user(report, contract_name, feishu_doc_url, risk_summary)

    except Exception as e:
        logger.exception(f"[_process_review] report_id={report_id} failed")
        await _mark_failed(report, str(e))


async def _review_clauses_parallel(
    contract_id: int,
    clause_tree: list[dict],
    llm,
) -> list[dict]:
    """并行审查所有条款（Semaphore 控制并发）"""
    logger.debug(
        f"[_review_clauses_parallel] contract_id={contract_id}, "
        f"total_clauses={len(clause_tree)}"
    )

    async def _review_one(clause: dict) -> dict:
        async with _REVIEW_SEMAPHORE:
            clause_title = clause.get("clause_title", "")
            logger.debug(
                f"[_review_one] contract_id={contract_id}, "
                f"clause_title={clause_title}"
            )

            try:
                # 构建子条款文本
                children = clause.get("children", [])
                children_text = "\n".join([
                    f"- {c.get('clause_title', '')}: {c.get('original_text', '')[:300]}"
                    for c in children
                ]) if children else "无"

                result = await agent_executor.execute(
                    "contract_clause_review",
                    {
                        "contract_id": contract_id,
                        "clause_title": clause_title,
                        "clause_level": clause.get("clause_level", 1),
                        "original_text": clause.get("original_text", ""),
                        "children_text": children_text,
                    },
                    llm=llm,
                )

                logger.debug(
                    f"[_review_one] Done: contract_id={contract_id}, "
                    f"clause_title={clause_title}, "
                    f"success={result.get('success')}"
                )

                return {
                    "clause_title": clause_title,
                    "success": result.get("success", False),
                    "review_result": result.get("review_result", ""),
                    "error": result.get("error"),
                }

            except Exception as e:
                logger.error(
                    f"[_review_one] Failed: contract_id={contract_id}, "
                    f"clause_title={clause_title}, error={e}",
                    exc_info=True,
                )
                return {
                    "clause_title": clause_title,
                    "success": False,
                    "review_result": f"### {clause_title}\n\n**审查失败：** {str(e)}",
                    "error": str(e),
                }

    # 并行执行
    tasks = [_review_one(c) for c in clause_tree]
    results = await asyncio.gather(*tasks)

    logger.debug(
        f"[_review_clauses_parallel] All done: contract_id={contract_id}, "
        f"results={len(results)}"
    )
    return list(results)


def _build_report(contract_name: str, results: list[dict]) -> tuple[str, dict]:
    """汇总审查结果生成 Markdown 报告"""
    # 统计风险
    high = medium = low = 0
    for r in results:
        content = r.get("review_result", "")
        if "高风险" in content:
            high += 1
        elif "中风险" in content:
            medium += 1
        elif "低风险" in content:
            low += 1

    risk_summary = {"high": high, "medium": medium, "low": low}

    # 构建报告
    parts = [
        f"# 合同审查报告：{contract_name}",
        "",
        "## 风险概览",
        "",
        "| 风险等级 | 数量 |",
        "|---------|------|",
        f"| 🔴 高风险 | {high} |",
        f"| 🟡 中风险 | {medium} |",
        f"| 🟢 低风险 | {low} |",
        "",
        "---",
        "",
        "## 逐条审查",
        "",
    ]

    for r in results:
        if r.get("success"):
            parts.append(r.get("review_result", ""))
        else:
            parts.append(
                f"### {r.get('clause_title', '未知条款')}\n\n"
                f"**审查失败：** {r.get('error', '未知错误')}"
            )
        parts.append("")
        parts.append("---")
        parts.append("")

    return "\n".join(parts), risk_summary


async def _create_feishu_doc(
    contract_name: str,
    report_md: str,
    report: ContractRiskReport,
) -> str | None:
    """创建飞书云文档"""
    try:
        folder_token = await contract_service.get_feishu_review_folder()
        if not folder_token:
            logger.debug("[_create_feishu_doc] No folder config, skipping")
            return None

        # 获取 bot 配置
        bot_config = await feishu_bot_controller.model.filter(
            is_active=True,
        ).first()
        if not bot_config:
            logger.debug("[_create_feishu_doc] No active bot config")
            return None

        access_token = await feishu_service.get_tenant_access_token(
            bot_config.app_id, bot_config.app_secret,
        )

        title = f"审查报告-{contract_name}-{datetime.now().strftime('%Y%m%d%H%M')}"

        doc_url = await feishu_service.import_markdown_to_folder(
            folder_token=folder_token,
            title=title,
            markdown_content=report_md,
            access_token=access_token,
        )

        logger.debug(f"[_create_feishu_doc] Created: {doc_url}")
        return doc_url

    except Exception as e:
        logger.error(f"[_create_feishu_doc] Failed: {e}", exc_info=True)
        return None


async def _notify_user(
    report: ContractRiskReport,
    contract_name: str,
    feishu_doc_url: str | None,
    risk_summary: dict,
):
    """通过飞书通知用户审查完成"""
    try:
        chat_id = report.chat_id
        if not chat_id:
            logger.debug("[_notify_user] No chat_id, skipping notification")
            return

        bot_id = report.bot_id
        bot_config = await feishu_bot_controller.model.filter(
            is_active=True,
        ).first()
        if not bot_config:
            logger.debug("[_notify_user] No active bot config")
            return

        high = risk_summary.get("high", 0)
        medium = risk_summary.get("medium", 0)
        low = risk_summary.get("low", 0)

        doc_link = f"\n\n📄 [查看完整报告]({feishu_doc_url})" if feishu_doc_url else ""

        message = (
            f"📋 **合同审查完成：{contract_name}**\n\n"
            f"🔴 高风险：{high} 项\n"
            f"🟡 中风险：{medium} 项\n"
            f"🟢 低风险：{low} 项"
            f"{doc_link}"
        )

        await feishu_service.send_message(
            app_id=bot_config.app_id,
            app_secret=bot_config.app_secret,
            chat_id=chat_id,
            content=json.dumps({"text": message}),
            msg_type="text",
        )

        logger.debug(
            f"[_notify_user] Notification sent: report_id={report.id}, "
            f"chat_id={chat_id}"
        )

    except Exception as e:
        logger.error(f"[_notify_user] Failed: {e}", exc_info=True)


async def _mark_failed(report: ContractRiskReport, error_message: str):
    """标记审查失败"""
    report.status = "failed"
    report.error_message = error_message
    await report.save(update_fields=["status", "error_message"])
    logger.debug(
        f"[_mark_failed] report_id={report.id}, error={error_message}"
    )
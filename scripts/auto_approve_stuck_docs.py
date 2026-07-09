"""一次性脚本：批量自动审批因重启补偿遗漏的飞书自动入库文档。

问题背景：重启后补偿任务 compensate_pending_extract 提取了文档但未读取
文件夹监听的 auto_approve 配置，导致本应自动审批的文档卡在 PENDING_REVIEW。

用法：在项目根目录执行
    python scripts/auto_approve_stuck_docs.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from tortoise import Tortoise
from app.settings.config import settings
from app.models.enums import DocumentStatus
from app.models.rag import Document, FeishuFolderWatch
from app.services.document_pipeline import document_pipeline


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)

    # 找到所有 PENDING_REVIEW 且有 auto_ingested 标记的文档
    docs = await Document.filter(
        status=DocumentStatus.PENDING_REVIEW,
        is_deleted=False,
    ).all()

    if not docs:
        print("[INFO] 没有 PENDING_REVIEW 状态的文档，无需处理。")
        await Tortoise.close_connections()
        return

    # 筛选出飞书自动入库的文档
    auto_ingested_docs = []
    for doc in docs:
        source_meta = doc.source_meta or {}
        if source_meta.get("auto_ingested") and source_meta.get("folder_watch_id"):
            auto_ingested_docs.append(doc)

    if not auto_ingested_docs:
        print(f"[INFO] {len(docs)} 个 PENDING_REVIEW 文档，但都不是飞书自动入库的，跳过。")
        await Tortoise.close_connections()
        return

    print(f"[INFO] 找到 {len(auto_ingested_docs)} 个飞书自动入库的 PENDING_REVIEW 文档")

    # 批量查询对应的 watch
    watch_ids = list({d.source_meta.get("folder_watch_id") for d in auto_ingested_docs})
    watches = await FeishuFolderWatch.filter(id__in=watch_ids).all()
    watch_map = {w.id: w for w in watches}

    auto_approved = 0
    skipped = 0
    failed = 0

    for doc in auto_ingested_docs:
        watch_id = doc.source_meta.get("folder_watch_id")
        watch = watch_map.get(watch_id)
        if not watch:
            print(f"  [SKIP] doc_id={doc.id}: 找不到对应的 watch (id={watch_id})")
            skipped += 1
            continue

        if not watch.auto_approve:
            print(f"  [SKIP] doc_id={doc.id}: watch '{watch.name}' 未开启自动审批")
            skipped += 1
            continue

        try:
            print(f"  [AUTO_APPROVE] doc_id={doc.id}, title={doc.title}, watch={watch.name}")
            await document_pipeline.approve(doc.id)
            auto_approved += 1
        except Exception as e:
            print(f"  [FAIL] doc_id={doc.id}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"完成！自动审批: {auto_approved}, 跳过: {skipped}, 失败: {failed}")
    print(f"{'='*50}")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter

from app.models.enums import DocumentStatus
from app.models.rag import Agent, ChatMessage, Conversation, Document, KnowledgeBase
from app.schemas.base import Success

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats", summary="仪表盘统计")
async def get_dashboard_stats():
    total_docs = await Document.filter(is_deleted=False).count()
    pending_review = await Document.filter(is_deleted=False, status=DocumentStatus.PENDING_REVIEW).count()
    completed_docs = await Document.filter(is_deleted=False, status=DocumentStatus.COMPLETED).count()
    failed_docs = await Document.filter(is_deleted=False, status=DocumentStatus.FAILED).count()
    rejected_docs = await Document.filter(is_deleted=False, status=DocumentStatus.REJECTED).count()
    processing_docs = await Document.filter(
        is_deleted=False,
        status__in=[
            DocumentStatus.PENDING_EXTRACT,
            DocumentStatus.EXTRACTED,
            DocumentStatus.SLICING,
            DocumentStatus.VECTORIZING,
        ],
    ).count()
    total_kbs = await KnowledgeBase.filter(is_deleted=False).count()
    total_agents = await Agent.all().count()
    total_conversations = await Conversation.all().count()
    total_messages = await ChatMessage.all().count()

    return Success(
        data={
            "total_documents": total_docs,
            "pending_review": pending_review,
            "completed_documents": completed_docs,
            "failed_documents": failed_docs,
            "rejected_documents": rejected_docs,
            "processing_documents": processing_docs,
            "total_knowledge_bases": total_kbs,
            "total_agents": total_agents,
            "total_conversations": total_conversations,
            "total_messages": total_messages,
        }
    )


@router.get("/trends", summary="7日趋势")
async def get_dashboard_trends():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = []
    for i in range(6, -1, -1):
        day_start = today - timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        doc_count = await Document.filter(
            is_deleted=False, created_at__gte=day_start, created_at__lt=day_end
        ).count()
        msg_count = await ChatMessage.filter(
            created_at__gte=day_start, created_at__lt=day_end
        ).count()
        days.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "new_documents": doc_count,
            "new_messages": msg_count,
        })

    return Success(data=days)

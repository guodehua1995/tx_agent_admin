from tortoise import fields

from .base import BaseModel, TimestampMixin
from .enums import (
    ChunkMode,
    DocumentSourceType,
    DocumentStatus,
    DocumentTypeCode,
    FeishuPublishStatus,
    LLMProviderType,
    MessageType,
    RetrievalMode,
    ReviewAction,
)


class LLMProviderConfig(BaseModel, TimestampMixin):
    name = fields.CharField(max_length=100, unique=True, description="显示名")
    provider_type = fields.CharEnumField(LLMProviderType, description="提供商类型")
    api_base_url = fields.CharField(max_length=500, description="API地址")
    api_key = fields.CharField(max_length=500, description="API密钥")
    model_name = fields.CharField(max_length=200, description="模型标识")
    is_embedding = fields.BooleanField(default=False, description="是否为Embedding模型")
    embedding_dimension = fields.IntField(null=True, description="向量维度")
    max_tokens = fields.IntField(default=4096, description="最大token数")
    is_active = fields.BooleanField(default=True, description="是否启用")
    extra_config = fields.JSONField(null=True, description="额外参数")

    class Meta:
        table = "llm_provider_config"


class KnowledgeBase(BaseModel, TimestampMixin):
    name = fields.CharField(max_length=100, unique=True, description="知识库名称")
    description = fields.TextField(null=True, description="描述")
    embedding_model_id = fields.IntField(description="Embedding模型ID -> llm_provider_config.id")
    is_active = fields.BooleanField(default=True, description="是否启用")
    # RAG 配置
    retrieval_mode = fields.CharEnumField(RetrievalMode, default=RetrievalMode.VECTOR, description="召回模式")
    chunk_mode = fields.CharEnumField(ChunkMode, default=ChunkMode.SENTENCE, description="切片模式")
    chunk_size = fields.IntField(default=512, description="分块大小(token)")
    chunk_overlap = fields.IntField(default=50, description="分块重叠(token)")
    similarity_top_k = fields.IntField(default=5, description="检索返回数量")
    similarity_threshold = fields.FloatField(default=0.5, description="相似度阈值")
    context_chunks_window = fields.IntField(default=0, description="上下文扩展窗口(前后各N个chunk)")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "knowledge_base"


class Document(BaseModel, TimestampMixin):
    title = fields.CharField(max_length=500, description="文档标题")
    source_type = fields.CharEnumField(DocumentSourceType, description="来源类型")
    source_meta = fields.JSONField(null=True, description="来源元数据")
    content = fields.TextField(null=True, description="清洗后的文本内容")
    summary = fields.TextField(null=True, description="文档概述摘要")
    doc_type_code = fields.CharEnumField(DocumentTypeCode, default=DocumentTypeCode.FEISHU_DOC, description="文档类型编码")
    knowledge_base_id = fields.IntField(description="知识库ID -> knowledge_base.id")
    status = fields.CharEnumField(DocumentStatus, default=DocumentStatus.PENDING_EXTRACT, description="处理状态")
    uploader_id = fields.IntField(description="上传者ID -> user.id")
    error_message = fields.TextField(null=True, description="错误信息")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "document"


class SlicingResult(BaseModel, TimestampMixin):
    document_id = fields.IntField(unique=True, description="文档ID -> document.id")
    sliced_content = fields.TextField(description="切片后的内容")
    slicing_model_id = fields.IntField(description="切片模型ID -> llm_provider_config.id")
    prompt_used = fields.TextField(null=True, description="实际使用的提示词")
    token_usage = fields.JSONField(null=True, description="token消耗")
    processing_time_ms = fields.IntField(null=True, description="处理耗时(ms)")
    feishu_publish_status = fields.CharEnumField(FeishuPublishStatus, null=True, description="飞书发布状态")
    feishu_publish_url = fields.CharField(max_length=1000, null=True, description="飞书文档URL")

    class Meta:
        table = "slicing_result"


class ReviewRecord(BaseModel, TimestampMixin):
    document_id = fields.IntField(description="文档ID -> document.id", index=True)
    reviewer_id = fields.IntField(description="审核人ID -> user.id", index=True)
    action = fields.CharEnumField(ReviewAction, description="审核动作")
    comment = fields.TextField(null=True, description="审核意见")

    class Meta:
        table = "review_record"


class Agent(BaseModel, TimestampMixin):
    name = fields.CharField(max_length=100, unique=True, description="Agent名称")
    description = fields.TextField(null=True, description="描述")
    chat_model_id = fields.IntField(description="对话模型ID -> llm_provider_config.id")
    system_prompt = fields.TextField(null=True, description="系统提示词")
    max_history_turns = fields.IntField(default=10, description="历史对话轮数")
    is_active = fields.BooleanField(default=True, description="是否启用")
    knowledge_bases = fields.ManyToManyField(
        "models.KnowledgeBase", related_name="agents", through="agent_knowledge_base"
    )
    doc_templates = fields.ManyToManyField(
        "models.DocTemplate", related_name="agents", through="agent_doc_template"
    )

    class Meta:
        table = "agent"


class DocTemplate(BaseModel, TimestampMixin):
    name = fields.CharField(max_length=100, description="模板名称")
    markdown_content = fields.TextField(description="Markdown模板内容")
    folder_token = fields.CharField(max_length=200, description="飞书文件夹Token")
    description = fields.TextField(description="模板描述(告知AI使用场景)")
    naming_format = fields.CharField(max_length=200, null=True, description="命名格式")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "doc_template"


class FeishuBotConfig(BaseModel, TimestampMixin):
    name = fields.CharField(max_length=100, unique=True, description="机器人名称")
    app_id = fields.CharField(max_length=200, unique=True, description="飞书应用ID")
    app_secret = fields.CharField(max_length=500, description="飞书应用密钥")
    verification_token = fields.CharField(max_length=500, null=True, description="事件验证token")
    encrypt_key = fields.CharField(max_length=500, null=True, description="事件加密key")
    agent_id = fields.IntField(description="绑定Agent ID -> agent.id", null=True, index=True)
    is_active = fields.BooleanField(default=True, description="是否启用")

    class Meta:
        table = "feishu_bot_config"


class Conversation(BaseModel, TimestampMixin):
    agent_id = fields.IntField(description="Agent ID -> agent.id", index=True)
    user_id = fields.IntField(description="用户ID -> user.id", index=True)
    message_count = fields.IntField(default=0, description="消息数")
    last_active_at = fields.DatetimeField(null=True, description="最后活跃时间")

    class Meta:
        table = "conversation"
        unique_together = (("agent_id", "user_id"),)


class ChatMessage(BaseModel, TimestampMixin):
    conversation_id = fields.IntField(description="会话ID -> conversation.id", index=True)
    type = fields.CharEnumField(MessageType, description="消息类型")
    content = fields.TextField(description="消息内容")
    retrieved_chunks = fields.JSONField(null=True, description="检索到的分块")
    token_count = fields.IntField(default=0, description="token消耗")
    response_time_ms = fields.IntField(null=True, description="响应耗时(ms)")
    feishu_message_id = fields.CharField(max_length=200, null=True, description="飞书消息ID", index=True)

    class Meta:
        table = "chat_message"


class DocumentPage(BaseModel, TimestampMixin):
    document_id = fields.IntField(description="文档ID -> document.id", index=True)
    page_number = fields.IntField(description="页码(从1开始)")
    total_pages = fields.IntField(description="总页数")
    content = fields.TextField(null=True, description="该页Markdown内容")
    screenshot_url = fields.CharField(max_length=1000, null=True, description="截图访问URL")

    class Meta:
        table = "document_page"
        unique_together = (("document_id", "page_number"),)


class FeishuFolderWatch(BaseModel, TimestampMixin):
    """飞书云盘文件夹监听配置。定时扫描文件变化，新增文件自动入库。”"""

    name = fields.CharField(max_length=100, description="文件夹显示名")
    folder_token = fields.CharField(
        max_length=200, unique=True, description="飞书 folder_token"
    )
    folder_url = fields.CharField(max_length=500, null=True, description="原始URL")
    knowledge_base_id = fields.IntField(
        description="入库目标知识库ID -> knowledge_base.id", index=True
    )
    doc_type_code = fields.CharEnumField(
        DocumentTypeCode, description="入库走哪个文档类型处理器"
    )
    scan_interval_seconds = fields.IntField(default=600, description="扫描周期(秒)")
    last_scanned_at = fields.DatetimeField(null=True, description="上次扫描时间")
    last_scan_status = fields.CharField(
        max_length=20, null=True, description="上次扫描状态: success/failed/running"
    )
    last_error = fields.TextField(null=True, description="上次失败原因")
    is_active = fields.BooleanField(default=True, description="是否启用")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "feishu_folder_watch"


class FeishuFolderFile(BaseModel, TimestampMixin):
    """飞书文件夹已扫描文件幂等表。幂等锁：(folder_watch_id, file_token) 唯一。"""

    folder_watch_id = fields.IntField(
        description="watch ID -> feishu_folder_watch.id", index=True
    )
    file_token = fields.CharField(max_length=200, description="飞书文件 token")
    file_name = fields.CharField(max_length=500, description="文件名")
    file_type = fields.CharField(max_length=50, null=True, description="飞书文件类型: file/docx/...")
    feishu_modified_time = fields.BigIntField(
        null=True, description="飞书侧修改时间戳")
    document_id = fields.IntField(null=True, description="入库后的 Document.id")
    ingest_status = fields.CharField(
        max_length=20, default="pending",
        description="入库状态: pending/ingested/skipped/failed",
    )
    ingest_error = fields.TextField(null=True, description="入库失败原因")

    class Meta:
        table = "feishu_folder_file"
        unique_together = (("folder_watch_id", "file_token"),)

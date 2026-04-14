from tortoise import fields

from .base import BaseModel, TimestampMixin
from .enums import (
    ChunkMode,
    DocumentSourceType,
    DocumentStatus,
    FeishuPublishStatus,
    LLMProviderType,
    MessageRole,
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


class DocumentType(BaseModel, TimestampMixin):
    name = fields.CharField(max_length=100, unique=True, description="类型名")
    code = fields.CharField(max_length=50, unique=True, description="机器码")
    needs_structuring = fields.BooleanField(default=False, description="是否需要AI结构化")
    is_active = fields.BooleanField(default=True, description="是否启用")
    description = fields.TextField(null=True, description="描述")

    class Meta:
        table = "document_type"


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
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "knowledge_base"


class Document(BaseModel, TimestampMixin):
    title = fields.CharField(max_length=500, description="文档标题")
    source_type = fields.CharEnumField(DocumentSourceType, description="来源类型")
    source_meta = fields.JSONField(null=True, description="来源元数据")
    content = fields.TextField(null=True, description="清洗后的文本内容")
    doc_type_id = fields.IntField(description="文档类型ID -> document_type.id")
    knowledge_base_id = fields.IntField(description="知识库ID -> knowledge_base.id")
    status = fields.CharEnumField(DocumentStatus, default=DocumentStatus.PENDING_FETCH, description="处理状态")
    uploader_id = fields.IntField(description="上传者ID -> user.id")
    error_message = fields.TextField(null=True, description="错误信息")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "document"


class StructuredResult(BaseModel, TimestampMixin):
    document_id = fields.IntField(unique=True, description="文档ID -> document.id")
    structured_content = fields.TextField(description="结构化后的内容")
    structuring_model_id = fields.IntField(description="结构化模型ID -> llm_provider_config.id")
    prompt_used = fields.TextField(null=True, description="实际使用的提示词")
    token_usage = fields.JSONField(null=True, description="token消耗")
    processing_time_ms = fields.IntField(null=True, description="处理耗时(ms)")
    feishu_publish_status = fields.CharEnumField(FeishuPublishStatus, null=True, description="飞书发布状态")
    feishu_publish_url = fields.CharField(max_length=1000, null=True, description="飞书文档URL")

    class Meta:
        table = "structured_result"


class ReviewRecord(BaseModel, TimestampMixin):
    document_id = fields.IntField(description="文档ID -> document.id", index=True)
    reviewer_id = fields.IntField(description="审核人ID -> user.id", index=True)
    action = fields.CharEnumField(ReviewAction, description="审核动作")
    comment = fields.TextField(null=True, description="审核意见")
    edited_content = fields.TextField(null=True, description="编辑后的内容")

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

    class Meta:
        table = "agent"


class FeishuBotConfig(BaseModel, TimestampMixin):
    name = fields.CharField(max_length=100, unique=True, description="机器人名称")
    app_id = fields.CharField(max_length=200, unique=True, description="飞书应用ID")
    app_secret = fields.CharField(max_length=500, description="飞书应用密钥")
    verification_token = fields.CharField(max_length=500, null=True, description="事件验证token")
    encrypt_key = fields.CharField(max_length=500, null=True, description="事件加密key")
    agent_id = fields.IntField(description="绑定Agent ID -> agent.id", index=True)
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
    role = fields.CharEnumField(MessageRole, description="消息角色")
    content = fields.TextField(description="消息内容")
    retrieved_chunks = fields.JSONField(null=True, description="检索到的分块")
    token_count = fields.IntField(default=0, description="token消耗")
    response_time_ms = fields.IntField(null=True, description="响应耗时(ms)")
    feishu_message_id = fields.CharField(max_length=200, null=True, description="飞书消息ID", index=True)

    class Meta:
        table = "chat_message"

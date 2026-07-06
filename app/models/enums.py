from enum import Enum, StrEnum


class EnumBase(Enum):
    @classmethod
    def get_member_values(cls):
        return [item.value for item in cls._member_map_.values()]

    @classmethod
    def get_member_names(cls):
        return [name for name in cls._member_names_]


class MethodType(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


# ========== RAG 模块枚举 ==========


class DocumentSourceType(StrEnum):
    FEISHU_DOC = "feishu_doc"
    FILE_UPLOAD = "file_upload"
    WEB_URL = "web_url"


class DocumentTypeCode(StrEnum):
    """文档类型编码 — 纯后端枚举，根据 code 路由到不同处理函数"""
    FEISHU_DOC = "feishu_doc"
    PPT = "ppt"
    CONTRACT = "contract"

    @classmethod
    def get_display_map(cls) -> dict[str, str]:
        """返回 code → 展示名称 映射"""
        return {
            cls.FEISHU_DOC: "飞书文档",
            cls.PPT: "PPT文档",
            cls.CONTRACT: "合同",
        }

    @classmethod
    def get_paged_types(cls) -> set[str]:
        """返回需要分页处理的文档类型集合"""
        return {cls.PPT}

    @classmethod
    def is_paged_type(cls, code: str) -> bool:
        """判断指定文档类型编码是否为分页类型"""
        return code in cls.get_paged_types()


class DocumentStatus(StrEnum):
    PENDING_EXTRACT = "pending_extract"   # 待提取内容
    EXTRACTED = "extracted"               # 已提取（瞬态，以前叫 fetched）
    PENDING_REVIEW = "pending_review"     # 待审核
    APPROVED = "approved"                 # 审核通过
    SLICING = "slicing"                   # 切片中（以前叫 structuring）
    VECTORIZING = "vectorizing"           # 向量化中
    COMPLETED = "completed"               # 完成
    REJECTED = "rejected"                 # 已驳回
    FAILED = "failed"                     # 处理失败


class FeishuPublishStatus(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class LLMProviderType(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    VOLCENGINE = "volcengine"
    AZURE_OPENAI = "azure_openai"


class MessageType(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    TOOL_CALL_RESULT = "tool_call_result"


class RetrievalMode(StrEnum):
    VECTOR = "vector"
    HYBRID = "hybrid"


class ChunkMode(StrEnum):
    SENTENCE = "sentence"
    MARKDOWN = "markdown"
    HIERARCHICAL = "hierarchical"


# ========== 报价模块枚举 ==========


class QuotationRuleStatus(StrEnum):
    """报价规则状态"""
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    EXPIRED = "expired"  # 已失效（被新版本替代或手动取消）
    ARCHIVED = "archived"


class RuleSourceType(StrEnum):
    """规则来源"""
    MANUAL = "manual"
    EXCEL_IMPORT = "excel_import"


# ========== 合同模块枚举 ==========


class ContractTypeCode(StrEnum):
    """合同类型编码 — 种子数据，与 contract_type 表同步"""
    PURCHASE = "purchase"
    SERVICE = "service"
    TECH_COOP = "tech_coop"
    FRAMEWORK = "framework"
    LABOR = "labor"
    LEASE = "lease"
    OTHER = "other"

    @classmethod
    def get_display_map(cls) -> dict[str, str]:
        return {
            cls.PURCHASE: "采购",
            cls.SERVICE: "服务",
            cls.TECH_COOP: "技术合作",
            cls.FRAMEWORK: "框架协议",
            cls.LABOR: "劳动",
            cls.LEASE: "租赁",
            cls.OTHER: "其他",
        }


class ClientType(StrEnum):
    """主体类型"""
    ENTERPRISE = "企业"
    GOVERNMENT = "政府"
    INDIVIDUAL = "个人"


class SummaryStatus(StrEnum):
    """合同条款摘要状态"""
    PENDING_SUMMARY = "pending_summary"    # 待生成摘要
    SUMMARY_COMPLETE = "summary_complete"  # 摘要已完成
    PENDING_DELETE = "pending_delete"      # 待删除（已不可见，等后台清理）

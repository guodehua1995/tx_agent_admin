from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., description="知识库名称")
    description: Optional[str] = Field(None, description="描述")
    embedding_model_id: int = Field(..., description="Embedding模型ID")
    is_active: bool = Field(True, description="是否启用")
    retrieval_mode: str = Field("vector", description="召回模式")
    chunk_mode: str = Field("sentence", description="切片模式")
    chunk_size: int = Field(512, description="分块大小")
    chunk_overlap: int = Field(50, description="分块重叠")
    similarity_top_k: int = Field(5, description="检索返回数量")
    similarity_threshold: float = Field(0.5, description="相似度阈值")
    context_chunks_window: int = Field(0, description="上下文扩展窗口(前后各N个chunk)")


class KnowledgeBaseUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    embedding_model_id: Optional[int] = None
    is_active: Optional[bool] = None
    retrieval_mode: Optional[str] = None
    chunk_mode: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    similarity_top_k: Optional[int] = None
    similarity_threshold: Optional[float] = None
    context_chunks_window: Optional[int] = None

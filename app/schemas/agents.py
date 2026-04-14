from typing import List, Optional

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(..., description="Agent名称")
    description: Optional[str] = Field(None, description="描述")
    chat_model_id: int = Field(..., description="对话模型ID")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    max_history_turns: int = Field(10, description="历史对话轮数")
    is_active: bool = Field(True, description="是否启用")
    knowledge_base_ids: Optional[List[int]] = Field([], description="关联知识库ID列表")


class AgentUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    chat_model_id: Optional[int] = None
    system_prompt: Optional[str] = None
    max_history_turns: Optional[int] = None
    is_active: Optional[bool] = None
    knowledge_base_ids: Optional[List[int]] = None


class UpdateKnowledgeBases(BaseModel):
    agent_id: int = Field(..., description="Agent ID")
    knowledge_base_ids: List[int] = Field(..., description="知识库ID列表")

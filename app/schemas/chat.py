
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., description="用户问题")
    agent_id: int = Field(..., description="Agent ID")

from pydantic import BaseModel, field_validator


class ChunkCreate(BaseModel):
    doc_id: int
    text: str

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("切片文本不能为空")
        return v


class ChunkUpdate(BaseModel):
    node_id: str
    doc_id: int
    text: str

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("切片文本不能为空")
        return v

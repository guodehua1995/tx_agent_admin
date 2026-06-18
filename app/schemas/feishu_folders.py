"""飞书文件夹监听相关 Schema"""

from typing import Optional

from pydantic import BaseModel, Field


class FeishuFolderCreate(BaseModel):
    name: str = Field(..., description="文件夹显示名")
    folder_url: str = Field(..., description="飞书文件夹 URL 或 folder_token")
    knowledge_base_id: int = Field(..., description="入库目标知识库ID")
    doc_type_code: str = Field(..., description="文档类型编码: feishu_doc/ppt/contract")
    scan_interval_seconds: Optional[int] = Field(
        None, description="扫描周期(秒)，留空使用默认值"
    )
    auto_approve: Optional[bool] = Field(False, description="自动审批(跳过人工审核)")
    recursive_scan: Optional[bool] = Field(False, description="递归扫描子文件夹")
    is_active: Optional[bool] = Field(True, description="是否启用")


class FeishuFolderUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    doc_type_code: Optional[str] = None
    scan_interval_seconds: Optional[int] = None
    auto_approve: Optional[bool] = None
    recursive_scan: Optional[bool] = None
    is_active: Optional[bool] = None


class FeishuFolderToggle(BaseModel):
    id: int
    is_active: bool

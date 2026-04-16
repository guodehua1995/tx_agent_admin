import re
import time
import requests
import mammoth
from io import BytesIO
from typing import List, Optional
from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser

class FeishuDocxToMarkdown:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self.tenant_access_token = ""
        self.token_expire = 0

    def _get_tenant_token(self) -> str:
        """获取飞书鉴权token，自动刷新"""
        if self.tenant_access_token and time.time() < self.token_expire:
            return self.tenant_access_token
        
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": self.app_id,
            "app_secret": self.app_secret
        })
        data = resp.json()
        resp.raise_for_status()
        if data.get("code") != 0:
            raise Exception(f"获取飞书token失败: {data.get('msg')}")
        self.tenant_access_token = data["tenant_access_token"]
        self.token_expire = time.time() + data["expire"] - 60  # 提前60秒刷新
        return self.tenant_access_token

    def _extract_doc_id(self, doc_url: str) -> str:
        """从飞书文档URL提取doc_id，支持新版docx/旧版doc格式"""
        # 匹配新版docx: https://xxx.feishu.cn/docx/abc123
        if "/docx/" in doc_url:
            return re.search(r"/docx/([a-zA-Z0-9]+)", doc_url).group(1)
        # 匹配旧版doc: https://xxx.feishu.cn/doc/abc123
        elif "/doc/" in doc_url:
            return re.search(r"/doc/([a-zA-Z0-9]+)", doc_url).group(1)
        else:
            raise ValueError(f"无效的飞书文档URL: {doc_url}")

    def _export_docx_from_feishu(self, doc_id: str) -> BytesIO:
        """调用飞书API导出docx文件，返回内存中的BytesIO对象"""
        token = self._get_tenant_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # 1. 创建导出任务（飞书导出是异步的，对应你截图的API参数）
        # 飞书机器人需要开通读云文档权限
        export_url = f"{self.base_url}/drive/v1/export_tasks"
        export_payload = {
            "type": "docx",  # 新版飞书文档，严格对应你截图的可选值
            "token": doc_id,
            "file_extension": "pdf"  # 导出为docx格式
        }
        resp = requests.post(export_url, json=export_payload, headers=headers)
        resp.raise_for_status()
        task_data = resp.json()["data"]
        ticket = task_data["ticket"]
    
        # 2. 轮询等待导出完成
        poll_url = f"{self.base_url}/drive/v1/export_tasks/{ticket}"
        for _ in range(30):  # 最多等30秒
            poll_resp = requests.get(poll_url, params={"token": doc_id}, headers=headers)
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()["data"]["result"]
            if poll_data["job_status"] == 0:
                # 3. 下载docx文件到内存，不写本地磁盘,飞书机器人需要开通下载云文档权限
                file_token = poll_data["file_token"]
                print(f"下载docx文件，文件名：{file_token}")
                docx_resp = requests.get(f"{self.base_url}/drive/v1/export_tasks/file/{file_token}/download", headers=headers)
                docx_resp.raise_for_status()
                return BytesIO(docx_resp.content)
            time.sleep(1)
        raise TimeoutError("飞书文档导出超时")

    def _docx_to_markdown(self, docx_bytes: BytesIO) -> str:
        """用mammoth将docx二进制转为标准Markdown，内存处理，无需写文件"""
        # mammoth直接从BytesIO读取，零成本转换
        # 保存到本地，方便查看
        with open("output.docx", "wb") as f:
            f.write(docx_bytes.getvalue())
        result = mammoth.convert_to_markdown(docx_bytes)
        md_content = result.value

        # 可选：MD清洗优化，专门适配RAG检索
        md_content = self._clean_markdown(md_content)
        return md_content

    def _clean_markdown(self, md: str) -> str:
        """清洗MD内容，去除飞书冗余格式，优化RAG效果"""
        # 1. 去除多余空行
        lines = [line.rstrip() for line in md.splitlines()]
        lines = [line for i, line in enumerate(lines) if line.strip() or (i > 0 and lines[i-1].strip())]
        # 2. 修复表格格式（mammoth转的表格可能有多余空行）
        md_clean = "\n".join(lines)
        # 3. 去除飞书导出的冗余页眉/页脚/水印
        md_clean = re.sub(r"^.*飞书文档.*$", "", md_clean, flags=re.MULTILINE)
        return md_clean.strip()

    def get_markdown_from_url(self, doc_url: str) -> str:
        """对外核心接口：输入飞书文档URL，直接输出标准Markdown"""
        doc_id = self._extract_doc_id(doc_url)
        docx_bytes = self._export_docx_from_feishu(doc_id)
        return self._docx_to_markdown(docx_bytes)

    def get_llama_index_document(self, doc_url: str) -> Document:
        """直接输出LlamaIndex Document对象，一键用于向量化"""
        md_content = self.get_markdown_from_url(doc_url)
        return Document(
            text=md_content,
            metadata={
                "source": "feishu",
                "doc_url": doc_url,
                "format": "markdown"
            }
        )

# ======================
# 飞书MD文档专用切片器（最优配置）
# ======================
def get_feishu_markdown_node_parser() -> MarkdownNodeParser:
    """获取适配飞书文档的Markdown切片器，完美保留语义结构"""
    return MarkdownNodeParser(
        levels=["h1", "h2", "h3"],  # 按1-3级标题切分，完全适配飞书文档层级
        max_chunk_size=1024,  # 块大小，根据你的模型上下文窗口调整
        chunk_overlap=50,     # 块重叠，保证上下文连贯
        include_metadata=True
    )

if __name__ == "__main__":
    fs_doc = FeishuDocxToMarkdown(app_id="cli_a938a06b8d39dbd1", app_secret="IwWkBO1HTjkCnBqppAZh0bO0B8zobnjy")
    doc = fs_doc.get_llama_index_document(doc_url="https://my.feishu.cn/docx/D66xdQ7iDoe6rwxQv3YcDCGwnoe")
    print(doc.text)

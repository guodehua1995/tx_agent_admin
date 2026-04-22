import logging
import re
from typing import Optional

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)


class FeishuAPIError(Exception):
    """飞书 API 返回非零业务错误码时抛出"""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


class FeishuService:
    """飞书 API 封装"""

    def __init__(self):
        self._base_url = settings.FEISHU_BASE_URL
        self._verify_ssl = settings.FEISHU_VERIFY_SSL

    async def _request(
        self,
        method: str,
        path: str,
        auth_token: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """统一 HTTP 请求封装：拼接 URL、设置 Auth、解析飞书错误码"""
        url = f"{self._base_url}{path}"
        headers = kwargs.pop("headers", {})
        if auth_token:
            headers.setdefault("Authorization", f"Bearer {auth_token}")

        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            data = resp.json()

        code = data.get("code")
        if code is not None and code != 0:
            raise FeishuAPIError(data.get("msg", "飞书API未知错误"), code=code)
        return data

    async def _get(self, path: str, auth_token: Optional[str] = None, **kwargs) -> dict:
        return await self._request("GET", path, auth_token=auth_token, **kwargs)

    async def _post(self, path: str, auth_token: Optional[str] = None, **kwargs) -> dict:
        return await self._request("POST", path, auth_token=auth_token, **kwargs)

    async def get_tenant_access_token(self, app_id: str, app_secret: str) -> str:
        """获取 tenant_access_token"""
        data = await self._post(
            "/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        return data["tenant_access_token"]

    async def fetch_document_content(self, doc_token: str, doc_type: str, access_token: str) -> str:
        """拉取飞书云文档内容"""
        data = await self._get(
            f"/docx/v1/documents/{doc_token}/raw_content",
            auth_token=access_token,
        )
        return data.get("data", {}).get("content", "")

    async def send_message(
        self, app_id: str, app_secret: str, chat_id: str, content: str, msg_type: str = "interactive"
    ) -> None:
        """发送飞书消息"""
        token = await self.get_tenant_access_token(app_id, app_secret)
        await self._post(
            "/im/v1/messages",
            auth_token=token,
            params={"receive_id_type": "chat_id"},
            json={"receive_id": chat_id, "msg_type": msg_type, "content": content},
        )

    async def build_answer_card(self, answer: str, sources: list) -> dict:
        """构建消息卡片"""
        source_elements = ""
        for i, src in enumerate(sources[:3], 1):
            title = src.get("metadata", {}).get("title", "未知来源")
            url = src.get("metadata", {}).get("url")
            source_elements += f"[{title}]({url})\n"
        
        elemsnts = [
                {"tag": "div", "text": {"tag": "lark_md", "content": answer}},
        ]
        if source_elements:
            elemsnts.extend([
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": "参考来源:\n" + source_elements}},
            ])

        return {
            "config": {"wide_screen_mode": True},
            "elements":elemsnts,
        }

    async def create_doc_in_folder(self, folder_token: str, title: str, content: str, access_token: str) -> str:
        """将结构化结果发布到飞书云文档指定文件夹"""
        data = await self._post(
            "/docx/v1/documents",
            auth_token=access_token,
            json={"folder_token": folder_token, "title": title},
        )
        doc_id = data["data"]["document"]["document_id"]

        await self._post(
            f"/docx/v1/documents/{doc_id}/blocks/batch_update",
            auth_token=access_token,
            json={
                "requests": [
                    {
                        "block_id": doc_id,
                        "update_text_elements": {
                            "elements": [{"text_run": {"content": content}}]
                        },
                    }
                ]
            },
        )
        return f"https://open.feishu.cn/docx/{doc_id}"

    def verify_webhook(self, body: dict, token: str, encrypt_key: str = None) -> bool:
        """验证 Webhook 事件"""
        if body.get("token") == token:
            return True
        header = body.get("header", {})
        if header.get("token") == token:
            return True
        return False

    def parse_feishu_url(self, url: str) -> tuple[str, str]:
        """解析飞书文档 URL，返回 (doc_token, doc_type)"""
        patterns = [
            (r"feishu\.cn/docx/([A-Za-z0-9]+)", "docx"),
            (r"feishu\.cn/wiki/([A-Za-z0-9]+)", "wiki"),
            (r"feishu\.cn/sheets/([A-Za-z0-9]+)", "sheet"),
        ]
        for pattern, doc_type in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1), doc_type
        raise ValueError(f"无法解析飞书文档URL: {url}")

    async def get_user_info(self, open_id: str, access_token: str) -> dict:
        """获取飞书用户信息"""
        data = await self._get(
            f"/contact/v3/users/{open_id}",
            auth_token=access_token,
        )
        return data.get("data", {}).get("user", {})


feishu_service = FeishuService()

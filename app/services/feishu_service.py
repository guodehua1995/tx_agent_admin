import logging

import httpx

from app.settings import settings
from app.utils.feishu_doc_parser import FeishuDocParser

logger = logging.getLogger(__name__)


class FeishuService:
    """飞书 API 封装"""

    def __init__(self):
        self._base_url = settings.FEISHU_BASE_URL
        self._verify_ssl = settings.FEISHU_VERIFY_SSL

    async def get_tenant_access_token(self, app_id: str, app_secret: str) -> str:
        """获取 tenant_access_token"""
        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            resp = await client.post(
                f"{self._base_url}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            data = resp.json()
            if data.get("code") != 0:
                raise Exception(f"获取飞书token失败: {data.get('msg')}")
            return data["tenant_access_token"]

    async def fetch_document_content(self, doc_token: str, doc_type: str, access_token: str) -> str:
        """拉取飞书云文档内容"""
        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            # resp = await client.get(
            #     f"{self._base_url}/docx/v1/documents/{doc_token}/blocks",
            #     headers={"Authorization": f"Bearer {access_token}"},
            # )
            resp = await client.get(
                f"{self._base_url}/docx/v1/documents/{doc_token}/raw_content",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            logger.info(f"Feishu Doc Content: {resp}")
            data = resp.json()
           
            if data.get("code") != 0:
                raise Exception(f"拉取飞书文档失败: {data.get('msg')}")
            # TODO 验证agent结构化飞书数据 如果成立将parse删除
            # fs_dco_parser = FeishuDocParser()
            # return fs_dco_parser.parse(data.get("data", {}).get("items", []))
            return data.get("data", {}).get("content", "")

    async def send_message(
        self, app_id: str, app_secret: str, chat_id: str, content: str, msg_type: str = "interactive"
    ) -> None:
        """发送飞书消息"""
        token = await self.get_tenant_access_token(app_id, app_secret)
        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            await client.post(
                f"{self._base_url}/im/v1/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"receive_id_type": "chat_id"},
                json={"receive_id": chat_id, "msg_type": msg_type, "content": content},
            )

    async def build_answer_card(self, answer: str, sources: list) -> dict:
        """构建消息卡片"""
        source_elements = []
        for i, src in enumerate(sources[:3], 1):
            title = src.get("metadata", {}).get("title", "未知来源")
            score = src.get("score", 0)
            source_elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"{i}. {title} (相关度: {score:.2f})"}})

        card = {
            "config": {"wide_screen_mode": True},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": answer}},
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "plain_text", "content": "参考来源:"}},
                *source_elements,
            ],
        }
        return card

    async def create_doc_in_folder(self, folder_token: str, title: str, content: str, access_token: str) -> str:
        """将结构化结果发布到飞书云文档指定文件夹"""
        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            resp = await client.post(
                f"{self._base_url}/docx/v1/documents",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"folder_token": folder_token, "title": title},
            )
            data = resp.json()
            if data.get("code") != 0:
                raise Exception(f"创建飞书文档失败: {data.get('msg')}")

            doc_id = data["data"]["document"]["document_id"]

            await client.post(
                f"{self._base_url}/docx/v1/documents/{doc_id}/blocks/batch_update",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"requests": [{"block_id": doc_id, "update_text_elements": {"elements": [{"text_run": {"content": content}}]}}]},
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
        import re

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
        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            resp = await client.get(
                f"{self._base_url}/contact/v3/users/{open_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            data = resp.json()
            return data.get("data", {}).get("user", {})


feishu_service = FeishuService()

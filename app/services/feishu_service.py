import asyncio
import base64
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
        # 复用连接池，避免并发时大量短连接导致 ConnectTimeout
        # timeout: 连接/读取均设 30s，应对飞书 API 偶发慢响应
        self._client = httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=httpx.Timeout(30.0, connect=15.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

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

        resp = await self._client.request(method, url, headers=headers, **kwargs)
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

    async def build_answer_card(self, answer: str, sources: list, image_keys: list[str] | None = None) -> dict:
        """构建消息卡片

        飞书卡片 markdown 标签支持的格式：
        - **粗体**
        - *斜体*
        - ~~删除线~~
        - [链接](url)
        - 无序列表 (- )
        - 有序列表 (1. )
        - 代码块
        - > 引用

        不支持 # 标题，需要用其他方式处理

        Args:
            image_keys: 可选的飞书 IM 图片 image_key 列表，追加为卡片 img 元素
        """
        # 处理标题：将 # 转为加粗文本
        import re
        def convert_heading(match):
            level = len(match.group(1))
            text = match.group(2).strip()
            if level == 1:
                return f"**{text}**"
            elif level == 2:
                return f"**{text}**"
            else:  # level >= 3
                return f"*{text}*"

        # 将 # 标题转换为加粗文本
        answer = re.sub(r'^(#{1,3})\s+(.+)$', convert_heading, answer, flags=re.MULTILINE)

        source_elements = ""
        for i, src in enumerate(sources[:3], 1):
            metadata = src.get("metadata", {})
            type = metadata.get("type")
            if type == "doc_url" or type == "img_url":
                title = metadata.get("title", "未知来源")
                url = metadata.get("url")
                if url:
                    source_elements += f"[{title}]({url})\n"

        elements = [
            {"tag": "markdown", "content": answer},
        ]

        # PDF/PPT 召回页截图以原生 img 元素插入，避免依赖外链可达性
        if image_keys:
            elements.append({"tag": "hr"})
            elements.append({"tag": "markdown", "content": "**参考页截图：**"})
            for img_key in image_keys:
                elements.append({
                    "tag": "img",
                    "img_key": img_key,
                    "alt": {"tag": "plain_text", "content": "页截图"},
                    "mode": "fit_horizontal",
                    "preview": True,
                })

        if source_elements:
            elements.extend([
                {"tag": "hr"},
                {"tag": "markdown", "content": "**参考来源:**\n" + source_elements},
            ])

        return {
            "config": {"wide_screen_mode": True},
            "elements": elements,
        }

    async def upload_message_image(
        self, app_id: str, app_secret: str, image_bytes: bytes
    ) -> str:
        """上传图片到飞书 IM 附件存储，返回 image_key

        对应开放平台接口 POST /im/v1/images，image_type=message。
        上传的图片不占用企业云盘容量，由飞书内部托管。
        """
        token = await self.get_tenant_access_token(app_id, app_secret)
        url = f"{self._base_url}/im/v1/images"
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=60) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": ("page.png", image_bytes, "image/png")},
            )
            data = resp.json()
        code = data.get("code")
        if code is not None and code != 0:
            raise FeishuAPIError(data.get("msg", "图片上传失败"), code=code)
        return data["data"]["image_key"]

    async def upload_image_keys_from_sources(
        self,
        app_id: str,
        app_secret: str,
        sources: list,
        max_count: int = 3,
    ) -> list[str]:
        """从 RAG sources 中拽出 PDF/PPT 页截图，读 TOS 字节后上传飞书拿 image_key。

        触发条件：元素 type==img_url 且 doc_type_code 在 (pdf,ppt) 或存在分页信息。
        仅取前 max_count 张以限制卡片体量与上传 QPS。
        单张失败不影响其他张。

        缓存：以 (app_id, screenshot_key) 为键复用已上传过的 image_key，
        缓存后端由 IMAGE_KEY_CACHE_BACKEND 控制（memory/redis）。
        """
        from app.services.file_storage import file_storage
        from app.services.image_key_cache import image_key_cache

        candidates: list[dict] = []
        seen_keys: set[str] = set()
        for src in sources:
            meta = src.get("metadata") or {}
            if meta.get("type") != "img_url":
                continue
            key = meta.get("screenshot_key")
            if not key or key in seen_keys:
                continue
            doc_type_code = (meta.get("doc_type_code") or "").lower()
            page_number = meta.get("page_number")
            # PDF/PPT 或存在分页元信息都视为有效
            if doc_type_code not in ("pdf", "ppt") and page_number is None:
                continue
            seen_keys.add(key)
            candidates.append({"key": key, "page_number": page_number})
            if len(candidates) >= max_count:
                break

        if not candidates:
            return []

        image_keys: list[str] = []
        for c in candidates:
            screenshot_key = c["key"]
            try:
                # 1) 缓存命中则直接复用
                cached = await image_key_cache.get(app_id, screenshot_key)
                if cached:
                    image_keys.append(cached)
                    logger.debug(
                        f"[Feishu] image_key cache hit: app_id={app_id}, key={screenshot_key}"
                    )
                    continue

                # 2) 未命中：读 TOS 字节 + 上传飞书 + 回写缓存
                img_bytes = await file_storage.read_bytes(screenshot_key)
                image_key = await self.upload_message_image(app_id, app_secret, img_bytes)
                await image_key_cache.set(app_id, screenshot_key, image_key)
                image_keys.append(image_key)
            except Exception as e:
                logger.warning(
                    f"[Feishu] Upload page screenshot failed: key={screenshot_key}, err={e}"
                )
        return image_keys


    async def create_doc_in_folder(self, folder_token: str, title: str, content: str, access_token: str) -> str:
        """将切片结果发布到飞书云文档指定文件夹"""
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
            (r"feishu\.cn/slides/([A-Za-z0-9]+)", "slide"),
            (r"feishu\.cn/file/([A-Za-z0-9]+)", "file"),
        ]
        for pattern, doc_type in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1), doc_type
        raise ValueError(f"无法解析飞书文档URL: {url}")

    def parse_feishu_folder_url(self, url_or_token: str) -> str:
        """解析飞书文件夹 URL，返回 folder_token。

        兼容两种输入：
        - 完整 URL：https://xxx.feishu.cn/drive/folder/<token> 或 .../folder/<token>
        - 裸 token。
        """
        if not url_or_token:
            raise ValueError("文件夹地址不能为空")

        # 带 URL 的情况
        match = re.search(r"/(?:drive/)?folder/([A-Za-z0-9]+)", url_or_token)
        if match:
            return match.group(1)

        # 裸 token：允许字母数字组合，不含斜杠与协议头
        if "://" not in url_or_token and "/" not in url_or_token:
            return url_or_token.strip()

        raise ValueError(f"无法解析飞书文件夹地址: {url_or_token}")

    async def list_files_in_folder(
        self,
        folder_token: str,
        access_token: str,
        page_size: int = 200,
        max_files: int = 5000,
    ) -> list[dict]:
        """列出文件夹下所有文件（循环翻页直到 has_more=false）。

        飞书未提供「文件夹文件总数」查询能力，只能通过分页逐页拉取。
        GET /open-apis/drive/v1/files?folder_token=xxx&page_size=200&page_token=xxx
        返回体：{files: [...], has_more: bool, next_page_token: str}

        Args:
            max_files: 超过该上限会提前终止并警告，避免异常巨大文件夹拖垮扫描。
        """
        files: list[dict] = []
        page_token: Optional[str] = None
        while True:
            params: dict = {"folder_token": folder_token, "page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            data = await self._get("/drive/v1/files", auth_token=access_token, params=params)
            payload = data.get("data") or {}
            batch = payload.get("files") or []
            files.extend(batch)
            if len(files) >= max_files:
                logger.warning(
                    f"[FeishuFolder] file count exceeds max_files={max_files}, "
                    f"truncated: folder_token={folder_token}"
                )
                break
            if not payload.get("has_more"):
                break
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return files

    async def download_file(self, file_token: str, access_token: str) -> tuple[bytes, str]:
        """下载飞书云空间文件

        Args:
            file_token: 文件 token
            access_token: 访问凭证

        Returns:
            (file_bytes, filename) 元组，filename 包含扩展名
        """
        url = f"{self._base_url}/drive/v1/files/{file_token}/download"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=120) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()

            # 从 Content-Disposition 提取文件名
            filename = self._extract_filename_from_headers(resp.headers, file_token)
            return resp.content, filename

    def _extract_filename_from_headers(self, headers, fallback_token: str) -> str:
        """从响应头 Content-Disposition 中提取文件名"""
        content_disposition = headers.get("content-disposition", "")
        if content_disposition:
            # 尝试匹配 filename*=UTF-8''xxx 或 filename="xxx"
            match = re.search(r"filename\*=UTF-8''(.+?)(?:;|$)", content_disposition)
            if match:
                from urllib.parse import unquote
                return unquote(match.group(1))
            match = re.search(r'filename="?([^";]+)"?', content_disposition)
            if match:
                return match.group(1)

        # fallback: 用 content-type 推断扩展名
        content_type = headers.get("content-type", "")
        ext_map = {
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            "text/csv": ".csv",
            "text/plain": ".txt",
            "image/png": ".png",
            "image/jpeg": ".jpg",
        }
        for mime, ext in ext_map.items():
            if mime in content_type:
                return f"{fallback_token}{ext}"

        return f"{fallback_token}.bin"

    async def get_user_info(self, open_id: str, access_token: str) -> dict:
        """获取飞书用户信息"""
        data = await self._get(
            f"/contact/v3/users/{open_id}",
            auth_token=access_token,
        )
        return data.get("data", {}).get("user", {})

    async def upload_media_for_import(self, file_content: bytes, file_name: str, access_token: str) -> str:
        """上传文件到飞书用于导入，返回 file_token"""
        url = f"{self._base_url}/drive/v1/medias/upload_all"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            resp = await client.post(
                url,
                headers=headers,
                data={
                    "file_name": file_name,
                    "parent_type": "explorer",
                    "parent_node": "",
                    "size": str(len(file_content)),
                },
                files={"file": (file_name, file_content, "application/octet-stream")},
            )
            data = resp.json()

        code = data.get("code")
        if code is not None and code != 0:
            raise FeishuAPIError(data.get("msg", "文件上传失败"), code=code)
        return data["data"]["file_token"]

    async def import_markdown_to_folder(
        self, folder_token: str, title: str, markdown_content: str, access_token: str
    ) -> str:
        """通过飞书导入API将Markdown内容创建为飞书云文档

        流程: 上传md文件 -> 创建导入任务 -> 轮询完成 -> 返回文档URL
        """
        import asyncio

        # 1. 上传markdown内容作为文件
        file_bytes = markdown_content.encode("utf-8")
        file_name = f"{title}.md"
        file_token = await self.upload_media_for_import(file_bytes, file_name, access_token)

        # 2. 创建导入任务
        data = await self._post(
            "/drive/v1/import_tasks",
            auth_token=access_token,
            json={
                "file_extension": "md",
                "file_token": file_token,
                "type": "docx",
                "point": {
                    "mount_type": 1,
                    "mount_key": folder_token,
                },
            },
        )
        ticket = data["data"]["ticket"]

        # 3. 轮询导入任务状态 (最多30秒)
        for _ in range(15):
            await asyncio.sleep(2)
            result = await self._get(
                f"/drive/v1/import_tasks/{ticket}",
                auth_token=access_token,
            )
            job_status = result.get("data", {}).get("result", {}).get("job_status", 0)
            if job_status == 0:
                doc_token = result["data"]["result"]["token"]
                return f"https://my.feishu.cn/docx/{doc_token}"
            elif job_status >= 100:
                error_msg = result.get("data", {}).get("result", {}).get("job_error_msg", "导入失败")
                raise FeishuAPIError(f"飞书文档导入失败: {error_msg}")

        raise FeishuAPIError("飞书文档导入超时，请稍后重试")


feishu_service = FeishuService()

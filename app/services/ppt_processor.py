"""
PPT 转 Markdown 处理器

将 PPT 文件按页转为图片，调用多模态 LLM 理解图片内容，输出 Markdown 格式文档。
支持本地 PPT 文件上传和飞书云文档 URL。
"""

import base64
import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Optional

from app.controllers.ai_config import ai_config_controller
from app.log import logger


# PPT 单页图片理解的 System Prompt
PPT_PAGE_SYSTEM_PROMPT = """你是一个专业的PPT内容解析专家。你的任务是分析PPT页面的截图，将其内容转换为结构化的Markdown格式。

要求：
1. 准确识别页面中的所有文本内容（标题、正文、列表项等）
2. 保持原始的层级结构和逻辑关系
3. 识别并描述图表、图片等视觉元素的含义
4. 如果有表格，使用Markdown表格格式输出
5. 保留关键的数据和数字信息
6. 忽略纯装饰性元素（如背景图案、页码等）

输出要求：
- 只输出该页内容的Markdown文本
- 不要添加额外解释或前缀
- 确保Markdown语法正确
- 不要输出"这一页包含..."之类的描述性文字，直接输出内容"""


class PPTProcessor:
    """PPT 文档处理器：PPT → 图片 → LLM 理解 → Markdown"""

    def __init__(self):
        self._libreoffice_path: Optional[str] = None

    def _find_libreoffice(self) -> str:
        """查找 LibreOffice 可执行文件路径"""
        if self._libreoffice_path:
            return self._libreoffice_path

        # Windows 常见路径
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        # Linux/Mac
        candidates += ["/usr/bin/libreoffice", "/usr/bin/soffice", "/opt/libreoffice/program/soffice"]

        for path in candidates:
            if os.path.isfile(path):
                self._libreoffice_path = path
                return path

        # 尝试 PATH 中查找
        import shutil
        for name in ("soffice", "libreoffice"):
            found = shutil.which(name)
            if found:
                self._libreoffice_path = found
                return found

        raise RuntimeError(
            "未找到 LibreOffice，请安装 LibreOffice 以支持 PPT 转图片。"
            "下载地址: https://www.libreoffice.org/download/"
        )

    def _ppt_to_pdf(self, ppt_path: str, output_dir: str) -> str:
        """使用 LibreOffice 将 PPT 转为 PDF"""
        soffice = self._find_libreoffice()
        cmd = [
            soffice,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            ppt_path,
        ]
        logger.info(f"[PPTProcessor] Converting PPT to PDF: {ppt_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice 转换失败: {result.stderr}")

        # 输出的 PDF 文件名与输入相同，扩展名改为 .pdf
        pdf_name = Path(ppt_path).stem + ".pdf"
        pdf_path = os.path.join(output_dir, pdf_name)
        if not os.path.isfile(pdf_path):
            raise RuntimeError(f"转换后未找到 PDF 文件: {pdf_path}")
        return pdf_path

    def _pdf_to_images(self, pdf_path: str) -> list[bytes]:
        """将 PDF 每页转为 PNG 图片，返回图片字节列表"""
        from pdf2image import convert_from_path

        images = convert_from_path(pdf_path, dpi=200, fmt="png")
        result = []
        for img in images:
            buf = BytesIO()
            img.save(buf, format="PNG")
            result.append(buf.getvalue())
        logger.info(f"[PPTProcessor] PDF converted to {len(result)} page images")
        return result

    def _ppt_to_images(self, ppt_bytes: bytes, filename: str = "input.pptx") -> list[bytes]:
        """将 PPT 字节转为每页 PNG 图片列表"""
        with tempfile.TemporaryDirectory(prefix="ppt_proc_") as tmpdir:
            # 写入临时 PPT 文件
            ppt_path = os.path.join(tmpdir, filename)
            with open(ppt_path, "wb") as f:
                f.write(ppt_bytes)

            # PPT → PDF
            pdf_path = self._ppt_to_pdf(ppt_path, tmpdir)

            # PDF → Images
            return self._pdf_to_images(pdf_path)

    async def _call_vision_llm(self, image_bytes: bytes, page_num: int) -> str:
        """调用多模态 LLM 理解单页 PPT 图片内容"""
        from llama_index.llms.openai_like import OpenAILike
        from llama_index.core.llms import ChatMessage, ImageBlock, TextBlock

        # 获取可用的 Chat 模型（需要支持 vision）
        chat_models = await ai_config_controller.get_active_chat_models()
        if not chat_models:
            raise ValueError("没有可用的 Chat 模型配置，无法处理 PPT 图片")
        model_config = chat_models[0]

        extra = model_config.extra_config or {}
        llm = OpenAILike(
            api_base=model_config.api_base_url,
            api_key=model_config.api_key,
            model=model_config.model_name,
            max_tokens=model_config.max_tokens,
            temperature=extra.get("temperature", 0.3),
            is_chat_model=True,
        )

        # 构建带图片的消息
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:image/png;base64,{image_b64}"

        messages = [
            ChatMessage(role="system", content=PPT_PAGE_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                blocks=[
                    TextBlock(text=f"请分析以下PPT第 {page_num} 页的内容，将其转换为Markdown格式："),
                    ImageBlock(url=image_url),
                ],
            ),
        ]

        response = await llm.achat(messages)
        return response.message.content

    async def process_ppt_to_markdown(
        self,
        ppt_bytes: bytes,
        filename: str = "input.pptx",
        source_path: str = "",
    ) -> str:
        """
        完整处理流程：PPT 字节 → 每页图片 → LLM 理解 → 拼接为 Markdown

        Args:
            ppt_bytes: PPT 文件的二进制内容
            filename: 文件名（用于临时文件）
            source_path: 来源路径/URL，记录在日志中

        Returns:
            完整的 Markdown 文本（每页以一级标题分隔）
        """
        logger.info(f"[PPTProcessor] Starting PPT processing: {filename}, source={source_path}")

        # 1. PPT → 图片
        page_images = self._ppt_to_images(ppt_bytes, filename)
        if not page_images:
            raise ValueError("PPT 文件没有任何页面内容")

        # 2. 逐页调用 LLM 理解
        markdown_pages = []
        for i, img_bytes in enumerate(page_images, start=1):
            logger.info(f"[PPTProcessor] Processing page {i}/{len(page_images)}")
            try:
                page_md = await self._call_vision_llm(img_bytes, i)
                # 每页以一级标题开头
                page_content = f"# 第{i}页\n\n{page_md}"
                markdown_pages.append(page_content)
            except Exception as e:
                logger.error(f"[PPTProcessor] Failed to process page {i}: {e}")
                markdown_pages.append(f"# 第{i}页\n\n> [页面处理失败: {str(e)}]")

        # 3. 拼接所有页面
        full_markdown = "\n\n---\n\n".join(markdown_pages)
        logger.info(
            f"[PPTProcessor] PPT processing complete: {len(page_images)} pages, "
            f"{len(full_markdown)} chars"
        )
        return full_markdown

    async def process_from_file_path(self, file_path: str) -> str:
        """从本地文件路径处理 PPT"""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"PPT 文件不存在: {file_path}")

        with open(file_path, "rb") as f:
            ppt_bytes = f.read()

        filename = os.path.basename(file_path)
        return await self.process_ppt_to_markdown(ppt_bytes, filename, source_path=file_path)

    async def process_from_feishu_url(self, feishu_url: str) -> str:
        """从飞书云文档 URL 下载并处理 PPT"""
        from app.controllers.feishu_bot import feishu_bot_controller
        from app.models.global_config import GlobalConfig
        from app.services.feishu_service import feishu_service

        # 获取飞书访问凭证
        global_config = await GlobalConfig.get(config_key="feishu_pull_bot")
        if not global_config:
            raise ValueError("没有配置飞书拉取机器人(feishu_pull_bot)")
        bot_config = await feishu_bot_controller.get_by_app_id(app_id=global_config.config_value)
        if not bot_config:
            raise ValueError("没有可用的飞书机器人配置")

        access_token = await feishu_service.get_tenant_access_token(
            bot_config.app_id, bot_config.app_secret
        )

        # 解析飞书 URL 获取文件 token
        doc_token, doc_type = feishu_service.parse_feishu_url(feishu_url)

        # 通过飞书导出接口下载 PPT（导出为 pptx 格式）
        ppt_bytes = await self._download_feishu_ppt(doc_token, access_token)

        filename = f"{doc_token}.pptx"
        return await self.process_ppt_to_markdown(ppt_bytes, filename, source_path=feishu_url)

    async def _download_feishu_ppt(self, file_token: str, access_token: str) -> bytes:
        """从飞书下载 PPT 文件"""
        import httpx

        base_url = "https://open.feishu.cn/open-apis"
        headers = {"Authorization": f"Bearer {access_token}"}

        # 创建导出任务
        export_resp = await self._feishu_request(
            "POST",
            f"{base_url}/drive/v1/export_tasks",
            headers=headers,
            json={"file_extension": "pptx", "token": file_token, "type": "slide"},
        )
        ticket = export_resp["data"]["ticket"]

        # 轮询导出结果
        import asyncio
        for _ in range(60):
            poll_resp = await self._feishu_request(
                "GET",
                f"{base_url}/drive/v1/export_tasks/{ticket}",
                headers=headers,
                params={"token": file_token},
            )
            job_status = poll_resp["data"]["result"]["job_status"]
            if job_status == 0:  # 成功
                download_token = poll_resp["data"]["result"]["file_token"]
                break
            elif job_status == 1 or job_status == 2:  # 进行中
                await asyncio.sleep(2)
            else:
                raise RuntimeError(f"飞书导出任务失败, status={job_status}")
        else:
            raise TimeoutError("飞书 PPT 导出超时")

        # 下载文件
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base_url}/drive/v1/export_tasks/file/{download_token}/download",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.content

    async def _feishu_request(self, method: str, url: str, **kwargs) -> dict:
        """飞书 API 请求封装"""
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code", 0) != 0:
                raise RuntimeError(f"飞书 API 错误: {data.get('msg', 'unknown')}")
            return data

    def get_page_documents(self, full_markdown: str, source_path: str) -> list[dict]:
        """
        将完整的 PPT Markdown 按页拆分为文档列表，用于分页向量化。

        Args:
            full_markdown: 完整的 PPT Markdown 内容（页间以一级标题分隔）
            source_path: PPT 来源路径（file_path 或 feishu_url）

        Returns:
            列表，每项包含 {"text": "...", "metadata": {...}}
        """
        import re

        # 按一级标题分割页面
        pages = re.split(r"(?=^# )", full_markdown, flags=re.MULTILINE)
        pages = [p.strip() for p in pages if p.strip()]

        documents = []
        for i, page_text in enumerate(pages, start=1):
            documents.append({
                "text": page_text,
                "metadata": {
                    "source": "ppt",
                    "ppt_path": source_path,
                    "page_number": i,
                    "total_pages": len(pages),
                },
            })
        return documents


# 模块级单例
ppt_processor = PPTProcessor()

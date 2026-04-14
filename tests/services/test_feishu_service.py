"""飞书服务单元测试

测试范围:
- tenant_access_token 获取
- 文档内容拉取
- 消息发送
- 消息卡片构建
- 文档创建发布
- Webhook 验证
- 飞书 URL 解析
- 用户信息获取
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_client(responses: list[dict]):
    """构建一个模拟 httpx.AsyncClient，按调用顺序返回指定响应。

    每个 response dict 需要包含 json() 返回值。
    """
    mock_client = AsyncMock()
    resp_mocks = []
    for r in responses:
        resp_mock = MagicMock()
        resp_mock.json.return_value = r
        resp_mocks.append(resp_mock)

    mock_client.post.side_effect = resp_mocks if len(resp_mocks) > 1 else None
    mock_client.get.side_effect = resp_mocks if len(resp_mocks) > 1 else None
    if len(resp_mocks) == 1:
        mock_client.post.return_value = resp_mocks[0]
        mock_client.get.return_value = resp_mocks[0]

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_client
    return ctx, mock_client


# ========== get_tenant_access_token ==========


class TestGetTenantAccessToken:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        ctx, mock_client = _make_mock_client([{
            "code": 0,
            "tenant_access_token": "t-abc123",
        }])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            token = await svc.get_tenant_access_token("app1", "secret1")

        assert token == "t-abc123"
        mock_client.post.assert_called_once_with(
            "https://test.feishu.cn/auth/v3/tenant_access_token/internal",
            json={"app_id": "app1", "app_secret": "secret1"},
        )

    @pytest.mark.asyncio
    async def test_error_raises(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        ctx, _ = _make_mock_client([{"code": 99999, "msg": "invalid app_id"}])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            with pytest.raises(Exception, match="获取飞书token失败"):
                await svc.get_tenant_access_token("bad", "bad")


# ========== fetch_document_content ==========


class TestFetchDocumentContent:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        ctx, mock_client = _make_mock_client([{
            "code": 0,
            "data": {"content": "# 文档标题\n\n文档内容"},
        }])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            content = await svc.fetch_document_content("doc_token_1", "docx", "token123")

        assert content == "# 文档标题\n\n文档内容"
        mock_client.get.assert_called_once_with(
            "https://test.feishu.cn/docx/v1/documents/doc_token_1/raw_content",
            headers={"Authorization": "Bearer token123"},
        )

    @pytest.mark.asyncio
    async def test_error_raises(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        ctx, _ = _make_mock_client([{"code": 40003, "msg": "no permission"}])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            with pytest.raises(Exception, match="拉取飞书文档失败"):
                await svc.fetch_document_content("doc1", "docx", "token")


# ========== send_message ==========


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_sends_message(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"
        svc.get_tenant_access_token = AsyncMock(return_value="t-token")

        ctx, mock_client = _make_mock_client([{"code": 0}])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            await svc.send_message("app1", "secret1", "chat_id_1", '{"text":"hello"}')

        svc.get_tenant_access_token.assert_called_once_with("app1", "secret1")
        mock_client.post.assert_called_once_with(
            "https://test.feishu.cn/im/v1/messages",
            headers={"Authorization": "Bearer t-token"},
            params={"receive_id_type": "chat_id"},
            json={"receive_id": "chat_id_1", "msg_type": "interactive", "content": '{"text":"hello"}'},
        )


# ========== build_answer_card ==========


class TestBuildAnswerCard:
    @pytest.mark.asyncio
    async def test_card_structure(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()

        sources = [
            {"metadata": {"title": "知识库文档A"}, "score": 0.95},
            {"metadata": {"title": "知识库文档B"}, "score": 0.82},
        ]
        card = await svc.build_answer_card("这是回答内容", sources)

        assert card["config"]["wide_screen_mode"] is True
        elements = card["elements"]
        # 回答内容
        assert elements[0]["text"]["content"] == "这是回答内容"
        # 分割线
        assert elements[1]["tag"] == "hr"
        # 参考来源标题
        assert "参考来源" in elements[2]["text"]["content"]
        # 来源条目
        assert "知识库文档A" in elements[3]["text"]["content"]
        assert "0.95" in elements[3]["text"]["content"]
        assert "知识库文档B" in elements[4]["text"]["content"]

    @pytest.mark.asyncio
    async def test_card_limits_sources_to_3(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()

        sources = [
            {"metadata": {"title": f"doc{i}"}, "score": 0.9 - i * 0.1}
            for i in range(5)
        ]
        card = await svc.build_answer_card("answer", sources)

        # 3 个元素（回答 + 分割线 + 参考来源标题） + 最多 3 条来源
        source_elements = [e for e in card["elements"] if e["tag"] == "div" and "相关度" in e.get("text", {}).get("content", "")]
        assert len(source_elements) == 3

    @pytest.mark.asyncio
    async def test_card_empty_sources(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        card = await svc.build_answer_card("answer", [])

        elements = card["elements"]
        # 回答 + 分割线 + 参考来源标题, 没有来源条目
        assert len(elements) == 3


# ========== create_doc_in_folder ==========


class TestCreateDocInFolder:
    @pytest.mark.asyncio
    async def test_success_returns_url(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        create_resp = MagicMock()
        create_resp.json.return_value = {
            "code": 0,
            "data": {"document": {"document_id": "docABC123"}},
        }
        update_resp = MagicMock()
        update_resp.json.return_value = {"code": 0}

        mock_client = AsyncMock()
        mock_client.post.side_effect = [create_resp, update_resp]

        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_client

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            url = await svc.create_doc_in_folder("folder1", "测试文档", "内容", "token")

        assert url == "https://open.feishu.cn/docx/docABC123"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_create_error_raises(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        ctx, mock_client = _make_mock_client([{"code": 99999, "msg": "创建失败"}])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            with pytest.raises(Exception, match="创建飞书文档失败"):
                await svc.create_doc_in_folder("folder1", "title", "content", "token")


# ========== verify_webhook ==========


class TestVerifyWebhook:
    def test_top_level_token_match(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        assert svc.verify_webhook({"token": "abc"}, "abc") is True

    def test_header_token_match(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        assert svc.verify_webhook({"header": {"token": "abc"}}, "abc") is True

    def test_no_match(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        assert svc.verify_webhook({"token": "wrong"}, "abc") is False

    def test_empty_body(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        assert svc.verify_webhook({}, "abc") is False


# ========== parse_feishu_url ==========


class TestParseFeishuUrl:
    def test_docx_url(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        token, doc_type = svc.parse_feishu_url("https://abc.feishu.cn/docx/XyZ123AbC")
        assert token == "XyZ123AbC"
        assert doc_type == "docx"

    def test_wiki_url(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        token, doc_type = svc.parse_feishu_url("https://abc.feishu.cn/wiki/WikiToken1")
        assert token == "WikiToken1"
        assert doc_type == "wiki"

    def test_sheet_url(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        token, doc_type = svc.parse_feishu_url("https://abc.feishu.cn/sheets/SheetABC")
        assert token == "SheetABC"
        assert doc_type == "sheet"

    def test_invalid_url_raises(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        with pytest.raises(ValueError, match="无法解析飞书文档URL"):
            svc.parse_feishu_url("https://example.com/random")


# ========== get_user_info ==========


class TestGetUserInfo:
    @pytest.mark.asyncio
    async def test_returns_user_data(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        ctx, mock_client = _make_mock_client([{
            "code": 0,
            "data": {"user": {"name": "张三", "open_id": "ou_123"}},
        }])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            user = await svc.get_user_info("ou_123", "token")

        assert user["name"] == "张三"
        assert user["open_id"] == "ou_123"
        mock_client.get.assert_called_once_with(
            "https://test.feishu.cn/contact/v3/users/ou_123",
            headers={"Authorization": "Bearer token"},
        )

    @pytest.mark.asyncio
    async def test_returns_empty_on_missing(self):
        from app.services.feishu_service import FeishuService

        svc = FeishuService()
        svc._base_url = "https://test.feishu.cn"

        ctx, _ = _make_mock_client([{"code": 0, "data": {}}])

        with patch("app.services.feishu_service.httpx.AsyncClient", return_value=ctx):
            user = await svc.get_user_info("ou_notfound", "token")

        assert user == {}

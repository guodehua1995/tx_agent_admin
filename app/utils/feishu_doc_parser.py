"""
飞书云文档 Block 解析工具
将飞书云文档 Block 结构转换为 Markdown 格式

支持的纯文本 Block 类型：
- 1: page 页面根节点
- 2: text 普通文本段落
- 3-11: heading1-heading9 标题
- 12: bullet 无序列表
- 13: ordered 有序列表
- 14: code 代码块
- 15: quote 引用块
- 20: divider 分割线

其他类型会记录 debug 日志并跳过
"""

from typing import Any

from app.log import logger


class FeishuDocParser:
    """飞书文档解析器"""

    # block_type 数字与属性名的映射
    BLOCK_TYPE_MAP = {
        1: "page",# 页面 Block
        2: "text",# 文本 Block
        3: "heading1", # 标题 1 Block
        4: "heading2",  
        5: "heading3",
        6: "heading4",
        7: "heading5",
        8: "heading6",
        9: "heading7",
        10: "heading8",
        11: "heading9",# 标题 9 Block   
        12: "bullet", # 无序列表 Block
        13: "ordered", # 有序列表 Block
        14: "code", # 代码块 Block
        15: "quote",# 引用 Block
        17: "todo", # 待办事项 Block
        18: "bitable", # 多维表格 Block
        19: "callout", # 高亮块 Block
        20: "chat_card", # 会话卡片 Block
        21: "diagram", # 流程图 & UML Block
        22: "divider", # 分割线 Block。为空结构体，需传入 {} 创建分割线 Block。
        23: "file", # 文件 Block
        24: "grid", # 分栏 Block
        25: "grid_column", # 分栏列 Block
        26: "iframe", # 内嵌网页 Block
        27: "image", # 图片 Block
        28: "isv",
        29: "mindnote", # 思维笔记 Block
        30: "sheet",# 电子表格 Block
        31: "table", # 表格 Block。
        32: "table_cell", # 表格单元格 Block

        33: "view",# 视图 Block
        34: "quote_container", # 引用容器 Block。为空结构体，需传入 {} 创建引用容器 Block。
        35: "task",# 任务 Block
        36: "okr",# OKR Block
        37: "okr_objective", #OKR Objective Block
        38: "okr_key_result",# OKR Key Result Block
        39: "okr_progress", # OKR 进展 Block、
        # ...还有一些暂时用不上
        999:"undefined"
    }

    # 纯文本相关的 block_type 数字
    TEXT_BLOCK_TYPES = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 20}

    def __init__(self):
        self.skipped_types = set()

    def parse(self, blocks: list[dict]) -> str:
        """
        解析飞书文档 Block 列表，返回 Markdown 字符串

        Args:
            blocks: 飞书 API 返回的 block 列表

        Returns:
            Markdown 格式字符串
        """
        self.skipped_types.clear()
        result = []

        for block in blocks:
            md = self._parse_block(block)
            if md:
                result.append(md)

        # 记录跳过的类型
        if self.skipped_types:
            logger.debug(f"Skipped block types: {self.skipped_types}")

        return "\n\n".join(result)

    def _parse_block(self, block: dict) -> str | None:
        """解析单个 Block"""
        block_type_num = block.get("block_type", 0)
        logger.debug(f"Processing block type: {block_type_num}")

        # 转换为整数
        try:
            block_type_num = int(block_type_num)
        except (ValueError, TypeError):
            logger.debug(f"Invalid block_type: {block_type_num}")
            return None

        # 获取属性名
        block_type_name = self.BLOCK_TYPE_MAP.get(block_type_num)
        if not block_type_name:
            logger.debug(f"Unknown block_type: {block_type_num}")
            return None

        # 处理纯文本相关类型
        if block_type_num in self.TEXT_BLOCK_TYPES:
            return self._parse_text_block(block, block_type_name)

        # 记录未处理的类型
        if block_type_num not in self.skipped_types:
            self.skipped_types.add(block_type_num)
            logger.debug(f"Skipping unsupported block type: {block_type_num} ({block_type_name})")

        return None

    def _parse_text_block(self, block: dict, block_type_name: str) -> str | None:
        """解析文本相关 Block"""
        # 获取 block 内容 - 使用属性名作为 key
        content = block.get(block_type_name, {})
        elements = content.get("elements", [])

        # 提取纯文本
        text = self._extract_text(elements)

        # 根据类型格式化
        formatters = {
            "page": lambda t: t,  # 页面根节点，直接返回内容
            "text": lambda t: t,  # 普通段落
            "heading1": lambda t: f"# {t}",
            "heading2": lambda t: f"## {t}",
            "heading3": lambda t: f"### {t}",
            "heading4": lambda t: f"#### {t}",
            "heading5": lambda t: f"##### {t}",
            "heading6": lambda t: f"###### {t}",
            "heading7": lambda t: f"####### {t}",
            "heading8": lambda t: f"######## {t}",
            "heading9": lambda t: f"######### {t}",
            "bullet": lambda t: f"- {t}",
            "ordered": lambda t: f"1. {t}",  # 简化处理，实际应维护序号
            "code": lambda t: f"```\n{t}\n```",
            "quote": lambda t: f"> {t}",
            "divider": lambda t: "---",
        }

        formatter = formatters.get(block_type_name)
        if formatter:
            return formatter(text) if text or block_type_name == "divider" else None

        return None

    def _extract_text(self, elements: list[dict]) -> str:
        """从 elements 中提取纯文本"""
        texts = []

        for elem in elements:
            elem_type = elem.get("type", "")

            if elem_type == "text_run":
                # 普通文本运行
                text_run = elem.get("text_run", {})
                content = text_run.get("content", "")
                texts.append(content)

            elif elem_type == "mention":
                # @提及
                mention = elem.get("mention", {})
                texts.append(mention.get("name", ""))

            elif elem_type == "url":
                # URL 链接
                url = elem.get("url", {})
                url_text = url.get("content", url.get("url", ""))
                texts.append(url_text)

            else:
                # 其他 element 类型，记录 debug
                logger.debug(f"Skipping unsupported element type: {elem_type}")

        return "".join(texts)


def parse_feishu_doc_to_markdown(blocks: list[dict]) -> str:
    """
    便捷函数：将飞书文档 Block 列表转换为 Markdown

    Args:
        blocks: 飞书 API 返回的 block 列表

    Returns:
        Markdown 格式字符串
    """
    parser = FeishuDocParser()
    return parser.parse(blocks)

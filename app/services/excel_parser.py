import logging
from io import BytesIO
from typing import Optional

import openpyxl

logger = logging.getLogger(__name__)

# 常见表头映射（兼容命名变体）
HEADER_MAPPING = {
    "项目名称": "name", "名称": "name", "项目": "name", "服务项": "name",
    "编码": "code", "项目编码": "code", "编号": "code",
    "单价": "unit_price", "价格": "unit_price", "报价": "unit_price",
    "单位": "unit", "计量单位": "unit",
    "备注": "remark", "说明": "remark",
}


class ExcelParseError(Exception):
    pass


def parse_quotation_excel(file_bytes: bytes) -> dict:
    """
    解析报价单 Excel，返回结构化明细 + 警告列表。

    返回格式：
    {
        "items": [{"name": ..., "code": ..., "unit_price": ..., "unit": ..., "children": [...]}],
        "warnings": ["第5行无法识别项目名称"]
    }
    """
    wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ExcelParseError("Excel 文件为空")

    # 识别表头行（取前5行中最匹配的一行）
    header_row_idx, col_map = _detect_header(rows[:5])
    if not col_map or "name" not in col_map:
        raise ExcelParseError("无法识别表头，请确保包含'项目名称'列")

    items = []
    warnings = []
    current_parent = None

    for row_idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
        parsed = _parse_row(row, col_map)
        if not parsed.get("name"):
            # 可能是空行或分隔行
            if any(cell for cell in row if cell):
                warnings.append(f"第{row_idx}行无法识别项目名称，标记为待确认")
            continue

        # 层级判定：有单价的为末级（可能是二级），无单价的为一级分类
        if parsed.get("unit_price") is not None:
            if current_parent is not None:
                current_parent["children"].append(parsed)
            else:
                items.append(parsed)
        else:
            # 无单价 → 一级分类项目
            current_parent = {**parsed, "children": []}
            items.append(current_parent)

    wb.close()
    return {"items": items, "warnings": warnings}


def _detect_header(candidate_rows: list) -> tuple[int, Optional[dict]]:
    """检测表头行，返回 (行索引, 列名→字段映射)"""
    best_idx = 0
    best_map = {}
    best_score = 0

    for idx, row in enumerate(candidate_rows):
        col_map = {}
        score = 0
        for col_idx, cell in enumerate(row):
            if cell is None:
                continue
            cell_str = str(cell).strip()
            if cell_str in HEADER_MAPPING:
                col_map[HEADER_MAPPING[cell_str]] = col_idx
                score += 1
        if score > best_score:
            best_score = score
            best_map = col_map
            best_idx = idx

    return best_idx, best_map if best_score >= 1 else (0, None)


def _parse_row(row: tuple, col_map: dict) -> dict:
    """按列映射解析单行"""
    result = {}
    for field, col_idx in col_map.items():
        val = row[col_idx] if col_idx < len(row) else None
        if field == "unit_price" and val is not None:
            try:
                result[field] = float(val)
            except (ValueError, TypeError):
                result[field] = None
        else:
            result[field] = str(val).strip() if val else None
    return result

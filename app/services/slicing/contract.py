"""合同文档切片处理器

合同向量化前的切片预处理（各 LLM 任务彼此独立，避免 prompt 混合）：

1. 元信息提取（独立 1 次调用）：取合同前 N 页 + 后 N 页的文本，提取 party_a / party_b / contract_type；
2. 条款结构分析（滑动窗口 N 次 + 必要时兜底 LLM 调用）：每轮 5000 字，LLM 仅输出 marker，
   代码 find() 切分；定位失败的 marker 把所属 chunk 再送 LLM 让其逐字复制完整原文作为兜底；
3. 明细数据摘要化（按条款逐个处理）：对含大段表格/清单的条款，LLM 将明细数据替换为简短描述；
4. 概要生成（独立 1 次调用）：基于元信息 + 前若干条款生成合同概要，作为 clause_index=0 入库。
"""

from __future__ import annotations

import datetime
import json
import re
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.log import logger
from app.models.rag import DocumentPage

from . import SlicingResult, register_handler
from .base import BaseSlicingHandler, LLMCallError

# 控制字符正则：保留 \t \n \r，移除其余 C0/C1 控制字符
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')


def _sanitize_text(text: str) -> str:
    """清除文本中的控制字符，避免透传到 LLM JSON 输出时导致解析失败。"""
    if not text:
        return text
    return _CONTROL_CHARS_RE.sub('', text)


# ── Pydantic 响应模型（用于 LangChain with_structured_output）──────────────

class MetaExtractResponse(BaseModel):
    """合同元信息提取结果"""
    model_config = ConfigDict(coerce_numbers_to_str=True)  # LLM 可能返回 int/float，自动转 str

    party_a: str = Field(default="", description="甲方简称")
    party_b: str = Field(default="", description="乙方简称")
    contract_type: str = Field(default="其他", description="合同类型")
    signing_date: Optional[str] = Field(default="", description="签订日期，YYYY-MM-DD")
    expiry_date: Optional[str] = Field(default="", description="到期日期，YYYY-MM-DD")
    total_amount: Optional[str] = Field(default=None, description="合同总金额（纯数字，无货币符号）")


class MarkerItem(BaseModel):
    """条款 marker（定位标记）"""
    title: str = Field(description="条款标题")
    level: int = Field(default=0, description="条款层级（0=顶级）")
    marker: str = Field(description="条款起始标记文本（原文中 find() 定位用）")


class StructureAnalyzeResponse(BaseModel):
    """条款结构分析结果"""
    clause_markers: list[MarkerItem] = Field(default_factory=list, description="条款 marker 列表")


class ContentResponse(BaseModel):
    """通用内容响应（条款补取、明细摘要）"""
    content: str = Field(default="", description="处理后的文本内容")


class SummaryResponse(BaseModel):
    """合同概要 + 合同判断"""
    model_config = ConfigDict(coerce_numbers_to_str=True)
    summary: str = Field(default="", description="文档内容概要，200~400字")
    is_contract: bool = Field(default=False, description="该文档是否为合同/协议类法律文书")


# 滑动窗口配置
WINDOW_SIZE = 5000          # 每轮送入 LLM 的字符数
MIN_PROGRESS = 500          # 兜底推进字符数（防死循环）
META_PAGES_HEAD = 2         # 元信息提取：取前 N 页
META_PAGES_TAIL = 2         # 元信息提取：取后 N 页
SUMMARY_CONTEXT_CLAUSES = 5 # 概要生成：取前 N 条作为上下文
MAX_INPUT_CHARS = 3000      # 单次 LLM 输入上限（字符数），超长在完整语句边界截断

# 句子边界字符（用于截断时定位完整语句结尾）
_SENTENCE_BOUNDARIES = '。\n；？！.?;!'


def _truncate_at_sentence_boundary(text: str, max_chars: int = MAX_INPUT_CHARS) -> str:
    """截断文本到 max_chars 以内，在完整语句边界（句号/换行等）处截断。

    若找不到句子边界，则硬截断。
    """
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    best_pos = -1
    for boundary in _SENTENCE_BOUNDARIES:
        pos = truncated.rfind(boundary)
        if pos > best_pos:
            best_pos = pos

    if best_pos > 0:
        return truncated[:best_pos + 1]
    # 找不到句子边界，硬截断
    return truncated

# Markdown 标题正则：行首 1~6 个 # 后跟空格再跟非空字符，避免误匹配 #include / 颜色码 #fff 之类
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def _detect_md_split_level(text: str) -> Optional[int]:
    """扫描全文 markdown 标题，返回切分锚点的层级（1~6）。

    规则：取全文出现的所有标题层级集合 S（去重）：
    - 无标题：返回 None（走数字编号兜底）；
    - len(S) == 1：返回该唯一层级；
    - len(S) >= 2：返回**倒数第二层**（即取最深层级的上一级作为切分锚点，
      使得最深层级及其下方的枚举被收纳到锚点章节内，避免切得太碎）。

    例：
    - 全文 # / ## / ###      -> 返回 2（按 ## 切）
    - 全文 # / ## / ### / ####-> 返回 3（按 ### 切）
    - 全文 ### / ####          -> 返回 3（按 ### 切，雀巢合同形态）
    - 全文仅 #                 -> 返回 1
    """
    levels = sorted({len(m.group(1)) for m in _MD_HEADING_RE.finditer(text or "")})
    if not levels:
        return None
    if len(levels) == 1:
        return levels[0]
    return levels[-2]


def _build_md_anchor_section(level: Optional[int]) -> str:
    """根据探测到的 markdown 切分层级，生成注入 prompt 的硬规则段落。

    无 markdown 标题时返回数字编号兜底规则。
    """
    if level is None:
        return (
            "- 本文档**未检测到 Markdown 标题**，请按原文中的数字/中文编号判断章节边界：\n"
            "  `1. / 2. / 3.`、`一、/ 二、/ 三、`、`Article 1 / Article 2` 等顶级编号必须各自至少有一个 marker；\n"
            "  即使该章节下仅是字母枚举 a/b/c、(i)/(ii)、项目符列表，也必须在该章节标题起始处打 marker，\n"
            "  不能因为「枚举不打 marker」而使整个章节被上一章节吞并。"
        )
    hashes = "#" * level
    deeper = "#" * (level + 1)
    return (
        f"- 本文档的 **Markdown 切分锚点为 `{hashes}`**（{level} 级标题）。\n"
        f"  规则推导：扫描全文出现的标题层级集合 S，若 |S|>=2 则取「倒数第二层」作为切分锚点，\n"
        f"  本次任务计算结果即 `{hashes}`。\n"
        f"- **每个 `{hashes}` 标题起始处必须打且仅打 1 个 marker**，无论其下方是字母枚举 a/b/c、(i)/(ii)、\n"
        f"  项目符列表，还是更深的 `{deeper}` 副标题，整个 `{hashes}` 章节都收纳为同一个 marker，**不再下钻**。\n"
        f"- 比 `{hashes}` 更深的 Markdown 标题（如 `{deeper}`）**不独立打 marker**；\n"
        f"  比 `{hashes}` 更浅的 Markdown 标题（如 `{'#' * (level - 1) if level > 1 else ''}` 等）也不独立打 marker（它们是「目录性」标题，下方会有多个 `{hashes}` 子章节各自承载 marker）。"
    )


META_EXTRACT_PROMPT = """你是合同解析助手。仅从以下合同的首部和尾部文本中提取签约主体信息和关键签约数据。

可选合同类型: {contract_types}

返回 JSON（不要包裹代码块，不要任何额外说明）：
{{"party_a": "甲方简称", "party_b": "乙方简称", "contract_type": "从可选合同类型中选择最匹配的一项", "signing_date": "YYYY-MM-DD", "expiry_date": "YYYY-MM-DD", "total_amount": 数字}}

要求：
1. 简称尽量精简（2~6 字），用于后续检索匹配，不含"有限公司"等通用后缀；
2. 若文档中存在多个甲乙方，取主合同当事人；
3. contract_type 必须从上述「可选合同类型」中选择一项，若无法匹配则选"其他"；
4. 若无法识别，对应字段填空字符串；
5. signing_date 为合同签订日期，expiry_date 为合同到期日期，格式统一为 YYYY-MM-DD；
6. total_amount 为合同总金额（数字，不含货币符号），如无法识别填 null；
7. 若合同未明确约定到期日（如"长期有效"），expiry_date 填空字符串。"""


STRUCTURE_PROMPT = """你是合同解析助手。分析以下合同片段，按顺序识别每个独立条款的起始位置。

返回 JSON（不要包裹代码块，不要任何额外说明）：
{"clause_markers": [{"title": "条款主题", "level": 数字, "marker": "原文中该条款的起始 20~40 字原文"}]}

# 上一窗口末尾条款（跨页上下文）
{last_top_clause}

如果当前片段中的条款属于上述条款的延续内容（同一主条款继续到新页面），请正确设置 level（比上一窗口末尾条款的 level 更深一级）。
例如：上一窗口最后条款为"合作范围-服务内容-软件开发"（level 2），本片段继续列出软件开发下的子项，则子项 level 应为 3。

# 切分颗粒度要求（重要）
marker 应放在**每个有独立编号/标题的条款层级**的起始位置，构建完整的条款树结构。

## 硬规则（优先级高于下述软规则）
{markdown_anchor_section}
- **同级并列章节**之间不能因其中一个被误识别为"上一章节的枚举子项"而跳过 marker，同级并列章节必须各自拥有一个 marker。

## 软规则
- 若文档不含 Markdown 标题（# / ## / ###…），按原文中的数字编号判断：
  - 每个有独立编号的条款层级（如 1. / 2.1 / 2.1.1）都应在该层级起始位置打一个 marker；
  - 更低层级的枚举/字母列表 a/b/c、(i)/(ii) 不独立打 marker；
  - 若某层级标题下仅有子标题而无正文内容，仍应打 marker（作为结构节点）。
- 「软规则」与「硬规则」冲突时，**以硬规则为准**。

## 示例 1：多层数字编号嵌套（无 Markdown 标题）
输入原文：
```
1. 合作期限
本合同期限为 2 年。
2. 合作范围
2.1 服务内容
2.1.1 软件开发
2.1.1.1 后端服务
2.1.1.2 前端页面
2.1.2 技术支持
2.1.2.1 故障响应
2.1.2.2 版本升级
```
应输出的 clause_markers（每个有独立编号的层级都打 marker，title 仅取本层标题、level 为层级深度）：
- {"title": "合作期限", "level": 0, "marker": "1. 合作期限\n本合同期限为 2 年。"}
- {"title": "合作范围", "level": 0, "marker": "2. 合作范围"}
- {"title": "服务内容", "level": 1, "marker": "2.1 服务内容"}
- {"title": "软件开发", "level": 2, "marker": "2.1.1 软件开发\n2.1.1.1 后端服务"}
- {"title": "技术支持", "level": 2, "marker": "2.1.2 技术支持\n2.1.2.1 故障响应"}

注意：不标记 4 级编号（太碎，属于最低层级的枚举子项）；"合作范围"和"服务内容"虽无正文内容，但作为结构节点仍需标记。

## 示例 2：列表型条款（标题 + 字母枚举，双语合同常见结构，最深 Markdown 标题为 ####）
本示例假设本次任务的 Markdown 切分锚点为 `###`（全文出现 ### 与 ####，按「倒数第二层」则取 ###）。
输入原文：
```
### 1. DEFINITIONS
#### 定義
a. "Affiliate" means a company controlled by ...
   "关联公司"系指由一方控制...
b. "Agreement" means this agreement and its schedules ...
   "协议"系指本协议及其附表...
c. "Background Intellectual Property" means ...

### 2. SCOPE OF SERVICE
#### 服务范围
a. The Service Provider shall provide ...
   服务提供者应向公司提供...
b. The Service Provider shall provide regular update ...
```
应输出的 clause_markers（按「硬规则」每个 ### 标题都要有，Markdown 锚点层级为 level 0）：
- {"title": "定义", "level": 0, "marker": "### 1. DEFINITIONS\n#### 定義\na. \"Affiliate\""}
- {"title": "服务范围", "level": 0, "marker": "### 2. SCOPE OF SERVICE\n#### 服务范围\na."}

注意：#### 不独立打 marker（比锚点深一层）；字母枚举 a/b/c 也不独立打 marker；但 ### 1./### 2. 这两个同级标题**必须各自有一个 marker**，不允许 SCOPE OF SERVICE 被 DEFINITIONS 吞并。

# 其他要求
1. marker 必须是片段中**实际存在的连续原文**，长度 20~40 字，逐字复制不要改写、不要更改标点/空白/全半角；
2. 即使片段以未完成的条款结尾（被截断），仍将该条款的 marker 加入列表；
3. 如果片段中完全没有可识别的条款（前言/附件清单等），返回空数组；
4. title 提取规则：仅提取本层标题，不含编号、不含上级前缀；双语合同优先取中文标题，若无中文则用英文标题。例如 1.合作期限 -> 合作期限；2.1.1 软件开发 -> 软件开发。
5. level 为该条款在文档中的层级深度（0=最高层，如 1.；1=第二层，如 2.1；以此类推）；Markdown 文档以锚点层级为 level 0，更深标题为 level 1；
6. 双语合同规范：同一条款同时出现中、英文版本时，**只在该条款的起始位置（以先出现的语言为准）打 1 个 marker**，不要为同一条款的不同语言版本重复打 marker。摘取 marker 原文时优先选择能唯一识别该条款的 20~40 字连续原文（例如含标题编号的那一行、首个枚举项的开头等），避免选取多条款重复出现的公共句式。"""


RECOVER_PROMPT = """你是合同解析助手。以下合同片段中包含一个指定标题的条款，请找到该条款并**逐字复制**其完整原文。

要求：
1. 以纯文本格式直接输出条款原文；
2. 内容必须从合同片段中**逐字复制**，不要改写、总结、翻译或调整标点空白；
3. 范围：从该条款的起始位置到下一条款起始之前（或片段结束）；
4. 如果片段中确实找不到该条款，只输出一个字：无"""


DATA_SUMMARIZE_PROMPT = """你是合同解析助手。以下条款中包含大量具体数据明细（如价格表、人员名单、物料清单、工时明细等）。
请将条款中所有明细数据（表格、列表、数据清单等）替换为一段简短描述（50字以内），说明数据类型、用途及关键汇总信息（如有）。
保留条款中的正文约定不变，仅替换数据部分。

返回 JSON（不要包裹代码块，不要任何额外说明）：
{"content": "处理后的条款文本（明细数据已替换为摘要描述）"}"""


SUMMARY_PROMPT = """你是文档解析助手。基于以下文档的元信息和主要内容，完成两项任务：

1. 判断该文档是否为合同/协议类法律文书。判断标准：
   - 是合同：包含签约主体（甲乙方）、合同标的、权利义务条款、违约责任、争议解决等法律要件；
   - 不是合同：如报价单、产品说明、会议纪要、通知公告、纯数据表格、技术文档等。
2. 用 200~400 字总结文档的核心内容，包括：当事人（如有）、文档类型、核心内容、关键信息。

返回 JSON（不要包裹代码块，不要任何额外说明）：
{"is_contract": true/false, "summary": "文档概要"}

重要：如果文档内容是双语的（中英对照），只输出中文部分作为摘要，不要输出英文或双语对照内容。"""


def _parse_date(date_str: str) -> Optional[datetime.datetime]:
    """解析日期字符串为 datetime，支持多种格式；解析失败返回 None"""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    # 常见日期格式
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _parse_amount(amount_val) -> Optional[Decimal]:
    """解析金额，返回 Decimal；解析失败返回 None"""
    if amount_val is None:
        return None
    try:
        val = Decimal(str(amount_val))
        return val if val >= 0 else None
    except Exception:
        return None


@register_handler("contract")
class ContractSlicingHandler(BaseSlicingHandler):
    """合同文档切片处理器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 收集本次处理过程中的告警/失败信息，随切片 JSON 输出供审核员查看
        self._processing_warnings: list[str] = []

    async def process(
        self,
        raw_content: str,
        pages: Optional[list[DocumentPage]] = None,
    ) -> SlicingResult:
        # 重置 warning 收集器（handler 实例可能被复用）
        self._processing_warnings = []
        logger.debug("[contract] slicing started")

        # 清除控制字符，防止透传到 LLM JSON 输出导致解析失败
        raw_content = _sanitize_text(raw_content)

        # 1. 元信息提取（独立 1 次调用，输入仅前后 N 页）
        meta = await self._extract_meta(raw_content, pages)
        logger.debug("[contract] meta extraction completed")

        # 2. 先做概要+合同判断（1 次调用），若为非合同则跳过条款分析
        summary_result = await self._generate_summary(meta, [], raw_content=raw_content)
        is_contract = summary_result["is_contract"]
        logger.info(f"[contract] is_contract={is_contract}, summary_len={len(summary_result['summary'])}")

        if not is_contract:
            # 非合同文档：只保存摘要 + 正文，不切条款
            logger.debug("[contract] non-contract document, skipping clause analysis")
            result_data: dict = {
                "meta": meta,
                "is_contract": False,
                "summary": summary_result["summary"],
                "body_text": raw_content.strip(),
            }
            if self._processing_warnings:
                result_data["processing_warnings"] = list(self._processing_warnings)
            result = json.dumps(result_data, ensure_ascii=False)
            return SlicingResult(content=result, prompt_used="contract_v2")

        # 3. 合同文档：滑动窗口分析条款结构（N 次调用 → markers 列表）
        markers = await self._analyze_structure(raw_content)
        logger.debug("[contract] structure analysis completed")

        # 4. 按 marker 在原文中定位并切分，定位失败项走 LLM 兜底补取
        clauses = await self._split_by_markers(raw_content, markers)
        if not clauses:
            # 兜底：LLM 未能识别任何条款，整篇作为单一条款
            self._processing_warnings.append("未识别出任何条款，整篇作为单一条款入库")
            clauses = [{"clause_title": None, "content": raw_content.strip()}]

        # 用 level 堆栈组装完整 title（如 "合作范围-服务内容-软件开发"）
        clauses = self._build_full_titles(clauses)

        # 合并同 title 的连续条款：跨窗口边界导致同一条款被切分为多条时，拼接 content
        clauses = self._merge_adjacent_same_title(clauses)

        logger.debug("[contract] clause splitting completed")
        # 5. 明细数据摘要化：将条款中的大段表格/清单数据替换为简短描述
        clauses = await self._summarize_data_in_clauses(clauses)
        logger.debug("[contract] data summarization completed")
        # 统一按顺序编号（从 1 开始，0 留给概要）
        for i, c in enumerate(clauses, start=1):
            c["clause_index"] = i
        logger.debug("[contract] clause numbering completed")
        # 6. 重新生成合同概要（有条款上下文后更准确）
        summary_result = await self._generate_summary(meta, clauses)
        all_clauses = [{
            "clause_index": 0,
            "clause_title": "合同概要",
            "content": summary_result["summary"],
        }] + clauses
        logger.debug("[contract] summary generation completed")
        result_data: dict = {"meta": meta, "is_contract": True, "clauses": all_clauses}
        if self._processing_warnings:
            result_data["processing_warnings"] = list(self._processing_warnings)
            logger.warning(
                "[contract] slicing completed with %d warnings",
                len(self._processing_warnings),
            )
        logger.debug("[contract] slicing completed")
        result = json.dumps(result_data, ensure_ascii=False)
        return SlicingResult(content=result, prompt_used="contract_v2")

    # ---------- 元信息 ----------

    def _build_meta_input(
        self,
        raw_content: str,
        pages: Optional[list[DocumentPage]],
    ) -> str:
        """取前 N 页 + 后 N 页文本作为元信息提取输入；无分页信息时回退取首尾各 4000 字"""
        if pages and len(pages) > META_PAGES_HEAD + META_PAGES_TAIL:
            head = pages[:META_PAGES_HEAD]
            tail = pages[-META_PAGES_TAIL:]
            return (
                "=== 合同首部 ===\n"
                + "\n\n".join((p.content or "") for p in head)
                + "\n\n=== 合同尾部 ===\n"
                + "\n\n".join((p.content or "") for p in tail)
            )
        if pages:
            return "\n\n".join((p.content or "") for p in pages)
        if len(raw_content) <= 8000:
            return raw_content
        return raw_content[:4000] + "\n...\n" + raw_content[-4000:]

    async def _extract_meta(
        self,
        raw_content: str,
        pages: Optional[list[DocumentPage]],
    ) -> dict:
        text = self._build_meta_input(raw_content, pages)
        # 动态查询活跃合同类型，注入 prompt
        contract_types = await self._get_active_contract_type_names()
        prompt = META_EXTRACT_PROMPT.format(contract_types=contract_types)
        try:
            data = await self.call_llm_structured(prompt, text, MetaExtractResponse)
            signing_date = _parse_date(data.signing_date or "")
            expiry_date = _parse_date(data.expiry_date or "")
            total_amount = _parse_amount(data.total_amount)
            return {
                "party_a": data.party_a or "",
                "party_b": data.party_b or "",
                "contract_type": data.contract_type or "其他",
                "signing_date": signing_date.strftime("%Y-%m-%d") if signing_date else "",
                "expiry_date": expiry_date.strftime("%Y-%m-%d") if expiry_date else "",
                "total_amount": str(total_amount) if total_amount is not None else "",
            }
        except Exception as e:
            logger.exception("[contract] meta extraction failed")
            self._processing_warnings.append(f"元信息提取失败，需人工补充: {e}")
            return {
                "party_a": "", "party_b": "", "contract_type": "其他",
                "signing_date": "", "expiry_date": "", "total_amount": "",
            }

    @staticmethod
    async def _get_active_contract_type_names() -> str:
        """查询活跃合同类型名称，拼接为 prompt 可用的枚举字符串"""
        from app.models.contract import ContractType
        types = await ContractType.filter(is_active=True, is_deleted=False).all()
        names = [t.name for t in types if t.name]
        if not names:
            return "其他"
        return "、".join(names) + "、其他"

    # ---------- 滑动窗口结构分析 ----------

    async def _analyze_structure(self, text: str) -> list[dict]:
        """滑动窗口逐段分析，输出全文条款 marker 列表。

        返回项结构：{title, marker, source_chunk_start, source_chunk_end}
        source_chunk_start/end 记录该 marker 由哪个 chunk 识别出，供后续 LLM 兜底使用。

        单窗口调用失败（超时/LLM 异常/重试耗尽）记录到 _processing_warnings，
        强制推进 cursor 不阻塞整体流程。
        """
        cursor = 0
        all_markers: list[dict] = []
        seen_markers: set[str] = set()
        last_top_clause: Optional[str] = None  # 上一窗口最后一个 keep marker 的完整 title

        # 全文预扫一次，确定本任务的 markdown 切分锚点层级（倒数第二层）
        # 在滑动窗口内 LLM 只看 5000 字片段、无法全局推断层级集合，故由代码端将决定后的锚点注入 prompt 作为硬规则。
        md_split_level = _detect_md_split_level(text)
        md_anchor_section = _build_md_anchor_section(md_split_level)
        logger.debug(
            f"[contract] markdown split anchor: level={md_split_level}, "
            f"hashes={'#' * md_split_level if md_split_level else 'N/A'}"
        )

        while cursor < len(text):
            chunk = text[cursor : cursor + WINDOW_SIZE]
            chunk_end = cursor + len(chunk)
            is_last_window = cursor + WINDOW_SIZE >= len(text)

            # 构建 prompt：注入跨页上下文
            context_value = (
                f"上一窗口最后条款：{last_top_clause}"
                if last_top_clause
                else "（无，这是第一个窗口）"
            )
            prompt = (
                STRUCTURE_PROMPT
                .replace("{last_top_clause}", context_value)
                .replace("{markdown_anchor_section}", md_anchor_section)
            )

            try:
                result = await self.call_llm_structured(prompt, chunk, StructureAnalyzeResponse)
                markers = [m.model_dump() for m in result.clause_markers]
            except LLMCallError as e:
                # 重试耗尽后的超时/网络异常
                logger.error(
                    "[contract] structure analyze LLM failed at chunk [%d-%d]: %s",
                    cursor, chunk_end, e,
                )
                self._processing_warnings.append(
                    f"结构分析失败（原文位置 {cursor}-{chunk_end}），该区间条款可能缺失: {e}"
                )
                markers = []
            except Exception as e:  # noqa: BLE001
                # 结构化输出解析异常
                logger.exception("[contract] structure analyze parse failed at cursor=%d", cursor)
                self._processing_warnings.append(
                    f"结构分析返回格式异常（原文位置 {cursor}-{chunk_end}）: {e}"
                )
                markers = []

            if not markers:
                # 当前窗口无 marker（未识别或失败），强制推进
                if is_last_window:
                    break
                cursor += WINDOW_SIZE - MIN_PROGRESS
                continue

            # 保留策略：
            # - 最后一窗：全收；
            # - 其它窗口同时识别 ≥2 个：舍弃最后一个（可能被截断）留给下一窗复识；
            # - 单 marker 场景：LLM 可能漏识别后续章节，若仍丢弃它会造成
            #   后续章节被本章节大面积吞并 -> 必须收下该 marker（seen_markers 会去重）
            if is_last_window or len(markers) >= 2:
                keep = markers if is_last_window else markers[:-1]
            else:
                keep = markers  # 单 marker 场景：不丢弃，避免空转与吞并

            for m in keep:
                self._append_marker(all_markers, seen_markers, m, cursor, chunk_end)

            # 更新跨页上下文：取本轮 keep 列表最后一个 marker 的 title + level
            if keep:
                last_top = keep[-1]
                last_title = (last_top.get("title") or "").strip()
                last_level = last_top.get("level", 0)
                last_top_clause = f"{last_title} (level {last_level})" if last_title else None

            if is_last_window:
                break

            # 推进策略：
            # - 多 marker：以未被收下的 markers[-1] 在 chunk 中的位置作下轮起点；
            # - 单 marker：该 marker 已被收下，不能再以它为锚，否则下轮以同一位置起始会
            #   重复识别同一 marker 造成空转，改为半窗强制推进
            if len(markers) == 1:
                cursor += WINDOW_SIZE - MIN_PROGRESS
                continue

            last_marker = (markers[-1].get("marker") or "").strip()
            offset = chunk.find(last_marker) if last_marker else -1
            if offset < 0:
                cursor += WINDOW_SIZE - MIN_PROGRESS
                continue

            new_cursor = cursor + offset
            cursor = new_cursor if new_cursor > cursor else cursor + MIN_PROGRESS

        return all_markers

    @staticmethod
    def _append_marker(
        all_markers: list[dict],
        seen: set[str],
        m: dict,
        chunk_start: int,
        chunk_end: int,
    ) -> None:
        """按 marker 文本跨窗口去重后追加，记录来源 chunk 范围"""
        marker_text = (m.get("marker") or "").strip()
        if not marker_text or marker_text in seen:
            return
        seen.add(marker_text)
        all_markers.append({
            "title": (m.get("title") or "").strip() or None,
            "marker": marker_text,
            "source_chunk_start": chunk_start,
            "source_chunk_end": chunk_end,
        })

    # ---------- 原文定位与切分（含 LLM 兜底）----------

    @staticmethod
    def _locate_marker(text: str, marker: str) -> int:
        """多层定位：返回 marker 在 text 中的位置，未找到返回 -1"""
        if not marker:
            return -1
        # ① 精确匹配
        pos = text.find(marker)
        if pos >= 0:
            return pos
        # ② 截断重试（取 marker 前 15 字）
        if len(marker) > 15:
            pos = text.find(marker[:15])
            if pos >= 0:
                return pos
        return -1

    async def _split_by_markers(self, text: str, markers: list[dict]) -> list[dict]:
        """按 marker 顺序切分原文，定位失败项走 LLM 兜底补取；均失败时保留占位供人工补充"""
        if not markers:
            return []

        # 第一遍：在原文中定位
        located_pos: dict[int, int] = {}   # idx_in_markers → pos_in_text
        fallback_indices: list[int] = []   # 定位失败的 markers
        for i, m in enumerate(markers):
            pos = self._locate_marker(text, m["marker"])
            if pos >= 0:
                located_pos[i] = pos
            else:
                fallback_indices.append(i)

        # 计算定位成功项的切分范围（按位置排序，相邻定位点为边界）
        sorted_located = sorted(located_pos.items(), key=lambda kv: kv[1])
        located_content: dict[int, str] = {}
        for k, (idx, pos) in enumerate(sorted_located):
            end = sorted_located[k + 1][1] if k + 1 < len(sorted_located) else len(text)
            located_content[idx] = text[pos:end].strip()

        # 第二遍：定位失败的项走 LLM 兜底
        fallback_content: dict[int, str] = {}
        # if fallback_indices:
            # logger.info(f"[contract] {len(fallback_indices)} markers need LLM recovery")
        for idx in fallback_indices:
            m = markers[idx]
            chunk = text[m["source_chunk_start"] : m["source_chunk_end"]]
            recovered = await self._recover_clause(chunk, m["title"], m["marker"])
            if recovered:
                fallback_content[idx] = recovered
            else:
                logger.warning(
                    f"[contract] marker recovery failed: title={m.get('title')}, marker={m['marker'][:30]}"
                )

        # 按原始 markers 顺序拼装结果；定位与兜底都失败时保留占位供人工补充
        clauses: list[dict] = []
        for i, m in enumerate(markers):
            content = located_content.get(i) or fallback_content.get(i)
            if not content:
                marker_preview = (m.get("marker") or "")[:30]
                title_preview = m.get("title") or "(未知标题)"
                self._processing_warnings.append(
                    f"条款「{title_preview}」定位与 LLM 兜底均失败（marker={marker_preview}...），需人工补充原文"
                )
                content = (
                    f"⚠️ 该条款解析失败，请人工补充原文。\n"
                    f"（原始起始标记：{marker_preview}...）"
                )
            clauses.append({"clause_title": m["title"], "level": m.get("level", 0), "content": content})
        return clauses

    @staticmethod
    def _build_full_titles(clauses: list[dict]) -> list[dict]:
        """用 level 堆栈将 LLM 输出的本层标题组装为完整路径。

        LLM 只输出本层标题（如"软件开发"）+ level（如 2），
        此方法按 level 维护一个堆栈，逐级拼接完整 title（如"合作范围-服务内容-软件开发"）。

        规则：
        - level 0 入栈，清空更深层级
        - level N 入栈时，弹出所有 level >= N 的栈顶
        - 最终 title = 栈中所有 title 用 "-" 拼接
        """
        if not clauses:
            return clauses

        level_stack: list[tuple[int, str]] = []
        for clause in clauses:
            local_title = (clause.get("clause_title") or "").strip()
            level = clause.get("level", 0)

            if not local_title:
                # title 为空时保留原样（如兜底 clause）
                continue

            # 弹出 >= 当前 level 的栈顶（同级或更深层级）
            while level_stack and level_stack[-1][0] >= level:
                level_stack.pop()

            level_stack.append((level, local_title))

            full_path = "-".join(t for _, t in level_stack)
            clause["clause_title"] = full_path

        return clauses

    @staticmethod
    def _merge_adjacent_same_title(clauses: list[dict]) -> list[dict]:
        """合并连续同 title 的条款。

        跨窗口边界时，同一条款可能被 LLM 识别为两条（content 被截断为前后两段），
        此处将相邻且 title 相同的条款拼接 content，保留第一条。
        """
        if not clauses:
            return clauses

        merged: list[dict] = []
        for c in clauses:
            title = (c.get("clause_title") or "").strip()
            if merged and title and title == ((merged[-1].get("clause_title") or "").strip()):
                # 同 title 连续出现：拼接 content
                merged[-1]["content"] = (
                    (merged[-1]["content"] or "") + "\n\n" + (c["content"] or "")
                ).strip()
                logger.debug(
                    f"[contract] merged adjacent same-title clause: title={title}",
                )
            else:
                merged.append(c)

        if len(merged) < len(clauses):
            logger.info(
                f"[contract] merged {len(clauses) - len(merged)} duplicate clauses into {len(merged)}"
            )
        return merged

    async def _recover_clause(
        self,
        chunk: str,
        title: Optional[str],
        original_marker: str,
    ) -> Optional[str]:
        """LLM 兜底：从来源 chunk 中补取该条款的完整原文。

        输入超过 MAX_INPUT_CHARS 时在完整语句边界截断，防止 LLM 输出报错。
        """
        # 超长 chunk 在完整语句边界截断
        original_len = len(chunk)
        chunk = _truncate_at_sentence_boundary(chunk, MAX_INPUT_CHARS)
        if len(chunk) < original_len:
            logger.info(
                f"[contract] recover_clause input truncated: "
                f"title={title}, {original_len} -> {len(chunk)} chars"
            )

        user_input = (
            f"# 条款标题\n{title or ''}\n\n"
            f"# 原始起始标记（仅供参考，可能存在偏差）\n{original_marker}\n\n"
            f"# 合同片段\n{chunk}"
        )
        try:
            content = (await self.call_llm(RECOVER_PROMPT, user_input)).strip()
        except Exception:
            logger.exception(f"[contract] recover_clause LLM call failed: title={title}")
            return None
        if not content or content == "无":
            return None
        # 二次校验：返回的 content 前 20 字必须能在 chunk 中定位，防止 LLM 改写
        if content[:20] not in chunk:
            return None
        return content

    # ---------- 明细数据摘要化 ----------

    # 检测明细数据特征的正则：markdown 表格、有序/无序列表、多行连续枚举等
    _DATA_PATTERN = re.compile(
        r'(?:^\s*\|.*\|)'          # markdown 表格行
        r'|(?:^\s*[-*]\s+.+)'      # 无序列表项
        r'|(?:^\s*\d+[.)\s].+)'    # 有序列表项（数字开头）
        r'|(?:^\s*[a-zA-Z][.)]\s+.+)',  # 字母列表项
        re.MULTILINE,
    )

    async def _summarize_data_in_clauses(self, clauses: list[dict]) -> list[dict]:
        """对含大段明细数据的条款调用 LLM，将表格/清单替换为简短摘要描述。

        仅当条款内容 ≥ 800 字且包含列表/表格特征时才调用 LLM，否则保持原内容不变。
        输入超过 MAX_INPUT_CHARS 时在完整语句边界截断，防止 LLM 输出报错。
        """
        for clause in clauses:
            content = clause.get("content") or ""
            if len(content) < 800:
                continue
            if not self._DATA_PATTERN.search(content):
                continue

            # 超长输入在完整语句边界截断，避免 LLM 输出报错
            content = _truncate_at_sentence_boundary(content, MAX_INPUT_CHARS)

            try:
                result = await self.call_llm_structured(DATA_SUMMARIZE_PROMPT, content, ContentResponse)
                new_content = (result.content or "").strip()
                if new_content and len(new_content) < len(content):
                    clause["content"] = new_content
                    logger.debug(
                        f"[contract] data summarized: clause=%s, {len(content)} -> {len(new_content)} chars"
                    )
            except Exception as e:
                logger.warning(
                    f"[contract] data summarize failed for clause={clause.get('clause_title')}: {e}"
                )
                self._processing_warnings.append(
                    f"条款「{clause.get('clause_title') or ''}」明细数据摘要失败，保留原文: {e}"
                )
        return clauses

        

    # ---------- 概要 ----------

    async def _generate_summary(self, meta: dict, clauses: list[dict], raw_content: str = "") -> dict:
        """生成文档概要 + 判断是否为合同。

        Returns:
            {"summary": str, "is_contract": bool}
        """
        if clauses:
            head_clauses_text = "\n\n".join(
                f"[{c.get('clause_title') or ''}]\n{c['content'][:500]}"
                for c in clauses[:SUMMARY_CONTEXT_CLAUSES]
            )
        else:
            # 取原文前 MAX_INPUT_CHARS 字，在完整语句边界截断
            head_clauses_text = _truncate_at_sentence_boundary(raw_content, MAX_INPUT_CHARS) if raw_content else "(无内容)"

        user_input = (
            f"文档元信息：{json.dumps(meta, ensure_ascii=False, default=str)}\n\n"
            f"文档内容：\n{head_clauses_text}"
        )
        try:
            result = await self.call_llm_structured(SUMMARY_PROMPT, user_input, SummaryResponse)
            return {"summary": (result.summary or "").strip(), "is_contract": result.is_contract}
        except Exception as e:
            logger.exception("[contract] summary generation failed")
            self._processing_warnings.append(f"文档概要生成失败，需人工补充: {e}")
            return {"summary": "", "is_contract": True}

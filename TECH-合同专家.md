# 合同专家 技术设计文档

## 一、改动概览

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/models/enums.py` | 修改 | `DocumentTypeCode` 新增 `CONTRACT` |
| `app/schemas/vector_metadata.py` | 修改 | 更新 `ContractMetadata` 字段定义 |
| `app/services/structuring/contract.py` | 新建 | 合同结构化处理器（拆条款 + 提取元信息 + 生成概要） |
| `app/services/structuring/__init__.py` | 修改 | 导入合同处理器以触发注册 |
| `app/services/document_pipeline.py` | 修改 | `vectorize_document` 新增 contract 向量化分支 |
| `app/agents/tools/kd_vector_query_tool.py` | 修改 | `METADATA_KEEP_KEYS` 补充合同专用字段 |
| `migrations/models/` | 新建 | 枚举扩展迁移文件 |

---

## 二、数据模型变更

### 2.1 DocumentTypeCode 枚举

**文件**：`app/models/enums.py`

```python
class DocumentTypeCode(StrEnum):
    FEISHU_DOC = "feishu_doc"
    PPT = "ppt"
    CONTRACT = "contract"          # 新增

    @classmethod
    def get_display_map(cls) -> dict[str, str]:
        return {
            cls.FEISHU_DOC: "飞书文档",
            cls.PPT: "PPT文档",
            cls.CONTRACT: "合同",  # 新增
        }

    @classmethod
    def get_paged_types(cls) -> set[str]:
        return {cls.PPT}           # contract 不是分页类型，不变
```

### 2.2 ContractMetadata

**文件**：`app/schemas/vector_metadata.py`

```python
class ContractMetadata(BaseVectorMetadata):
    """合同文档 Metadata"""

    # 合同级元信息（必填，由 LLM 在结构化阶段提取）
    party_a: str = Field(..., description="甲方名称（简称）")
    party_b: str = Field(..., description="乙方名称（简称）")
    contract_type: str = Field(..., description="合同类型: 采购/服务/技术合作/框架协议/其他")

    # 条款级元信息
    clause_index: int = Field(..., description="条款序号，第0条为概要")
    clause_title: Optional[str] = Field(None, description="条款标题，如'违约责任'")
```

### 2.3 数据库迁移

`DocumentTypeCode` 是 `CharEnumField`，Tortoise ORM 实际存储为 varchar，枚举新增值无需 ALTER，运行 `aerich.exe upgrade` 确认迁移状态即可。

---

## 三、合同结构化处理器

### 3.1 设计说明

合同向量化前需要完成三步结构化预处理，**三个 LLM 任务彼此独立**，避免 prompt 混合导致任务边界模糊：

1. **元信息提取**（独立调用 1 次）：取合同前 2 页 + 后 2 页的文本，由 LLM 提取 `party_a / party_b / contract_type`。原因：合同元信息集中在首页（甲乙方介绍）和尾页（签字盖章），无需读取正文。
2. **条款结构分析**（滑动窗口 N 次 + 必要时兜底 LLM 调用）：每轮取 5000 字，由 LLM 输出该片段中的条款边界 `clause_markers`（仅 `title` 与原文起始 `marker`，不输出正文）。代码根据 marker 在原文中 `find()` 定位并切分；若 marker 出现幻觉无法定位，则把该 marker 所属的 chunk 重新送入 LLM，让 LLM 返回该条款的完整原文作为兜底。**选择该方案的原因**：合同编号格式多样（`第X条 / 一、 / 1.1 / Article X`），固定正则覆盖率低；让 LLM 只输出短小的 marker 而非全文，每轮 LLM 输出 token 从“条款全文”压缩到“每条 ≈30 字”，同时代码从原文切出的内容天然与原文一致，不会发生 LLM 隐式改写。
3. **概要生成**（独立调用 1 次）：基于元信息 + 前若干条款生成合同概要，作为 `clause_index=0` 的“第0条”入库，与普通条款共用 schema。

结构化结果以 JSON 格式保存到 `StructuredResult.structured_content`，供向量化阶段解析。

**调用次数估算（25000 字合同）**：元信息 1 次 + 滑动窗口约 5~6 次 + 概要 1 次 ≈ **7~8 次 LLM 调用**；marker 定位失败时每项额外 1 次兜底调用（实测幻觉率低，一般不会触发）。

### 3.2 structured_content 格式

```json
{
  "meta": {
    "party_a": "A公司",
    "party_b": "B公司",
    "contract_type": "采购"
  },
  "clauses": [
    {
      "clause_index": 0,
      "clause_title": "合同概要",
      "content": "本合同约定A公司向B公司采购XX设备，总金额120万元..."
    },
    {
      "clause_index": 1,
      "clause_title": "定义",
      "content": "第一条 定义\n1.1 本合同中的'设备'指..."
    },
    {
      "clause_index": 8,
      "clause_title": "违约责任",
      "content": "第八条 违约责任\n8.1 任何一方未按本合同约定履行义务的..."
    }
  ]
}
```

### 3.3 已知处理边界

**跨页内容**：合同 PDF/DOCX 经文档转换器处理后，`pages_to_markdown()` 将所有页面拼接为完整字符串存入 `doc.content`，滑动窗口在合并后的完整内容上执行，**不存在条款被截断在不同页的问题**。但换页处会残留分页分隔符（`---`），可能干扰 LLM 的 marker 提取。建议在审核阶段清理，或在送入 LLM 前做一次 `re.sub(r'\n---+\n', '\n', text)` 预处理。

**长合同处理（滑动窗口策略）**：单次 LLM 调用受 context window 限制，超长合同（如 30+ 页）需要分窗口处理。策略如下：
- 每次取 `cursor` 起 5000 字送入 LLM，LLM 返回该窗口内的 `clause_markers`（每项含 `title` + 原文起始 `marker`）；
- 记录每个 marker 的来源窗口范围（`source_chunk_start / source_chunk_end`），供后续兜底使用；
- **保留除最后一个外的所有 markers**——最后一个 marker 位置后的内容可能未读完；
- 下一轮 `cursor` 推进到“最后一个 marker 在当前 chunk 中的位置”，最后一个 marker 在新一轮中重新识别并能看到其后续完整内容；
- 进入最后一个窗口时（`cursor + 5000 >= 总长度`），所有 markers 全部收下；
- 兜底推进：当前窗口未识别出任何 marker（前言/附件清单等无条款内容），或最后一个 marker 在 chunk 中 `find()` 失败时，强制 `cursor += 4500` 推进。

**marker 定位多层兜底**：全文切分阶段逐个尝试在原文中定位 marker，按顺序尝试：
1. **精确匹配**：`text.find(marker)`；
2. **截断重试**：取 marker 前 15 个字符重试 find（应对 marker 尾部有轻微漂移）；
3. **LLM 兜底补取**：前两步均失败时，将该 marker 所属的 chunk（与其 title、原 marker）重新送入 LLM，让 LLM 从 chunk 中**逐字复制**该条款的完整原文作为 content。返回后二次校验：content 前 20 字必须能在 chunk 中 find 到，否则视为兜底失败，丢弃该条并警告。

**跨窗口去重**：使用 `marker` 文本作为去重键，同一 marker 在两轮中重复出现仅保留一份。

### 3.4 实现代码

**新建文件**：`app/services/structuring/contract.py`

```python
import json
import re
from typing import Optional

from app.schemas.documents import DocumentPage

from . import StructuringResult, register_handler
from .base import BaseStructuringHandler


# 滑动窗口配置
WINDOW_SIZE = 5000          # 每轮送入 LLM 的字符数
MIN_PROGRESS = 500          # 兜底推进字符数（防死循环）
META_PAGES_HEAD = 2         # 元信息提取：取前 N 页
META_PAGES_TAIL = 2         # 元信息提取：取后 N 页
SUMMARY_CONTEXT_CLAUSES = 5 # 概要生成：取前 N 条作为上下文

META_EXTRACT_PROMPT = """你是合同解析助手。仅从以下合同的首部和尾部文本中提取签约主体信息。

返回 JSON（不要包裹代码块，不要任何额外说明）：
{"party_a": "甲方简称", "party_b": "乙方简称", "contract_type": "采购|服务|技术合作|框架协议|劳动|租赁|其他"}

要求：
1. 简称尽量精简（2~6 字），用于后续检索匹配，不含"有限公司"等通用后缀；
2. 若文档中存在多个甲乙方，取主合同当事人；
3. 若无法识别，对应字段填空字符串。"""

STRUCTURE_PROMPT = """你是合同解析助手。分析以下合同片段，按顺序识别每个独立条款的起始位置。

返回 JSON（不要包裹代码块，不要任何额外说明）：
{"clause_markers": [{"title": "条款主题", "marker": "原文中该条款的起始 20~40 字原文"}]}

# 切分颗粒度要求（重要）
marker 应放在**含有具体内容的最低条款层级**的起始位置，避免过粗（一整个章节作为一个 marker）也避免过碎（每行子项都加 marker）。

判定规则：
- 若条款无子项（如“1. 合作期限：本合同期限为 2 年。”），在该条起始位置打一个 marker；
- 若条款有多层嵌套结构，仅在**含具体内容的最低层级**的起始位置打 marker；更高层级（纯嵌套结构）不独立打 marker，更低层级的枚举/子条款也不独立打 marker。

示例：
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
应输出的 clause_markers：
- {"title": "合作期限", "marker": "1. 合作期限\n本合同期限为 2 年。"}
- {"title": "软件开发", "marker": "2.1.1 软件开发\n2.1.1.1 后端服务"}
- {"title": "技术支持", "marker": "2.1.2 技术支持\n2.1.2.1 故障响应"}

注意：“2. 合作范围”与“2.1 服务内容”不独立打 marker（太粗）；4 级编号也不打 marker（太碎）。

# 其他要求
1. marker 必须是片段中**实际存在的连续原文**，長度 20~40 字，逐字复制不要改写、不要跟改标点/空白/全半角；
2. 即使片段以未完成的条款结尾（被截断），仍将该条款的 marker 加入列表；
3. 如果片段中完全没有可识别的条款（前言/附件清单等），返回空数组；
4. title 取条款的核心主题（如“违约责任”、“付款方式”），不含“第X条”等编号前缀。"""

RECOVER_PROMPT = """你是合同解析助手。以下合同片段中包含一个指定标题的条款，请找到该条款并**逐字复制**其完整原文。

返回 JSON（不要包裹代码块，不要任何额外说明）：
{"content": "条款完整原文"}

要求：
1. content 必须从合同片段中**逐字复制**，不要改写、总结、翻译或调整标点空白；
2. 范围：从该条款的起始位置到下一条款起始之前（或片段结束）；
3. 如果片段中确实找不到该条款，content 字段填空字符串。"""

SUMMARY_PROMPT = """你是合同解析助手。基于以下合同元信息和主要条款，用 200~400 字总结合同的核心约定，
包括：当事人、合同类型、核心标的、关键义务、主要金额（如有）、争议解决方式。
直接输出概要正文，不要标题和前置说明。"""


def _extract_json(raw: str) -> str:
    """从 LLM 输出中剥离代码块包裹"""
    raw = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()


@register_handler("contract")
class ContractStructuringHandler(BaseStructuringHandler):
    """合同文档结构化处理器"""

    async def process(
        self,
        raw_content: str,
        pages: Optional[list[DocumentPage]] = None,
    ) -> StructuringResult:
        # 1. 元信息提取（独立 1 次调用，输入仅前后 N 页）
        meta = await self._extract_meta(raw_content, pages)

        # 2. 滑动窗口分析条款结构（N 次调用 → markers 列表）
        markers = await self._analyze_structure(raw_content)

        # 3. 按 marker 在原文中定位并切分，定位失败项走 LLM 兜底补取
        clauses = await self._split_by_markers(raw_content, markers)
        if not clauses:
            # 兜底：LLM 未能识别任何条款，整篇作为单一条款
            clauses = [{"clause_title": None, "content": raw_content.strip()}]

        # 统一按顺序编号（从 1 开始，0 留给概要）
        for i, c in enumerate(clauses, start=1):
            c["clause_index"] = i

        # 4. 生成合同概要（独立 1 次调用，作为第 0 条入库）
        summary = await self._generate_summary(meta, clauses)
        all_clauses = [{
            "clause_index": 0,
            "clause_title": "合同概要",
            "content": summary,
        }] + clauses

        result = json.dumps({"meta": meta, "clauses": all_clauses}, ensure_ascii=False)
        return StructuringResult(content=result, prompt_used="contract_v2")

    # ---------- 元信息 ----------

    def _build_meta_input(self, raw_content: str, pages: Optional[list[DocumentPage]]) -> str:
        """取前 N 页 + 后 N 页文本作为元信息提取输入；无分页信息时回退取首尾各 4000 字"""
        if pages and len(pages) > META_PAGES_HEAD + META_PAGES_TAIL:
            head = pages[:META_PAGES_HEAD]
            tail = pages[-META_PAGES_TAIL:]
            return (
                "=== 合同首部 ===\n"
                + "\n\n".join(p.content for p in head)
                + "\n\n=== 合同尾部 ===\n"
                + "\n\n".join(p.content for p in tail)
            )
        if pages:
            return "\n\n".join(p.content for p in pages)
        if len(raw_content) <= 8000:
            return raw_content
        return raw_content[:4000] + "\n...\n" + raw_content[-4000:]

    async def _extract_meta(
        self,
        raw_content: str,
        pages: Optional[list[DocumentPage]],
    ) -> dict:
        text = self._build_meta_input(raw_content, pages)
        try:
            raw = await self.call_llm(META_EXTRACT_PROMPT, text)
            data = json.loads(_extract_json(raw))
            return {
                "party_a": data.get("party_a", "") or "",
                "party_b": data.get("party_b", "") or "",
                "contract_type": data.get("contract_type", "其他") or "其他",
            }
        except Exception:
            return {"party_a": "", "party_b": "", "contract_type": "其他"}

    # ---------- 滑动窗口结构分析 ----------

    async def _analyze_structure(self, text: str) -> list[dict]:
        """滑动窗口逐段分析，输出全文条款 marker 列表。

        返回项结构：{title, marker, source_chunk_start, source_chunk_end}
        source_chunk_start/end 记录该 marker 由哪个 chunk 识别出，供后续 LLM 兜底使用。
        """
        cursor = 0
        all_markers: list[dict] = []
        seen_markers: set[str] = set()

        while cursor < len(text):
            chunk = text[cursor : cursor + WINDOW_SIZE]
            chunk_end = cursor + len(chunk)
            is_last_window = cursor + WINDOW_SIZE >= len(text)

            try:
                raw = await self.call_llm(STRUCTURE_PROMPT, chunk)
                result = json.loads(_extract_json(raw))
                markers = result.get("clause_markers", []) or []
            except Exception:
                markers = []

            if not markers:
                # 当前窗口无 marker，强制推进
                cursor += WINDOW_SIZE - MIN_PROGRESS
                continue

            # 保留的 markers：最后一窗全收，非最后窗保留前 N-1 个
            keep = markers if is_last_window else markers[:-1]
            for m in keep:
                self._append_marker(all_markers, seen_markers, m, cursor, chunk_end)

            if is_last_window:
                break

            # 用最后一个 marker 在 chunk 的位置作为下一轮起点
            last_marker = markers[-1].get("marker", "")
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
        """按 marker 顺序切分原文，定位失败项走 LLM 兜底补取"""
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
        for idx in fallback_indices:
            m = markers[idx]
            chunk = text[m["source_chunk_start"] : m["source_chunk_end"]]
            recovered = await self._recover_clause(chunk, m["title"], m["marker"])
            if recovered:
                fallback_content[idx] = recovered

        # 按原始 markers 顺序拼装结果
        clauses: list[dict] = []
        for i, m in enumerate(markers):
            content = located_content.get(i) or fallback_content.get(i)
            if not content:
                continue  # 定位与兜底都失败，丢弃该条
            clauses.append({"clause_title": m["title"], "content": content})
        return clauses

    async def _recover_clause(
        self,
        chunk: str,
        title: Optional[str],
        original_marker: str,
    ) -> Optional[str]:
        """LLM 兜底：从来源 chunk 中补取该条款的完整原文"""
        user_input = (
            f"# 条款标题\n{title or ''}\n\n"
            f"# 原始起始标记（仅供参考，可能存在偏差）\n{original_marker}\n\n"
            f"# 合同片段\n{chunk}"
        )
        try:
            raw = await self.call_llm(RECOVER_PROMPT, user_input)
            data = json.loads(_extract_json(raw))
            content = (data.get("content") or "").strip()
        except Exception:
            return None
        if not content:
            return None
        # 二次校验：返回的 content 前 20 字必须能在 chunk 中定位，防止 LLM 改写
        if content[:20] not in chunk:
            return None
        return content

    # ---------- 概要 ----------

    async def _generate_summary(self, meta: dict, clauses: list[dict]) -> str:
        head_clauses_text = "\n\n".join(
            f"[{c.get('clause_title') or ''}]\n{c['content'][:500]}"
            for c in clauses[:SUMMARY_CONTEXT_CLAUSES]
        )
        user_input = (
            f"合同元信息：{json.dumps(meta, ensure_ascii=False)}\n\n"
            f"主要条款：\n{head_clauses_text}"
        )
        try:
            return (await self.call_llm(SUMMARY_PROMPT, user_input)).strip()
        except Exception:
            return ""
```

### 3.5 注册处理器

**修改文件**：`app/services/structuring/__init__.py`

```python
# 导入处理器以触发注册
from . import meeting_notes, partner_profile, contract  # noqa: E402, F401
```

---

## 四、向量化入库

### 4.1 document_pipeline.py 新增 contract 分支

**修改文件**：`app/services/document_pipeline.py`

在 `vectorize_document` 方法中，`is_paged_type` 判断之后新增 contract 分支：

```python
async def vectorize_document(self, doc_id: int):
    doc = await Document.get(id=doc_id)
    ...
    kb = await KnowledgeBase.get(id=doc.knowledge_base_id)

    if DocumentTypeCode.is_paged_type(doc.doc_type_code):
        await self._vectorize_from_pages(doc, kb)
    elif doc.doc_type_code == DocumentTypeCode.CONTRACT:      # 新增
        await self._vectorize_contract(doc, kb)               # 新增
    else:
        # 原有非分页文档逻辑...
```

### 4.2 _vectorize_contract 方法

```python
async def _vectorize_contract(self, doc: Document, kb: KnowledgeBase):
    """合同文档向量化：解析 structured_content → 逐条款入库"""
    import json
    from llama_index.core.schema import Document as LlamaDocument
    from app.schemas.vector_metadata import ContractMetadata

    # 优先使用审核员编辑后的内容
    structured_json = None
    reviews = await review_controller.get_by_document(doc.id)
    if reviews and reviews[0].edited_content:
        structured_json = reviews[0].edited_content
    else:
        structured = await StructuredResult.filter(document_id=doc.id).first()
        if structured:
            structured_json = structured.structured_content

    if not structured_json:
        raise ValueError("合同文档缺少结构化内容，请先完成审核")

    data = json.loads(structured_json)
    meta = data.get("meta", {})
    clauses = data.get("clauses", [])

    llama_docs = []
    for clause in clauses:
        # 构建 text 头部
        header = (
            f"[合同: {doc.title} | "
            f"甲方: {meta.get('party_a', '')} | "
            f"乙方: {meta.get('party_b', '')} | "
            f"类型: {meta.get('contract_type', '')}]"
        )
        text = f"{header}\n{clause['content']}"

        clause_meta = ContractMetadata(
            title=doc.title,
            source_type=doc.source_type,
            knowledge_base_id=str(kb.id),
            doc_id=str(doc.id),
            doc_type_code=doc.doc_type_code,
            party_a=meta.get("party_a", ""),
            party_b=meta.get("party_b", ""),
            contract_type=meta.get("contract_type", "其他"),
            clause_index=clause["clause_index"],
            clause_title=clause.get("clause_title"),
        )
        llama_docs.append(
            LlamaDocument(
                text=text,
                metadata=clause_meta.to_dict(),
                doc_id=f"contract_{doc.id}_clause_{clause['clause_index']}",
            )
        )

    if not llama_docs:
        raise ValueError("合同解析后无有效条款")

    from llama_index.core.ingestion import IngestionPipeline
    from app.services.llm_builder import build_embed_model
    from app.models.rag import LLMProviderConfig

    embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
    embed_model = build_embed_model(embedding_config)

    pipeline = IngestionPipeline(
        transformations=[embed_model],           # 合同已按条款切好，不再走 NodeParser
        vector_store=rag_service._vector_store,
    )
    await pipeline.arun(documents=llama_docs)
    logger.info(f"Contract vectorized: doc_id={doc.id}, clauses={len(llama_docs)}")
```

> **注意**：合同文档在结构化阶段已完成条款级切分，向量化时直接用 `embed_model` 生成向量，**不经过** `MarkdownNodeParser`，避免二次切分破坏条款完整性。

---

## 五、查询工具配置

### 5.1 METADATA_KEEP_KEYS 扩展

**修改文件**：`app/agents/tools/kd_vector_query_tool.py`

```python
METADATA_KEEP_KEYS = [
    "doc_id", "page_id", "page_number", "doc_type_code",
    "screenshot_url", "is_context_expansion",
    # 合同专用字段
    "party_a", "party_b", "contract_type",
    "clause_index", "clause_title",
]
```

### 5.2 合同知识库参数配置

创建合同知识库时，以下参数直接影响召回质量：

| 参数 | 推荐值 | 说明 |
|------|-------|------|
| `context_chunks_window` | `1` | 命中条款时自动带出前后各1条，弥补条款间引用 |
| `similarity_top_k` | `8` | 合同条款短，适当提高数量 |
| `similarity_threshold` | `0.45` | 合同用词较正式，阈值可略低于默认值 |
| `chunk_mode` | `sentence`（默认） | 合同已在结构化阶段切好，此配置不影响 contract 类型 |

---

## 六、数据流总览

```
上传合同 URL
    │
    ▼
process_document()
    ├─ 文档内容提取（URL 抓取 / 文件转换 → pages + 完整 markdown）
    ├─ doc_type_code == "contract" → ContractStructuringHandler.process()
    │       ├─ ① LLM 元信息提取（输入：前2页+后2页 → party_a/party_b/contract_type）
    │       ├─ ② LLM 滑动窗口结构分析（5000字/轮，N轮 → clause_markers + 来源 chunk）
    │       │     ├─ 代码多层定位：精确find → 截断前15字重试
    │       │     └─ 定位失败项→ LLM 兜底调用：重送来源chunk让LLM返回该条完整原文
    │       └─ ③ LLM 概要生成（输入：meta + 前5条 → 第0条概要）
    │       → 保存到 StructuredResult.structured_content（JSON：meta + clauses）
    └─ 状态 → PENDING_REVIEW

审核（人工）
    └─ 可在 edited_content 中修正 JSON（甲乙方/条款内容/概要）
    → 审核通过 → 状态 APPROVED

vectorize_document()
    └─ doc_type_code == "contract" → _vectorize_contract()
            ├─ 解析 structured_content JSON
            ├─ 逐条款构建 [合同标识头部] + 条款正文
            ├─ ContractMetadata 校验
            └─ 直接 embed → PGVectorStore（不经过 NodeParser）
            → 状态 COMPLETED

用户提问
    └─ Agent → kd_vector_query_tool
            ├─ 向量检索 top_k 条款（命中条款标题/正文 或 第0条概要）
            ├─ ContextExpansionPostProcessor（context_chunks_window=1）
            └─ 返回条款原文 + metadata（含 party_a/b/type/clause_title）
```

---

## 七、待实现项

以下功能在本期实现中暂未覆盖，后续按需补充：

1. **前端合同元信息展示**：审核页面展示结构化 JSON 中的 meta 字段，便于人工核对甲乙方信息。
2. **滑动窗口指标观测**：记录每份合同的窗口轮次、marker 幻觉次数、强制推进次数，便于评估 LLM 切分稳定性。
3. **向量库中的合同删除**：文档删除时需同步清理向量库中所有 `doc_id` 对应的节点（现有逻辑同此）。

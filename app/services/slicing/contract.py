"""合同文档切片处理器

合同向量化前的三步切片预处理（三个 LLM 任务彼此独立，避免 prompt 混合）：

1. 元信息提取（独立 1 次调用）：取合同前 N 页 + 后 N 页的文本，提取 party_a / party_b / contract_type；
2. 条款结构分析（滑动窗口 N 次 + 必要时兜底 LLM 调用）：每轮 5000 字，LLM 仅输出 marker，
   代码 find() 切分；定位失败的 marker 把所属 chunk 再送 LLM 让其逐字复制完整原文作为兜底；
3. 概要生成（独立 1 次调用）：基于元信息 + 前若干条款生成合同概要，作为 clause_index=0 入库。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from app.log import logger
from app.models.rag import DocumentPage

from . import SlicingResult, register_handler
from .base import BaseSlicingHandler, LLMCallError


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
- 若条款无子项（如"1. 合作期限：本合同期限为 2 年。"），在该条起始位置打一个 marker；
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
- {"title": "合作期限", "marker": "1. 合作期限\\n本合同期限为 2 年。"}
- {"title": "软件开发", "marker": "2.1.1 软件开发\\n2.1.1.1 后端服务"}
- {"title": "技术支持", "marker": "2.1.2 技术支持\\n2.1.2.1 故障响应"}

注意："2. 合作范围"与"2.1 服务内容"不独立打 marker（太粗）；4 级编号也不打 marker（太碎）。

# 其他要求
1. marker 必须是片段中**实际存在的连续原文**，长度 20~40 字，逐字复制不要改写、不要更改标点/空白/全半角；
2. 即使片段以未完成的条款结尾（被截断），仍将该条款的 marker 加入列表；
3. 如果片段中完全没有可识别的条款（前言/附件清单等），返回空数组；
4. title 取条款的核心主题（如"违约责任"、"付款方式"），不含"第X条"等编号前缀。"""


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

        # 1. 元信息提取（独立 1 次调用，输入仅前后 N 页）
        meta = await self._extract_meta(raw_content, pages)

        # 2. 滑动窗口分析条款结构（N 次调用 → markers 列表）
        markers = await self._analyze_structure(raw_content)

        # 3. 按 marker 在原文中定位并切分，定位失败项走 LLM 兜底补取
        clauses = await self._split_by_markers(raw_content, markers)
        if not clauses:
            # 兜底：LLM 未能识别任何条款，整篇作为单一条款
            self._processing_warnings.append("未识别出任何条款，整篇作为单一条款入库")
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

        result_data: dict = {"meta": meta, "clauses": all_clauses}
        if self._processing_warnings:
            result_data["processing_warnings"] = list(self._processing_warnings)
            logger.warning(
                "[contract] slicing completed with %d warnings",
                len(self._processing_warnings),
            )

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
        try:
            raw = await self.call_llm(META_EXTRACT_PROMPT, text)
            data = json.loads(_extract_json(raw))
            return {
                "party_a": data.get("party_a", "") or "",
                "party_b": data.get("party_b", "") or "",
                "contract_type": data.get("contract_type", "其他") or "其他",
            }
        except Exception as e:
            logger.exception("[contract] meta extraction failed")
            self._processing_warnings.append(f"元信息提取失败，需人工补充: {e}")
            return {"party_a": "", "party_b": "", "contract_type": "其他"}

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

        while cursor < len(text):
            chunk = text[cursor : cursor + WINDOW_SIZE]
            chunk_end = cursor + len(chunk)
            is_last_window = cursor + WINDOW_SIZE >= len(text)

            try:
                raw = await self.call_llm(STRUCTURE_PROMPT, chunk)
                result = json.loads(_extract_json(raw))
                markers = result.get("clause_markers", []) or []
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
                # JSON 解析错误等 LLM 返回形式问题
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

            # 保留的 markers：最后一窗全收，非最后窗保留前 N-1 个
            keep = markers if is_last_window else markers[:-1]
            for m in keep:
                self._append_marker(all_markers, seen_markers, m, cursor, chunk_end)

            if is_last_window:
                break

            # 用最后一个 marker 在 chunk 的位置作为下一轮起点
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
        if fallback_indices:
            logger.info(f"[contract] {len(fallback_indices)} markers need LLM recovery")
        for idx in fallback_indices:
            m = markers[idx]
            chunk = text[m["source_chunk_start"] : m["source_chunk_end"]]
            recovered = await self._recover_clause(chunk, m["title"], m["marker"])
            if recovered:
                fallback_content[idx] = recovered
            else:
                logger.warning(
                    "[contract] marker recovery failed: title=%s, marker=%s",
                    m.get("title"), m["marker"][:30],
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
            logger.exception("[contract] recover_clause LLM call failed")
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
        except Exception as e:
            logger.exception("[contract] summary generation failed")
            self._processing_warnings.append(f"合同概要生成失败，需人工补充: {e}")
            return ""

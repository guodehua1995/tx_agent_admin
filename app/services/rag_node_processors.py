"""RAG Node Postprocessors - 用于处理检索后的节点"""

from typing import List, Optional

from llama_index.core.schema import NodeWithScore, QueryBundle


class TextOnlyPostProcessor:
    """
    清理节点，只保留文本内容，移除所有 metadata。
    
    用于减少传入 LLM 的上下文长度，避免 metadata 占用 token。
    """

    def postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        """同步处理节点"""
        
        for node_with_score in nodes:
            # 只保留文本
            node_with_score.node.metadata = {}
        return nodes

    async def apostprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        """异步处理节点"""
        return self.postprocess_nodes(nodes, query_bundle)


class MetadataFilterPostProcessor:
    """
    保留指定的 metadata 字段，移除其他字段。
    
    Args:
        keep_keys: 要保留的 metadata key 列表
    """

    def __init__(self, keep_keys: Optional[List[str]] = None):
        self.keep_keys = set(keep_keys or [])

    def postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        for node_with_score in nodes:
            if self.keep_keys:
                
                # 只保留指定的 keys
                node_with_score.node.metadata = {
                    k: v for k, v in node_with_score.node.metadata.items()
                    if k in self.keep_keys
                }
            else:
                # 清空所有 metadata
                node_with_score.node.metadata = {}
        return nodes

    async def apostprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        return self.postprocess_nodes(nodes, query_bundle)

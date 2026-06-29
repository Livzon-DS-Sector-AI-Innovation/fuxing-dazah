"""DazahNodeFactory — graphon NodeFactory 的 dazah 实现。

注册所有节点类型，并在创建 LLM 节点时注入 DazahLLMAdapter。
"""

from __future__ import annotations

import logging
from typing import Any

from graphon.entities.graph_init_params import GraphInitParams
from graphon.graph.graph import NodeFactory
from graphon.nodes.base.node import Node
from graphon.runtime.graph_runtime_state import GraphRuntimeState

from app.modules.safety.workflow.adapters.code_executor import DazahCodeExecutor
from app.modules.safety.workflow.adapters.llm import DazahLLMAdapter

logger = logging.getLogger(__name__)


class DazahNodeFactory(NodeFactory):
    """创建 graphon Node 实例，注入 dazah 适配器。

    支持的节点类型：
    - start / end — 无需额外依赖
    - llm — 注入 DazahLLMAdapter
    - code — 注入 DazahCodeExecutor
    - if-else / template-transform / variable-aggregator — 无需额外依赖
    """

    def __init__(
        self,
        llm_adapter: DazahLLMAdapter,
        code_executor: DazahCodeExecutor | None = None,
        graph_init_params: GraphInitParams | None = None,
        graph_runtime_state: GraphRuntimeState | None = None,
    ):
        self._llm_adapter = llm_adapter
        self._code_executor = code_executor
        self._graph_init_params = graph_init_params
        self._graph_runtime_state = graph_runtime_state

    def create_node(self, node_config: dict[str, Any]) -> Node:
        """根据 node_config 创建对应的 graphon Node。

        Args:
            node_config: graph JSON 中 nodes[] 的单个元素（包含 id, type, data）

        Returns:
            初始化好的 Node 实例

        Raises:
            ValueError: 未知的节点类型
        """
        node_id = node_config["id"]
        node_data = node_config.get("data", {})
        node_type = node_data.get("type", node_config.get("type", ""))

        return self._create_node_by_type(node_id, node_type, node_data, node_config)

    def _create_node_by_type(
        self,
        node_id: str,
        node_type: str,
        node_data: dict[str, Any],
        raw_config: dict[str, Any],
    ) -> Node:
        """按类型分派节点创建。"""
        graph_init = self._graph_init_params or GraphInitParams(
            workflow_id="",
            graph_config={},
            run_context={},
            call_depth=0,
        )
        graph_runtime = self._graph_runtime_state

        if node_type == "start":
            from graphon.nodes.start.entities import StartNodeData
            from graphon.nodes.start.start_node import StartNode

            data = StartNodeData(**node_data)
            return StartNode(node_id=node_id, data=data)

        elif node_type == "end":
            from graphon.nodes.end.end_node import EndNode
            from graphon.nodes.end.entities import EndNodeData

            data = EndNodeData(**node_data)
            return EndNode(node_id=node_id, data=data)

        elif node_type == "llm":
            from graphon.nodes.llm.entities import LLMNodeData
            from graphon.nodes.llm.node import LLMNode

            data = LLMNodeData(**node_data)
            return LLMNode(
                node_id=node_id,
                data=data,
                graph_init_params=graph_init,
                graph_runtime_state=graph_runtime,
                model_instance=self._llm_adapter,
                llm_file_saver=_NoopFileSaver(),
                prompt_message_serializer=_NoopPromptSerializer(),
            )

        elif node_type == "code":
            from graphon.nodes.code.code_node import CodeNode
            from graphon.nodes.code.entities import CodeNodeData

            data = CodeNodeData(**node_data)
            kwargs: dict[str, Any] = {
                "node_id": node_id,
                "data": data,
                "graph_init_params": graph_init,
                "graph_runtime_state": graph_runtime,
            }
            if self._code_executor:
                kwargs["code_executor"] = self._code_executor
            return CodeNode(**kwargs)

        elif node_type == "if-else":
            from graphon.nodes.if_else.entities import IfElseNodeData
            from graphon.nodes.if_else.if_else_node import IfElseNode

            data = IfElseNodeData(**node_data)
            return IfElseNode(
                node_id=node_id,
                data=data,
                graph_init_params=graph_init,
                graph_runtime_state=graph_runtime,
            )

        elif node_type == "template-transform":
            from graphon.nodes.template_transform.entities import (
                TemplateTransformNodeData,
            )
            from graphon.nodes.template_transform.template_transform_node import (
                TemplateTransformNode,
            )

            data = TemplateTransformNodeData(**node_data)
            return TemplateTransformNode(
                node_id=node_id,
                data=data,
                graph_init_params=graph_init,
                graph_runtime_state=graph_runtime,
            )

        elif node_type == "variable-aggregator":
            from graphon.nodes.variable_aggregator.entities import (
                VariableAggregatorNodeData,
            )
            from graphon.nodes.variable_aggregator.variable_aggregator_node import (
                VariableAggregatorNode,
            )

            data = VariableAggregatorNodeData(**node_data)
            return VariableAggregatorNode(
                node_id=node_id,
                data=data,
                graph_init_params=graph_init,
                graph_runtime_state=graph_runtime,
            )

        else:
            raise ValueError(f"不支持的节点类型: {node_type} (node_id={node_id})")

    def set_run_context(
        self,
        graph_init_params: GraphInitParams,
        graph_runtime_state: GraphRuntimeState,
    ) -> None:
        """设置运行时上下文（在 GraphEngine 启动前调用）。"""
        self._graph_init_params = graph_init_params
        self._graph_runtime_state = graph_runtime_state


# ═══════════════════════════════════════════════════════════
# Minimal protocol stubs (no-op implementations)
# ═══════════════════════════════════════════════════════════


class _NoopFileSaver:
    """占位 LLMFileSaver — 暂时不需要文件保存功能。"""

    def save(self, *args: Any, **kwargs: Any) -> Any:
        return None


class _NoopPromptSerializer:
    """占位 PromptMessageSerializer — 暂时不需要序列化功能。"""

    def serialize(self, prompt_messages: Any) -> str:
        return ""

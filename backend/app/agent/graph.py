"""LangGraph 智能体图 —— M3 版本，支持多步任务编排。

图结构：
    START → planner → executor → (还有下一步吗？)
                              ├── 有 → executor
                              └── 无 → aggregator → END

与 M2 的区别：
    M2 是模型自主选工具（call_model ⇄ tools 闭环）；
    M3 是先生成计划，再按计划逐步执行，最后汇总。

注意：节点里用 get_stream_writer() 推的自定义事件，
需要用 graph.astream(..., stream_mode="custom") 才能收到。
"""

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    aggregator_node,
    executor_node,
    planner_node,
    should_continue,
)
from app.agent.state import AgentState


@lru_cache
def build_graph():
    """编译并缓存整张图。

    用 lru_cache 是因为编译一次就够，避免每次请求都重建。
    M4 加 checkpointer 时这里会变成 build_graph(checkpointer=...)，
    届时缓存键也要跟着调整。
    """
    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("executor", executor_node)
    g.add_node("aggregator", aggregator_node)

    g.add_edge(START, "planner")
    g.add_edge("planner", "executor")

    # 条件边：还有步骤没执行完就回到 executor，否则去汇总
    g.add_conditional_edges(
        "executor",
        should_continue,
        {"executor": "executor", "aggregator": "aggregator"},
    )

    g.add_edge("aggregator", END)
    return g.compile()

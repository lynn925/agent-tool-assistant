"""LangGraph 智能体图 —— M4 版本，支持记忆持久化。

图结构：
    START → planner → executor → (还有下一步吗？)
                              ├── 有 → executor
                              └── 无 → aggregator → END

M4 的变化：编译时传入 checkpointer，图会把每个 thread_id 的状态存进 SQLite。
调用时通过 config={"configurable": {"thread_id": ...}} 指定会话，
不同会话的状态互相隔离。
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
    """编译并缓存整张图（不带 checkpointer）。

    M4 增加了带 checkpointer 的 build_graph_with_memory()，
    两者缓存键不同，互不影响。
    """
    return _compile(None)


@lru_cache
def build_graph_with_memory(checkpointer):
    """编译带 checkpointer 的图。

    参数 checkpointer 参与 lru_cache 的缓存键，
    所以同一个 saver 只会编译一次。
    """
    return _compile(checkpointer)


def _compile(checkpointer):
    """实际的编译逻辑，两个入口共用。"""
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
    # 传 checkpointer 就会持久化每个 thread 的状态
    return g.compile(checkpointer=checkpointer)

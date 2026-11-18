"""LangGraph agent graph — M2 version with tool calling.

Graph shape: START → call_model → (tools? → call_model)* → END
The `tools` node is LangGraph's prebuilt `ToolNode`, which executes the
tool calls the model requested and returns their results as ToolMessages.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.state import AgentState
from app.agent.tools import ALL_TOOLS
from app.config import get_settings


@lru_cache
def _model() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.openai_model,
        api_key=s.openai_api_key or None,
        base_url=s.openai_base_url or None,
        temperature=0.2,
    )


async def call_model(state: AgentState) -> dict:
    """Call the LLM with the three M2 tools bound."""
    response = await _model().bind_tools(ALL_TOOLS).ainvoke(state["messages"])
    return {"messages": [response]}


def _should_call_tools(state: AgentState) -> str:
    """Route to the tool node when the model asked for tool calls."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


@lru_cache
def build_graph():
    """Compile the M2 graph: START → call_model → tools → call_model → END."""
    g = StateGraph(AgentState)
    g.add_node("call_model", call_model)
    g.add_node("tools", ToolNode(ALL_TOOLS))
    g.add_edge(START, "call_model")
    g.add_conditional_edges(
        "call_model",
        _should_call_tools,
        {"tools": "tools", END: END},
    )
    g.add_edge("tools", "call_model")
    return g.compile()

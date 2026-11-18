"""Agent state schema — M1 minimal version.

M3 will extend with `plan`, `current_step`, `final_answer`.
"""

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Subclass of LangGraph's prebuilt MessagesState.

    Inherits `messages: list[BaseMessage]` with the add-message reducer
    already wired up. M2 adds tool-call routing; M3 adds plan fields;
    M4 adds checkpointer-driven persistence.
    """

    pass
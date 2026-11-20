"""智能体状态定义 —— M3 版本。

M2 只用到 LangGraph 内置的 MessagesState（消息列表）。
M3 增加了多步任务编排需要的字段：
    plan          完整的任务计划
    current_step  当前执行到第几步
    final_answer  最终答案
"""

from typing import Any, Literal, TypedDict

from langgraph.graph import MessagesState

#: 步骤状态：
#: pending 待执行 → running 执行中 → done 成功 / failed 失败 / skipped 被跳过
StepStatus = Literal["pending", "running", "done", "failed", "skipped"]


class TaskStep(TypedDict):
    """任务计划里的一个步骤。"""

    #: 步骤 ID，形如 "step-1"
    id: str
    #: 中文描述，展示给用户看
    description: str
    #: 要调用的工具名；None 表示这步不用工具（比如纯思考步骤）
    tool: str | None
    #: 调用参数
    args: dict[str, Any]
    #: 当前状态
    status: StepStatus
    #: 执行结果（成功时）
    result: Any
    #: 错误信息（失败时）
    error: str | None
    #: 重试次数（M5 用，M3 恒为 0）
    retry: int


class AgentState(MessagesState):
    """继承 LangGraph 内置的 MessagesState。

    MessagesState 自带 messages: list[BaseMessage] 字段，
    以及配套的"追加消息" reducer —— 节点返回新消息时，
    LangGraph 会自动把它追加到列表末尾，不用自己手动拼接。

    M3 新增的三个字段用于多步任务编排：
        plan          完整的任务计划（planner 节点产出）
        current_step  当前执行到第几步，-1 表示还没规划
        final_answer  最终答案（aggregator 节点产出）
    """

    #: 完整的任务计划
    plan: list[TaskStep]
    #: 当前执行到第几步；-1 表示还没规划，>= len(plan) 表示已全部执行完
    current_step: int
    #: 最终答案
    final_answer: str | None

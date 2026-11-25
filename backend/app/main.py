"""FastAPI 入口 —— M4：CORS + 路由 + checkpointer 生命周期管理。

路由：
  /api/health            健康检查
  /api/echo              回显（调试用）
  /api/chat              聊天（SSE）
  /api/memory/{id}       查看/清空会话记忆
  /api/threads           会话列表
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.checkpointer import checkpointer_scope
from app.api import chat, echo, health, memory, models, threads
from app.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时打开 SQLite 连接，关闭时释放。"""
    async with checkpointer_scope():
        yield


app = FastAPI(
    title="Agent Tool Assistant API",
    version="0.1.0",
    description="AI Agent 工具调用助手 (LangGraph + OpenAI Function Calling)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(echo.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(threads.router)
app.include_router(models.router)

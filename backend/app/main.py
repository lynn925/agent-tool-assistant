"""FastAPI entry — M1: CORS + /api/health + /api/echo (debug) + /api/chat (real LLM)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, echo, health
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Agent Tool Assistant API",
    version="0.1.0",
    description="AI Agent 工具调用助手 (LangGraph + OpenAI Function Calling)",
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

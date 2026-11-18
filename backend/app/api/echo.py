"""M1 minimal echo endpoint — replaced by /api/chat in M2."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["echo"])


class EchoRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class EchoResponse(BaseModel):
    reply: str


@router.post("/echo", response_model=EchoResponse)
async def echo(req: EchoRequest) -> EchoResponse:
    return EchoResponse(reply=f"[echo] {req.message}")

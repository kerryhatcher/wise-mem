from fastapi import FastAPI
from loguru import logger
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str = "wise-mem"


app = FastAPI(title="wise-mem")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    logger.info("Health endpoint called")
    return HealthResponse()

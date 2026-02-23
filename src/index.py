from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.routes import balance, health, keys, receive, send
from src.services.db import close_pool
from src.services.sdk import disconnect_sdk


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await disconnect_sdk()
    await close_pool()


app = FastAPI(title="glow-cloud", lifespan=lifespan)

app.include_router(health.router)
app.include_router(balance.router)
app.include_router(receive.router)
app.include_router(send.router)
app.include_router(keys.router)

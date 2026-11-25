import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, me
from app.auth.tokens import jwt_secret
from app.db import create_engine, create_sessionmaker
from app.errors import install_error_handlers


def app_origin() -> str:
    """The one origin CORS allows (C-001, Q15); required (A2)."""
    origin = os.environ.get("APP_ORIGIN")
    if not origin:
        raise RuntimeError("APP_ORIGIN is not set")
    return origin


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    jwt_secret()  # fail fast, before anything else (Q10)
    engine = create_engine()
    app.state.sessionmaker = create_sessionmaker(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Shopy API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[app_origin()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
install_error_handlers(app)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

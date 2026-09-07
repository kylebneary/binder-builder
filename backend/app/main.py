"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import binder, collection, goals, sets

app = FastAPI(title="binder-builder", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(sets.router, prefix="/api/v1")
app.include_router(collection.router, prefix="/api/v1")
app.include_router(goals.router, prefix="/api/v1")
app.include_router(binder.router, prefix="/api/v1")

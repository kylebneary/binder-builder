"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


# TODO(phase-1): mount routers from app.api
# app.include_router(sets.router, prefix="/api/v1")
# app.include_router(collection.router, prefix="/api/v1")
# TODO(phase-2): goals, simulate
# TODO(phase-3): binders

"""FastAPI application entry point."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Allow imports from the project root (meeting_engine, diarization, speaker_naming)
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.database import create_tables
from backend.ws_manager import manager
from backend.routers import notes, recording, postprocess, generate, audio_ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="Meeting Assistant API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(notes.router, prefix="/api")
app.include_router(recording.router, prefix="/api/recording")
app.include_router(postprocess.router, prefix="/api/postprocess")
app.include_router(generate.router, prefix="/api/generate")
app.include_router(audio_ws.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/app")


# WebSocket endpoint for live transcription streaming
@app.websocket("/ws/transcription")
async def ws_transcription(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive; client may send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# Serve frontend if built
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/app", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")

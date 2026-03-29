"""Pydantic models for the API."""

from typing import Optional, Any
from pydantic import BaseModel


# --- Folder ---

class FolderCreate(BaseModel):
    name: str


class FolderOut(BaseModel):
    id: int
    name: str
    created_at: str


# --- Note ---

class NoteCreate(BaseModel):
    folder_id: Optional[int] = None
    title: str
    transcript: Optional[Any] = None
    diarized_script: Optional[Any] = None
    summary: Optional[str] = None
    wav_path: Optional[str] = None


class NoteUpdate(BaseModel):
    folder_id: Optional[int] = None
    title: Optional[str] = None
    transcript: Optional[Any] = None
    diarized_script: Optional[Any] = None
    summary: Optional[str] = None
    wav_path: Optional[str] = None
    generated_docs: Optional[Any] = None


class NoteOut(BaseModel):
    id: int
    folder_id: Optional[int]
    title: str
    transcript: Optional[Any]
    diarized_script: Optional[Any]
    summary: Optional[str]
    wav_path: Optional[str]
    generated_docs: Optional[Any]
    created_at: str
    updated_at: str


# --- Recording ---

class RecordingStartRequest(BaseModel):
    engine: str = "gemini"
    language: str = "ko"
    api_key: Optional[str] = None


class RecordingStatusResponse(BaseModel):
    is_recording: bool
    duration: str
    segment_count: int


class RecordingStopResponse(BaseModel):
    wav_path: Optional[str]
    transcript: list[dict]
    duration: str


# --- Postprocess ---

class PostprocessRequest(BaseModel):
    hf_token: Optional[str] = None


class PostprocessResponse(BaseModel):
    status: str
    script: list[dict]
    mapping: dict[str, str]


# --- Generate ---

class GenerateRequest(BaseModel):
    note_id: int
    template: str = "한페이지요약"
    api_key: Optional[str] = None


class GenerateResult(BaseModel):
    content: str

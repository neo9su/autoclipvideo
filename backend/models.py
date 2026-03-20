from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class RoomCreate(BaseModel):
    name: str
    url: str


class Room(BaseModel):
    id: int
    name: str
    url: str
    enabled: bool
    created_at: str
    live_status: Optional[str] = "unknown"  # unknown / live / offline
    recording: Optional[bool] = False
    current_segment: Optional[str] = None
    segment_start: Optional[str] = None


class Recording(BaseModel):
    id: int
    room_id: int
    room_name: Optional[str] = None
    filename: str
    start_time: str
    end_time: Optional[str] = None
    size_bytes: Optional[int] = None
    synced: bool
    segment_index: int

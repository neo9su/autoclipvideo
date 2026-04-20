from pydantic import BaseModel
from typing import Optional, List
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


# ── Publish models ────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    platform: str = "douyin"
    product_id: Optional[str] = None
    product_name: str
    product_url: Optional[str] = None
    product_thumb: Optional[str] = None
    keywords: Optional[str] = None
    enabled: bool = True
    room_id: Optional[int] = None


class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    product_url: Optional[str] = None
    product_thumb: Optional[str] = None
    keywords: Optional[str] = None
    enabled: Optional[bool] = None
    room_id: Optional[int] = None


class PublishAccountCreate(BaseModel):
    platform: str
    account_name: str


class PublishTaskCreate(BaseModel):
    group_id: int
    platform: str
    account_id: Optional[int] = None
    scheduled_at: Optional[str] = None   # ISO datetime string, None = immediate
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    product_id: Optional[int] = None
    product_ids: Optional[List[int]] = None
    auto_meta: bool = False              # trigger LLM meta generation
    no_cart: bool = False                # 无车发布：跳过小黄车挂载步骤


class BatchScheduleCreate(BaseModel):
    platform: str = "douyin"
    account_id: Optional[int] = None
    start_datetime: str                  # ISO datetime, e.g. "2026-03-25T10:00:00"
    interval_minutes: int = 90           # 每篇间隔分钟数
    no_cart: bool = False
    auto_meta: bool = False              # 每个任务触发 LLM 生成文案
    product_ids: Optional[List[int]] = None  # 统一挂载商品（可不填）
    room_id: Optional[int] = None        # 只排期指定直播间的分组（None = 全部）


# ── Director Mode models ──────────────────────────────────────────────────────

class DirectorConfig(BaseModel):
    script_style: str = "professional"  # professional | casual | energetic
    voice_style: str = "female_young"   # 配音风格
    video_style: str = "dynamic"        # 视频合成风格
    duration_target: int = 60           # 目标时长(秒)
    enable_transitions: bool = True     # 是否启用转场效果
    background_music: bool = False      # 是否添加背景音乐


class DirectorScriptSegment(BaseModel):
    text: str
    visual_keywords: List[str]
    duration: Optional[float] = None
    start_time: Optional[float] = None


class DirectorScript(BaseModel):
    text: str
    segments: List[DirectorScriptSegment]
    style: str
    duration_estimate: int


class DirectorMatchedSegment(BaseModel):
    script_segment: DirectorScriptSegment
    matched_recording_id: Optional[int]
    matched_start_time: Optional[float]
    matched_duration: Optional[float]
    confidence_score: float


class SetDirectorModeRequest(BaseModel):
    config: Optional[DirectorConfig] = None


class DirectorProcessRequest(BaseModel):
    regenerate_script: bool = False
    custom_script: Optional[str] = None

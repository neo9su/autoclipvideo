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
    keywords: Optional[str] = None
    enabled: bool = True
    room_id: Optional[int] = None


class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    product_url: Optional[str] = None
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

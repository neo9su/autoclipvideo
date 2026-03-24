"""Bilibili publisher — placeholder."""
from publisher_base import BasePublisher


class BilibiliPublisher(BasePublisher):
    async def login_check(self, account: dict) -> bool:
        raise NotImplementedError("Bilibili publisher not yet implemented")

    async def login_interactive(self, account: dict, cookie_file: str) -> bool:
        raise NotImplementedError("Bilibili publisher not yet implemented")

    async def publish(self, task: dict, video_path: str) -> str:
        raise NotImplementedError("Bilibili publisher not yet implemented")

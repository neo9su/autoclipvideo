"""Abstract base class for platform publishers."""
from abc import ABC, abstractmethod
from typing import Optional


class BasePublisher(ABC):
    """
    Platform publisher interface.
    Each subclass implements login_check and publish for a specific platform.
    """

    @abstractmethod
    async def login_check(self, account: dict) -> bool:
        """
        Check if the account's cookies are still valid.
        Returns True if logged in, False otherwise.
        """

    @abstractmethod
    async def publish(self, task: dict, video_path: str) -> str:
        """
        Publish the video described by task.
        Returns the published URL on success.
        Raises an exception on failure.
        """

    @abstractmethod
    async def login_interactive(self, account: dict, cookie_file: str) -> bool:
        """
        Open a headed browser, let the user log in manually,
        then save cookies to cookie_file. Returns True on success.
        """

"""Abstract base classes for execution adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from trading_platform.core.models import Order


class ExecAdapter(ABC):
    """Interface for execution venues."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def submit_order(self, order: Order) -> Any: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> Any: ...

    @abstractmethod
    async def get_positions(self) -> list[Any]: ...

    @abstractmethod
    async def get_account(self) -> Any: ...

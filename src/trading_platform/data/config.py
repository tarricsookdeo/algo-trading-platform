"""Data ingestion configuration."""

from __future__ import annotations

from pydantic import BaseModel


class DataConfig(BaseModel):
    """Data ingestion configuration."""

    ingestion_enabled: bool = True
    csv_directory: str = ""
    parquet_directory: str = ""
    replay_speed: float = 0.0
    max_bars_per_request: int = 10000

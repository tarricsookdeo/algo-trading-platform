"""Tests for CsvBarProvider — file loading, streaming, validation."""

from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from trading_platform.data.file_provider import CsvBarProvider


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "bars.csv"
    csv_file.write_text(textwrap.dedent("""\
        timestamp,symbol,open,high,low,close,volume
        2024-01-15T09:30:00,AAPL,185.50,186.20,185.30,186.00,125000
        2024-01-15T09:31:00,AAPL,186.00,186.50,185.80,186.30,80000
        2024-01-15T09:30:00,MSFT,380.00,381.00,379.50,380.50,60000
    """))
    return csv_file


@pytest.fixture
def sample_csv_dir(tmp_path: Path) -> Path:
    d = tmp_path / "csvdata"
    d.mkdir()
    (d / "aapl.csv").write_text(textwrap.dedent("""\
        timestamp,symbol,open,high,low,close,volume
        2024-01-15T09:30:00,AAPL,185.50,186.20,185.30,186.00,125000
    """))
    (d / "msft.csv").write_text(textwrap.dedent("""\
        timestamp,symbol,open,high,low,close,volume
        2024-01-15T09:30:00,MSFT,380.00,381.00,379.50,380.50,60000
    """))
    return d


class TestCsvBarProvider:
    @pytest.mark.asyncio
    async def test_connect_loads_bars(self, sample_csv):
        prov = CsvBarProvider(str(sample_csv))
        assert prov.is_connected is False
        await prov.connect()
        assert prov.is_connected is True
        assert len(prov._bars) == 3

    @pytest.mark.asyncio
    async def test_disconnect_clears(self, sample_csv):
        prov = CsvBarProvider(str(sample_csv))
        await prov.connect()
        await prov.disconnect()
        assert prov.is_connected is False
        assert len(prov._bars) == 0

    @pytest.mark.asyncio
    async def test_stream_bars(self, sample_csv):
        prov = CsvBarProvider(str(sample_csv))
        await prov.connect()
        bars = []
        async for bar in prov.stream_bars([]):
            bars.append(bar)
        assert len(bars) == 3
        # Bars should be sorted by timestamp
        assert bars[0].symbol in ("AAPL", "MSFT")
        assert bars[0].timestamp <= bars[1].timestamp

    @pytest.mark.asyncio
    async def test_get_historical_bars(self, sample_csv):
        prov = CsvBarProvider(str(sample_csv))
        await prov.connect()
        start = datetime(2024, 1, 15, 9, 30)
        end = datetime(2024, 1, 15, 9, 30)
        bars = await prov.get_historical_bars("AAPL", start, end)
        assert len(bars) == 1
        assert bars[0].symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_directory_loading(self, sample_csv_dir):
        prov = CsvBarProvider(str(sample_csv_dir))
        await prov.connect()
        assert len(prov._bars) == 2
        symbols = {b.symbol for b in prov._bars}
        assert symbols == {"AAPL", "MSFT"}

    def test_name(self, sample_csv):
        prov = CsvBarProvider(str(sample_csv))
        assert prov.name.startswith("csv:")

    @pytest.mark.asyncio
    async def test_bar_values(self, sample_csv):
        prov = CsvBarProvider(str(sample_csv))
        await prov.connect()
        aapl = [b for b in prov._bars if b.symbol == "AAPL"]
        assert len(aapl) == 2
        bar = aapl[0]
        assert bar.open == 185.50
        assert bar.high == 186.20
        assert bar.low == 185.30
        assert bar.close == 186.00
        assert bar.volume == 125000

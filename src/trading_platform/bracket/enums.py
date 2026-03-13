"""Bracket order enumerations."""

from enum import StrEnum


class BracketState(StrEnum):
    """State machine states for a bracket order."""
    PENDING_ENTRY = "pending_entry"
    ENTRY_PLACED = "entry_placed"
    ENTRY_FILLED = "entry_filled"
    STOP_LOSS_PLACED = "stop_loss_placed"
    MONITORING = "monitoring"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    TAKE_PROFIT_FILLED = "take_profit_filled"
    STOPPED_OUT = "stopped_out"
    CANCELED = "canceled"
    ENTRY_REJECTED = "entry_rejected"
    ERROR = "error"


# Terminal states — bracket is complete
TERMINAL_STATES = frozenset({
    BracketState.TAKE_PROFIT_FILLED,
    BracketState.STOPPED_OUT,
    BracketState.CANCELED,
    BracketState.ENTRY_REJECTED,
    BracketState.ERROR,
})


class BracketChannel(StrEnum):
    """Event bus channels for bracket order events."""
    BRACKET_ENTRY_FILLED = "bracket.entry.filled"
    BRACKET_STOP_PLACED = "bracket.stop.placed"
    BRACKET_STOPPED_OUT = "bracket.stopped_out"
    BRACKET_TAKE_PROFIT_TRIGGERED = "bracket.take_profit.triggered"
    BRACKET_TAKE_PROFIT_FILLED = "bracket.take_profit.filled"
    BRACKET_CANCELED = "bracket.canceled"
    BRACKET_ERROR = "bracket.error"
    BRACKET_STATE_CHANGE = "bracket.state_change"

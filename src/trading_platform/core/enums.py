"""Platform enumerations."""

from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(StrEnum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    PENDING_NEW = "pending_new"
    PENDING_CANCEL = "pending_cancel"
    EXPIRED = "expired"


class AssetClass(StrEnum):
    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"


class ContractType(StrEnum):
    CALL = "call"
    PUT = "put"


class BarType(StrEnum):
    MINUTE = "minute"
    DAILY = "daily"
    UPDATED = "updated"


class Channel(StrEnum):
    """Event bus channels."""
    QUOTE = "quote"
    TRADE = "trade"
    BAR = "bar"
    STATUS = "status"
    ORDER = "order"
    FILL = "fill"
    POSITION = "position"
    SYSTEM = "system"
    ERROR = "error"
    EXPIRATION_WARNING = "options.expiration.warning"
    POSITION_AUTO_CLOSED = "options.position.auto_closed"
    POSITION_ROLLED = "options.position.rolled"

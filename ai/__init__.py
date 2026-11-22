"""Intelligence providers.

The UI and services depend on the small provider protocol in :mod:`ai.provider`
rather than on a vendor SDK, so tests can substitute a deterministic fake and
future local models can be added without rewriting conversation logic.
"""

from ai.errors import AIError, AIErrorKind, classify_exception
from ai.provider import ChatProvider, ChatTurn, ProviderResult

__all__ = [
    "AIError",
    "AIErrorKind",
    "ChatProvider",
    "ChatTurn",
    "ProviderResult",
    "classify_exception",
]

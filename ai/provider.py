"""Provider-neutral conversation types.

A provider receives normalised turns and either streams text through a callback
or returns the complete reply. Conversation storage, retries, cancellation and
audit behaviour stay outside the vendor adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol, Sequence

MessageRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatTurn:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class ProviderResult:
    text: str
    model: str
    chunks: int = 0
    retries: int = 0
    finish_reason: str | None = None


class ChatProvider(Protocol):
    """Minimal interface the conversation service depends on."""

    name: str

    @property
    def configured(self) -> bool:
        """True when credentials are present; not a live connectivity check."""

    def describe(self) -> str:
        """Short, human-readable status safe to show in the UI."""

    async def generate(
        self,
        history: Sequence[ChatTurn],
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> ProviderResult:
        """Return a complete reply, calling ``on_delta`` for streamed chunks."""
        ...

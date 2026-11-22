"""Conversation page: local history, streamed Gemini replies and cancellation."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ai.errors import AIError
from core.application import ApplicationContext
from core.event_manager import Event
from core.services.chat import ChatBusyError
from memory.models import MessageRecord
from ui.components.cards import Card, CardHeader, PageHeader, StatusPill, make_button
from ui.theme import repolish
from utils.formatting import wrap_path
from utils.logger import redact_text
from utils.time import format_local

_ASSISTANT_NAME = "J.A.V.E.D."
_STATE_LABELS = {
    "streaming": "streaming",
    "complete": "complete",
    "error": "failed",
    "cancelled": "stopped",
}


def _time_label(created_at: str | None = None) -> str:
    if created_at:
        rendered = format_local(created_at)
        if rendered != "—":
            return rendered.split()[-1]
    return datetime.now().strftime("%H:%M")


class MessageBubble(QFrame):
    """A plain-text message bubble; model output is never rendered as HTML."""

    def __init__(
        self,
        role: str,
        text: str = "",
        *,
        created_at: str | None = None,
        state: str = "complete",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MessageBubble")
        self.setProperty("role", role)
        self.setProperty("state", state)
        self.setMaximumWidth(680)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 11)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        role_label = QLabel(
            "YOU" if role == "user" else ("SYSTEM" if role == "system" else _ASSISTANT_NAME)
        )
        role_label.setObjectName("BubbleRole")
        header.addWidget(role_label)
        self.meta_label = QLabel(_time_label(created_at))
        self.meta_label.setObjectName("BubbleMeta")
        header.addWidget(self.meta_label)
        header.addStretch(1)
        layout.addLayout(header)

        self.body = QLabel("")
        self.body.setObjectName("BubbleBody")
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.body.setMinimumWidth(0)
        layout.addWidget(self.body)

        self._text = ""
        self._state = state
        if text:
            self.append_text(text)
        else:
            self._refresh_meta()

    @property
    def text(self) -> str:
        return self._text

    def append_text(self, delta: str) -> None:
        if not delta:
            return
        self._text += delta
        self.body.setText(wrap_path(self._text, chunk=40))
        self._refresh_meta()

    def set_text(self, text: str) -> None:
        self._text = text
        self.body.setText(wrap_path(text, chunk=40))
        self._refresh_meta()

    def set_state(self, state: str) -> None:
        self._state = state
        self.setProperty("state", state)
        self._refresh_meta()
        repolish(self)

    def _refresh_meta(self) -> None:
        suffix = _STATE_LABELS.get(self._state)
        base = _time_label()
        self.meta_label.setText(f"{base} · {suffix}" if suffix else base)


class ChatComposer(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.submitted.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class ChatWidget(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._conversation_id: str | None = None
        self._rendered_ids: set[str] = set()
        self._stream_bubble: MessageBubble | None = None
        self._streaming = False
        self._pending_send = False
        self._loading = False
        self.setObjectName("Page")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        self.header = PageHeader(
            "Conversation",
            "Typed Gemini replies stream here with retries, timeouts and cancellation. "
            "Voice input and speech output arrive in Phase 3.",
            eyebrow="J.A.V.E.D. // Phase 02",
        )
        self.provider_pill = StatusPill("Checking", "muted")
        self.new_button = make_button("New chat", "ghost")
        self.new_button.clicked.connect(self._new_chat)
        self.header.add_action(self.provider_pill)
        self.header.add_action(self.new_button)
        outer.addWidget(self.header)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)
        columns.addWidget(self._build_history(), 0)
        columns.addWidget(self._build_conversation(), 1)
        outer.addLayout(columns, 1)

        self._empty_state = self._build_empty_state()
        self._show_empty(self._empty_state)
        self.refresh()

    # ------------------------------------------------------------- construction
    def _build_history(self) -> QWidget:
        card = Card(margins=(14, 14, 14, 14), spacing=10)
        card.setFixedWidth(238)
        card.body.addWidget(
            CardHeader("History", "Stored locally in SQLite. Nothing leaves this computer.")
        )
        self.history_list = QListWidget()
        self.history_list.setObjectName("HistoryList")
        self.history_list.setUniformItemSizes(False)
        self.history_list.currentItemChanged.connect(self._on_history_selected)
        card.body.addWidget(self.history_list, 1)
        self.delete_button = make_button("Delete conversation", "danger")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_current)
        card.body.addWidget(self.delete_button)
        return card

    def _build_conversation(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("ChatPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(18, 13, 18, 12)
        head_layout.setSpacing(10)
        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(1)
        self.title_label = QLabel("New conversation")
        self.title_label.setObjectName("CardTitle")
        title_column.addWidget(self.title_label)
        self.model_label = QLabel("")
        self.model_label.setObjectName("MonoMuted")
        self.model_label.setWordWrap(True)
        title_column.addWidget(self.model_label)
        head_layout.addLayout(title_column, 1)
        self.state_pill = StatusPill("Idle", "muted")
        head_layout.addWidget(self.state_pill)
        self.stop_button = make_button("Stop", "danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        head_layout.addWidget(self.stop_button)
        layout.addWidget(head)

        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ChatTranscript")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.transcript = QWidget()
        self.transcript.setObjectName("ChatTranscriptInner")
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(16, 14, 16, 14)
        self.transcript_layout.setSpacing(10)
        self.transcript_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.transcript_layout.addStretch(1)
        self.scroll.setWidget(self.transcript)
        layout.addWidget(self.scroll, 1)

        composer_frame = QFrame()
        composer_frame.setObjectName("ChatComposerFrame")
        composer_layout = QVBoxLayout(composer_frame)
        composer_layout.setContentsMargins(16, 12, 16, 12)
        composer_layout.setSpacing(8)
        self.composer = ChatComposer()
        self.composer.setObjectName("ChatComposer")
        self.composer.setPlaceholderText(
            "Message J.A.V.E.D. — Enter to send, Shift+Enter for a new line"
        )
        self.composer.setMinimumHeight(64)
        self.composer.setMaximumHeight(132)
        self.composer.submitted.connect(self._send)
        composer_layout.addWidget(self.composer)
        helper_row = QHBoxLayout()
        helper_row.setContentsMargins(0, 0, 0, 0)
        helper_row.setSpacing(10)
        self.helper_label = QLabel("")
        self.helper_label.setObjectName("Footnote")
        self.helper_label.setWordWrap(True)
        self.helper_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        helper_row.addWidget(self.helper_label, 1)
        self.send_button = make_button("Send", "primary")
        self.send_button.clicked.connect(self._send)
        helper_row.addWidget(self.send_button)
        composer_layout.addLayout(helper_row)
        layout.addWidget(composer_frame)
        return panel

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(10)
        layout.addStretch(1)
        eyebrow = QLabel("NO MESSAGES YET")
        eyebrow.setObjectName("Eyebrow")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(eyebrow)
        self.empty_headline = QLabel("Start a conversation.")
        self.empty_headline.setObjectName("Display")
        self.empty_headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_headline.setWordWrap(True)
        layout.addWidget(self.empty_headline)
        self.empty_copy = QLabel("")
        self.empty_copy.setObjectName("BodyCopy")
        self.empty_copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_copy.setWordWrap(True)
        layout.addWidget(self.empty_copy)
        self.settings_button = make_button("Open Settings", "ghost")
        self.settings_button.clicked.connect(lambda: self.navigate_requested.emit("settings"))
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 6, 0, 0)
        button_row.addStretch(1)
        button_row.addWidget(self.settings_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)
        return widget

    # ---------------------------------------------------------------- lifecycle
    def refresh_provider_status(self) -> None:
        self._refresh_provider()

    def refresh(self) -> None:
        self._refresh_provider()
        self._refresh_history()
        if self._conversation_id and not self._streaming:
            self._load_conversation(self._conversation_id)
        elif self._conversation_id is None:
            self._show_empty(self._empty_state)

    def _refresh_provider(self) -> None:
        configured = self.context.chat.configured
        description = self.context.chat.describe()
        self.model_label.setText(description)
        if configured:
            self.provider_pill.set_status("ok", "Gemini ready")
            self.helper_label.setText(
                f"Model: {self.context.chat.model}. Replies are stored locally in the app database."
            )
        else:
            self.provider_pill.set_status("warning", "No API key")
            self.helper_label.setText(
                "No Gemini API key. Add one in Settings, then send a message here."
            )
        self.empty_headline.setText(
            "Start a conversation." if configured else "Gemini is not configured."
        )
        self.empty_copy.setText(
            "Ask a question below. Replies stream from Gemini and stay in local history."
            if configured
            else "Add a Gemini API key in Settings to enable typed conversation. "
            "The key is encrypted with Windows DPAPI."
        )
        self.settings_button.setVisible(not configured)
        self.composer.setEnabled(configured and not self._streaming)
        self.send_button.setEnabled(configured and not self._streaming)
        self.composer.setPlaceholderText(
            "Message J.A.V.E.D. — Enter to send, Shift+Enter for a new line"
            if configured
            else "Add a Gemini API key in Settings to start"
        )

    def _refresh_history(self) -> None:
        conversations = self.context.chat.list_conversations()
        selected = self._conversation_id
        self.history_list.blockSignals(True)
        self.history_list.clear()
        selected_item: QListWidgetItem | None = None
        for conversation in conversations:
            item = QListWidgetItem(conversation.title)
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            item.setToolTip(
                f"Updated {format_local(conversation.updated_at)} · "
                f"{self.context.conversation_repository.message_count(conversation.id)} messages"
            )
            self.history_list.addItem(item)
            if conversation.id == selected:
                selected_item = item
        self.history_list.blockSignals(False)

        if selected_item is not None:
            self.history_list.setCurrentItem(selected_item)
        elif selected is None and conversations:
            first = self.history_list.item(0)
            if first is not None and not self._streaming:
                self.history_list.setCurrentItem(first)
        elif selected is not None and selected_item is None:
            # The active conversation was deleted elsewhere; reset the page.
            self._reset_conversation()
        self.delete_button.setEnabled(
            self._conversation_id is not None and not self._streaming
        )
        self.history_list.setEnabled(not self._streaming)

    # ------------------------------------------------------------- conversation
    def _on_history_selected(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if self._loading or current is None or self._streaming:
            return
        conversation_id = current.data(Qt.ItemDataRole.UserRole)
        if conversation_id and conversation_id != self._conversation_id:
            self._conversation_id = conversation_id
            self._load_conversation(conversation_id)

    def _load_conversation(self, conversation_id: str) -> None:
        self._loading = True
        try:
            conversation = self.context.chat.get_conversation(conversation_id)
            if conversation is None:
                self._reset_conversation()
                return
            self._conversation_id = conversation.id
            self.title_label.setText(conversation.title)
            self._clear_transcript()
            messages = self.context.chat.messages(conversation.id)
            for message in messages:
                self._ensure_message_bubble(message)
            if not messages:
                self._show_empty(self._empty_state)
            self.delete_button.setEnabled(not self._streaming)
        finally:
            self._loading = False
        self._scroll_to_bottom()

    def _new_chat(self) -> None:
        if self._streaming:
            return
        self._reset_conversation()

    def _reset_conversation(self) -> None:
        self._conversation_id = None
        self._rendered_ids.clear()
        self._stream_bubble = None
        self.title_label.setText("New conversation")
        self.state_pill.set_status("muted", "Idle")
        self._clear_transcript()
        self._show_empty(self._empty_state)
        self.history_list.clearSelection()
        self.history_list.setCurrentItem(None)
        self.delete_button.setEnabled(False)

    def _delete_current(self) -> None:
        if self._conversation_id is None or self._streaming:
            return
        confirm = QMessageBox.question(
            self,
            "Delete conversation",
            "Delete this conversation and all of its messages from the local database?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.context.chat.delete_conversation(self._conversation_id)
        except (ChatBusyError, KeyError) as exc:
            self._show_notice(str(exc))
            return
        self._reset_conversation()
        self._refresh_history()

    # ------------------------------------------------------------------- send
    def _send(self) -> None:
        if self._streaming:
            return
        text = self.composer.toPlainText().strip()
        if not text:
            return
        self._pending_send = True
        try:
            handle = self.context.chat.send(self._conversation_id, text)
        except AIError as exc:
            self.composer.setPlainText(text)
            self._show_notice(exc.message)
            self._refresh_provider()
            return
        except (ValueError, ChatBusyError, KeyError) as exc:
            self.composer.setPlainText(text)
            self._show_notice(str(exc))
            return
        finally:
            self._pending_send = False
        self.composer.clear()
        self._conversation_id = handle.conversation.id
        self.title_label.setText(handle.conversation.title)
        self._ensure_message_bubble(handle.user_message)
        self._refresh_history()

    def _stop(self) -> None:
        if self._conversation_id is None:
            return
        if self.context.chat.cancel(self._conversation_id):
            self.stop_button.setEnabled(False)
            self.state_pill.set_status("warning", "Stopping")

    # ------------------------------------------------------------------ events
    def handle_event(self, event: Event) -> None:
        if event.type == "chat.conversations_changed":
            conversation_id = event.get("conversation_id")
            self._refresh_history()
            if conversation_id == self._conversation_id:
                conversation = self.context.chat.get_conversation(conversation_id)
                if conversation is not None:
                    self.title_label.setText(conversation.title)
            return

        conversation_id = event.get("conversation_id")
        if not self._accepts_event(conversation_id):
            return

        if event.type == "chat.message_added":
            payload = event.get("message") or {}
            try:
                message = MessageRecord.model_validate(payload)
            except Exception:
                return
            self._ensure_message_bubble(message)
            self._scroll_to_bottom()
        elif event.type == "chat.started":
            self._begin_streaming(str(event.get("model", self.context.chat.model)))
        elif event.type == "chat.delta":
            self._append_delta(str(event.get("text", "")))
        elif event.type == "chat.completed":
            self._complete_stream(event)
        elif event.type == "chat.failed":
            self._fail_stream(event)
        elif event.type == "chat.cancelled":
            self._cancel_stream()

    def _accepts_event(self, conversation_id: str | None) -> bool:
        if not conversation_id:
            return False
        if conversation_id == self._conversation_id:
            return True
        # Events are emitted synchronously while send() is still on the stack,
        # before ChatWidget knows the id of a newly created conversation.
        if self._pending_send and self._conversation_id is None:
            self._conversation_id = conversation_id
            return True
        return False

    def _begin_streaming(self, model: str) -> None:
        self._streaming = True
        self._stream_bubble = None
        self.state_pill.set_status("accent", "Streaming")
        self.stop_button.setEnabled(True)
        self.send_button.setEnabled(False)
        self.composer.setEnabled(False)
        self.history_list.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.new_button.setEnabled(False)
        self.model_label.setText(f"{model} · generating")

    def _append_delta(self, delta: str) -> None:
        if not delta:
            return
        if self._stream_bubble is None:
            self._hide_empty()
            bubble = MessageBubble("assistant", "", state="streaming")
            self._stream_bubble = bubble
            self._add_bubble(bubble)
        self._stream_bubble.append_text(delta)
        self._scroll_to_bottom()

    def _complete_stream(self, event: Event) -> None:
        payload = event.get("message") or {}
        try:
            message = MessageRecord.model_validate(payload)
        except Exception:
            message = None
        if self._stream_bubble is not None and message is not None:
            self._stream_bubble.set_text(message.content)
            self._stream_bubble.set_state("complete")
            self._rendered_ids.add(message.id)
        elif message is not None:
            self._ensure_message_bubble(message)
        if message is not None:
            retries = int(event.get("retries", 0) or 0)
            suffix = f" · retries {retries}" if retries else ""
            self.model_label.setText(f"{message.metadata.get('model', self.context.chat.model)}{suffix}")
        self.state_pill.set_status("ok", "Complete")
        self._end_streaming()
        self._scroll_to_bottom()

    def _fail_stream(self, event: Event) -> None:
        message = str(event.get("error", "The request failed."))
        if self._stream_bubble is not None:
            self._stream_bubble.set_state("error")
        else:
            self._show_notice(message, state="error")
        self.state_pill.set_status("error", "Failed")
        self.model_label.setText(message)
        self._end_streaming()

    def _cancel_stream(self) -> None:
        if self._stream_bubble is not None:
            self._stream_bubble.set_state("cancelled")
        self.state_pill.set_status("warning", "Stopped")
        self._end_streaming()

    def _end_streaming(self) -> None:
        self._streaming = False
        self._stream_bubble = None
        self.stop_button.setEnabled(False)
        self.history_list.setEnabled(True)
        self.delete_button.setEnabled(self._conversation_id is not None)
        self.new_button.setEnabled(True)
        self._refresh_provider()
        self._refresh_history()

    # -------------------------------------------------------------- transcript
    def _ensure_message_bubble(self, message: MessageRecord) -> None:
        if message.id in self._rendered_ids:
            return
        self._rendered_ids.add(message.id)
        self._hide_empty()
        bubble = MessageBubble(
            message.role,
            message.content,
            created_at=message.created_at,
            state="complete",
        )
        if message.metadata.get("interrupted"):
            bubble.set_state("cancelled")
        self._add_bubble(bubble)

    def _show_notice(self, text: str, *, state: str = "error") -> None:
        self._hide_empty()
        bubble = MessageBubble("system", redact_text(text), state=state)
        self._add_bubble(bubble)
        self._scroll_to_bottom()

    def _add_bubble(self, bubble: MessageBubble) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if bubble.property("role") == "user":
            layout.addStretch(1)
            layout.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
        else:
            layout.addWidget(bubble, 0, Qt.AlignmentFlag.AlignLeft)
            layout.addStretch(1)
        self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, row)

    def _show_empty(self, widget: QWidget) -> None:
        self._hide_empty()
        self.transcript_layout.insertWidget(self.transcript_layout.count() - 1, widget)
        self._empty_widget = widget

    def _hide_empty(self) -> None:
        widget = getattr(self, "_empty_widget", None)
        if widget is not None:
            widget.setParent(None)
            widget.hide()
            self._empty_widget = None

    def _clear_transcript(self) -> None:
        self._hide_empty()
        while self.transcript_layout.count() > 1:
            item = self.transcript_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(0, self._scroll_now)

    def _scroll_now(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

"""Speaker management — list, rename, delete, reset-all.

Identity Lab pattern: destructive actions get an explicit red
confirmation where Enter always cancels, never confirms. Contexts
management joins this dialog in Batch 4.
"""

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from audio_lab.conversation.store import ConversationStore, ConversationStoreError
from audio_lab.identity.errors import IdentityStoreError
from audio_lab.identity.types import IdentityRecord
from audio_lab.ui import theme


def format_identity_row(record: IdentityRecord) -> str:
    """Pure formatting — tested without driving widgets."""
    date = record.created_at.strftime("%Y-%m-%d")
    return f"{record.display_name}  ·  {record.sample_count} samples  ·  {date}"


class _ConfirmDialog(QDialog):
    """Destructive confirmation: Enter cancels, only the red button confirms."""

    def __init__(self, title: str, detail: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QVBoxLayout(self)
        heading = QLabel(f"** {title} **")
        heading.setObjectName("error")
        layout.addWidget(heading)
        body = QLabel(detail)
        body.setWordWrap(True)
        layout.addWidget(body)
        row = QHBoxLayout()
        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)  # safety: Enter cancels, never confirms
        confirm = QPushButton(title)
        confirm.setObjectName("danger")
        confirm.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addStretch(1)
        row.addWidget(confirm)
        layout.addLayout(row)


class ManageDialog(QDialog):
    """Modal management over the identity store and (optionally) the
    conversation store. The caller refreshes the matcher gallery after this
    dialog closes (changes apply live)."""

    def __init__(self, store, conversations=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MANAGE")
        self.setModal(True)
        self.setMinimumSize(500, 380)
        self._store = store
        self._conversations = conversations
        self.changed = False  # gallery-affecting mutation; caller rebuilds

        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACING)
        tabs = QTabWidget()
        tabs.addTab(self._build_speakers_tab(), "SPEAKERS")
        if conversations is not None:
            tabs.addTab(self._build_contexts_tab(), "CONTEXTS")
        root.addWidget(tabs, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("secondary")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        close = QPushButton("CLOSE")
        close.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close)
        root.addLayout(close_row)

        self._records: list[IdentityRecord] = []
        self._reload()
        if conversations is not None:
            self._reload_contexts()

    def _build_speakers_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(theme.SPACING)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, stretch=1)
        row = QHBoxLayout()
        rename = QPushButton("RENAME")
        rename.clicked.connect(self._rename)
        delete = QPushButton("DELETE")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        reset = QPushButton("RESET ALL")
        reset.setObjectName("danger")
        reset.clicked.connect(self._reset_all)
        row.addWidget(rename)
        row.addWidget(delete)
        row.addWidget(reset)
        row.addStretch(1)
        layout.addLayout(row)
        return tab

    def _build_contexts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(theme.SPACING)
        layout.addWidget(QLabel("PRIVATE FACTS — per speaker"))
        self.facts_list = QListWidget()
        layout.addWidget(self.facts_list, stretch=1)
        row = QHBoxLayout()
        make_shared = QPushButton("MAKE SHARED")
        make_shared.clicked.connect(self._make_shared)
        delete_fact = QPushButton("DELETE FACT")
        delete_fact.setObjectName("danger")
        delete_fact.clicked.connect(self._delete_fact)
        row.addWidget(make_shared)
        row.addWidget(delete_fact)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(QLabel("SHARED FACTS — household-wide"))
        self.shared_list = QListWidget()
        self.shared_list.setMaximumHeight(90)
        layout.addWidget(self.shared_list)
        delete_all = QPushButton("DELETE ALL CONVERSATIONS")
        delete_all.setObjectName("danger")
        delete_all.clicked.connect(self._delete_all_conversations)
        layout.addWidget(delete_all)
        return tab

    def _reload(self) -> None:
        self.list_widget.clear()
        try:
            self._records = self._store.list_identities()
        except IdentityStoreError as exc:
            self._records = []
            self.status_label.setText(f"STORE ERROR: {exc}")
            return
        for record in self._records:
            self.list_widget.addItem(format_identity_row(record))

    def _selected(self) -> IdentityRecord | None:
        index = self.list_widget.currentRow()
        if 0 <= index < len(self._records):
            return self._records[index]
        return None

    def _rename(self) -> None:
        record = self._selected()
        if record is None:
            return
        name, ok = QInputDialog.getText(
            self, "RENAME", "New name:", text=record.display_name
        )
        if not ok or not name.strip():
            return
        try:
            self._store.rename_identity(record.identity_id, name)
            self.changed = True
        except (IdentityStoreError, ValueError) as exc:
            self.status_label.setText(f"RENAME FAILED: {exc}")
        self._reload()

    def _delete(self) -> None:
        record = self._selected()
        if record is None:
            return
        confirm = _ConfirmDialog(
            "DELETE",
            f"Delete {record.display_name} — voiceprint and all "
            f"{record.sample_count} samples. This cannot be undone.",
            self,
        )
        if confirm.exec() == QDialog.DialogCode.Accepted:
            try:
                self._store.delete_identity(record.identity_id)
                if self._conversations is not None:
                    # drop their private context too; shared facts they
                    # created stay (sharing was deliberate)
                    self._conversations.delete_speaker_data(record.identity_id)
                self.changed = True
            except (IdentityStoreError, ConversationStoreError) as exc:
                self.status_label.setText(f"DELETE FAILED: {exc}")
            self._reload()
            if self._conversations is not None:
                self._reload_contexts()

    def _reset_all(self) -> None:
        confirm = _ConfirmDialog(
            "RESET ALL",
            "Delete EVERY enrolled speaker and every voice sample. "
            "Deleted data is securely overwritten. This cannot be undone.",
            self,
        )
        if confirm.exec() == QDialog.DialogCode.Accepted:
            try:
                self._store.reset_database()
                self.changed = True
            except IdentityStoreError as exc:
                self.status_label.setText(f"RESET FAILED: {exc}")
            self._reload()

    # -- contexts tab --

    def _name_for(self, speaker_id: str) -> str:
        return next(
            (r.display_name for r in self._records if r.identity_id == speaker_id),
            f"speaker {speaker_id[:8]}",
        )

    def _reload_contexts(self) -> None:
        self.facts_list.clear()
        self.shared_list.clear()
        try:
            shared_id = self._conversations.shared_context_id()
            shared_facts = self._conversations.facts(shared_id)
            for record in self._records:
                ctx = self._conversations.private_context_id(record.identity_id)
                for fact in self._conversations.facts(ctx):
                    item = QListWidgetItem(f"[{record.display_name}]  {fact.content}")
                    item.setData(256, fact.fact_id)  # Qt.UserRole
                    self.facts_list.addItem(item)
            for fact in shared_facts:
                self.shared_list.addItem(
                    f"[from {self._name_for(fact.created_by_speaker_id)}]  {fact.content}"
                )
        except ConversationStoreError as exc:
            self.status_label.setText(f"CONTEXT STORE ERROR: {exc}")

    def _selected_fact_id(self) -> str | None:
        item = self.facts_list.currentItem()
        return item.data(256) if item is not None else None

    def _make_shared(self) -> None:
        fact_id = self._selected_fact_id()
        if fact_id is None:
            return
        try:
            self._conversations.share_fact(fact_id)
            self.status_label.setText("FACT SHARED — NOW HOUSEHOLD-WIDE")
        except ConversationStoreError as exc:
            self.status_label.setText(f"SHARE FAILED: {exc}")
        self._reload_contexts()

    def _delete_fact(self) -> None:
        fact_id = self._selected_fact_id()
        if fact_id is None:
            return
        try:
            self._conversations.delete_fact(fact_id)
            self.status_label.setText("FACT DELETED")
        except ConversationStoreError as exc:
            self.status_label.setText(f"DELETE FAILED: {exc}")
        self._reload_contexts()

    def _delete_all_conversations(self) -> None:
        confirm = _ConfirmDialog(
            "DELETE ALL CONVERSATIONS",
            "Delete every private and shared fact and all conversation "
            "history. Voiceprints are kept. This cannot be undone.",
            self,
        )
        if confirm.exec() == QDialog.DialogCode.Accepted:
            try:
                self._conversations.delete_all()
                self.status_label.setText("ALL CONVERSATIONS DELETED")
            except ConversationStoreError as exc:
                self.status_label.setText(f"DELETE FAILED: {exc}")
            self._reload_contexts()

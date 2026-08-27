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
    QPushButton,
    QVBoxLayout,
)

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
    """Modal speaker management over the IdentityStore. The caller refreshes
    the matcher gallery after this dialog closes (changes apply live)."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MANAGE SPEAKERS")
        self.setModal(True)
        self.setMinimumSize(460, 320)
        self._store = store
        self.changed = False  # any mutation happened; caller rebuilds gallery

        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACING)
        self.list_widget = QListWidget()
        root.addWidget(self.list_widget, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("secondary")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        row = QHBoxLayout()
        rename = QPushButton("RENAME")
        rename.clicked.connect(self._rename)
        delete = QPushButton("DELETE")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        reset = QPushButton("RESET ALL")
        reset.setObjectName("danger")
        reset.clicked.connect(self._reset_all)
        close = QPushButton("CLOSE")
        close.clicked.connect(self.accept)
        row.addWidget(rename)
        row.addWidget(delete)
        row.addWidget(reset)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

        self._records: list[IdentityRecord] = []
        self._reload()

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
                self.changed = True
            except IdentityStoreError as exc:
                self.status_label.setText(f"DELETE FAILED: {exc}")
            self._reload()

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

import re
import sys
import json
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QCheckBox,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QPlainTextEdit,
    QFileDialog,
    QMessageBox,
    QStatusBar,
    QToolButton,
    QHeaderView
)

from es3 import EasySave3, ES3Error

DEFAULT_PASSWORD = "t36gref9u84y7f43g"
INT_MAX = 2147483647

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_value(value):
    """Short text representation of a leaf value for display in the tree."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def convert_text_to_type(text, target_type):
    """Convert edited text back to the original Python type."""
    if target_type is bool:
        low = text.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        raise ValueError("Expected true/false")
    if target_type is int:
        return int(text.strip())
    if target_type is float:
        return float(text.strip())
    if target_type is type(None):
        low = text.strip().lower()
        if low in ("null", "none", ""):
            return None
        return text
    return text


def find_field(data, key):
    """Return the {'__type':.., 'value':..} wrapper dict for a top-level key, or None."""
    entry = data.get(key)
    if isinstance(entry, dict) and "value" in entry:
        return entry
    return None


def get_simple_value(data, key, default=None):
    entry = find_field(data, key)
    if entry is None:
        return default
    return entry.get("value", default)


def set_simple_value(data, key, value):
    entry = find_field(data, key)
    if entry is not None:
        entry["value"] = value


def ensure_field(data, key, default_value, type_name):
    """Create a {'__type', 'value'} wrapper for key if it doesn't already exist.

    Leaves the field untouched (existing value preserved) if it's already present.
    """
    if find_field(data, key) is None:
        data[key] = {"__type": type_name, "value": default_value}


TIER_SUFFIXES = [
    ("TierOneUnlockOwned", "Tier 1"),
    ("TierTwoUnlockOwned", "Tier 2"),
    ("TierThreeUnlockOwned", "Tier 3"),
]

BONE_KEY_RE = re.compile(r"^Bone(\d+)$")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class SaveEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phasmophobia Save Editor")
        self.resize(560, 1100) # 557, 1090

        self.data = None            # currently loaded / edited save data (Python dict)
        self.current_save_path = None
        self._tree_guard = False    # re-entrancy guard for tree edits
        self._common_guard = False  # re-entrancy guard for common-field edits

        self._build_ui()
        self._set_data_loaded_state(False)

    # -- UI construction ---------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_top_bar())

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs)

        self.common_tab = self._build_common_tab()
        self.tree_tab = self._build_tree_tab()
        self.raw_tab = self._build_raw_tab()

        self.tabs.addTab(self.common_tab, "Common Fields")
        self.tabs.addTab(self.tree_tab, "All Fields (Tree)")
        self.tabs.addTab(self.raw_tab, "Raw JSON")

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Open a save file to get started.")

    def _build_top_bar(self):
        layout = QGridLayout()

        # Password row
        layout.addWidget(QLabel("Password:"), 0, 0)
        self.password_edit = QLineEdit(DEFAULT_PASSWORD)
        self.password_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_edit, 0, 1)

        self.show_password_chk = QCheckBox("Show")
        self.show_password_chk.toggled.connect(lambda checked: self.password_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
        layout.addWidget(self.show_password_chk, 0, 2)

        # Save file path row
        layout.addWidget(QLabel("Save file:"), 1, 0)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("No file loaded")
        self.path_edit.setReadOnly(True)
        layout.addWidget(self.path_edit, 1, 1, 1, 2)

        # Buttons
        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open Save File...")
        self.open_btn.clicked.connect(self.open_save_file)
        btn_row.addWidget(self.open_btn)

        self.import_json_btn = QPushButton("Import JSON...")
        self.import_json_btn.clicked.connect(self.import_json)
        btn_row.addWidget(self.import_json_btn)

        btn_row.addStretch()

        self.export_json_btn = QPushButton("Export as JSON...")
        self.export_json_btn.clicked.connect(self.export_json)
        btn_row.addWidget(self.export_json_btn)

        self.save_as_btn = QPushButton("Save As (Encrypted)...")
        self.save_as_btn.setStyleSheet("font-weight: bold;")
        self.save_as_btn.clicked.connect(self.save_as_encrypted)
        btn_row.addWidget(self.save_as_btn)

        layout.addLayout(btn_row, 2, 0, 1, 3)
        layout.setColumnStretch(1, 1)
        return layout

    # -- Tab 1: Common fields ----------------------------------------------

    def _build_common_tab(self):
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        self.common_content = QWidget()
        self.common_layout = QVBoxLayout(self.common_content)
        self.common_layout.addWidget(QLabel("Open a save file to edit common fields."))
        self.common_layout.addStretch()
        scroll.setWidget(self.common_content)
        return outer

    def _rebuild_common_tab(self):
        """Rebuild the Common Fields tab widgets based on the currently loaded data."""
        while self.common_layout.count():
            item = self.common_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if self.data is None:
            self.common_layout.addWidget(QLabel("Open a save file to edit common fields."))
            self.common_layout.addStretch()
            return

        self.common_layout.addWidget(self._build_player_stats_group())
        self.common_layout.addWidget(self._build_bones_group())
        self.common_layout.addWidget(self._build_tier_unlocks_group())
        self.common_layout.addStretch()

    def _build_player_stats_group(self):
        box = QGroupBox("Player Stats")
        form = QFormLayout(box)

        self.money_spin = self._make_int_spin("PlayersMoney", 0, INT_MAX)
        form.addRow("Money:", self._with_max_button(self.money_spin, INT_MAX))

        self.level_spin = self._make_int_spin("NewLevel", 0, 100)
        form.addRow("Level:", self.level_spin)

        self.xp_spin = self._make_int_spin("Experience", 0, INT_MAX)
        form.addRow("Experience:", self.xp_spin)

        # "Prestige" only exists in the Phasmophobia save once the player has prestiged at least
        # once. So we can create it at 0 and if you dont wanna prestige this doesnt
        # cause anything to happen. Tis a win-win :3
        if self.password_edit.text() == DEFAULT_PASSWORD: ensure_field(self.data, "Prestige", 0, "int")
        self.prestige_spin = self._make_int_spin("Prestige", 0, 20)
        form.addRow("Prestige:", self.prestige_spin)

        return box

    def _with_max_button(self, spin, max_value):
        wrapper = QWidget()
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(spin)
        btn = QToolButton()
        btn.setText("Max")
        btn.clicked.connect(lambda: spin.setValue(max_value))
        h.addWidget(btn)
        return wrapper

    def _make_int_spin(self, key, minimum, maximum):
        """Create a QSpinBox bound to a top-level simple int field, if present."""
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setGroupSeparatorShown(True)
        entry = find_field(self.data, key)
        if entry is None or not isinstance(entry.get("value"), (int, float)) or isinstance(entry.get("value"), bool):
            spin.setEnabled(False)
            spin.setToolTip(f"'{key}' was not found in this save file.")
            return spin
        spin.setValue(int(entry["value"]))
        spin.valueChanged.connect(lambda v, k=key: self._on_common_int_changed(k, v))
        return spin

    def _on_common_int_changed(self, key, value):
        if self._common_guard or self.data is None:
            return
        
        set_simple_value(self.data, key, int(value))

        if key == "Prestige":
            set_simple_value(self.data, "PrestigeIndex", value)

    def _build_bones_group(self):
        box = QGroupBox("Bones (set to 3 so they appear in the lobby cabinet)")
        grid = QGridLayout(box)

        bone_keys = sorted((k for k in self.data.keys() if BONE_KEY_RE.match(k)), key=lambda k: int(BONE_KEY_RE.match(k).group(1)))

        self.bone_spins = {}
        if not bone_keys:
            grid.addWidget(QLabel("No 'BoneN' fields found in this save."), 0, 0)
        else:
            col_count = 5
            for i, key in enumerate(bone_keys):
                row, col = divmod(i, col_count)
                label = QLabel(key + ":")
                spin = QSpinBox()
                spin.setRange(0, 10)
                spin.setValue(int(get_simple_value(self.data, key, 0)))
                spin.valueChanged.connect(lambda v, k=key: self._on_common_int_changed(k, v))
                self.bone_spins[key] = spin
                grid.addWidget(label, row * 2, col)
                grid.addWidget(spin, row * 2 + 1, col)

            set_all_btn = QPushButton("Set All Bones to 3")
            set_all_btn.clicked.connect(self._set_all_bones_to_3)
            grid.addWidget(set_all_btn, (len(bone_keys) // col_count + 1) * 2, 0, 1, col_count)

        return box

    def _set_all_bones_to_3(self):
        self._common_guard = True
        try:
            for key, spin in self.bone_spins.items():
                spin.setValue(3)
                set_simple_value(self.data, key, 3)
        finally:
            self._common_guard = False

    def _build_tier_unlocks_group(self):
        box = QGroupBox("Item Tier Unlocks")
        v = QVBoxLayout(box)

        items = {}
        for k in self.data.keys():
            for suffix, _label in TIER_SUFFIXES:
                if k.endswith(suffix):
                    item_name = k[: -len(suffix)]
                    items.setdefault(item_name, {})[suffix] = k
                    break

        if not items:
            v.addWidget(QLabel("No tier-unlock fields found in this save."))
            return box

        table = QTableWidget(len(items), 1 + len(TIER_SUFFIXES))
        table.setHorizontalHeaderLabels(["Item"] + [label for _s, label in TIER_SUFFIXES])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.tier_checkboxes = {suffix: [] for suffix, _ in TIER_SUFFIXES}

        for row, item_name in enumerate(sorted(items.keys())):
            name_item = QTableWidgetItem(item_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, name_item)

            for col, (suffix, _label) in enumerate(TIER_SUFFIXES, start=1):
                full_key = items[item_name].get(suffix)
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setAlignment(Qt.AlignCenter)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                chk = QCheckBox()
                if full_key is None:
                    chk.setEnabled(False)
                else:
                    chk.setChecked(bool(get_simple_value(self.data, full_key, False)))
                    chk.toggled.connect(lambda checked, k=full_key: self._on_common_bool_changed(k, checked))
                    self.tier_checkboxes[suffix].append(chk)
                cell_layout.addWidget(chk)
                table.setCellWidget(row, col, cell)

        table.setMinimumHeight(min(400, 34 * (len(items) + 1)))
        v.addWidget(table)

        btn_row = QHBoxLayout()
        for suffix, label in TIER_SUFFIXES:
            btn = QPushButton(f"Unlock All {label}")
            btn.clicked.connect(lambda checked=False, s=suffix: self._set_all_tier(s, True))
            btn_row.addWidget(btn)
        unlock_all_btn = QPushButton("Unlock Everything")
        unlock_all_btn.setStyleSheet("font-weight: bold;")
        unlock_all_btn.clicked.connect(self._unlock_everything)
        btn_row.addWidget(unlock_all_btn)
        v.addLayout(btn_row)

        return box

    def _on_common_bool_changed(self, key, checked):
        if self._common_guard or self.data is None:
            return
        set_simple_value(self.data, key, bool(checked))

    def _set_all_tier(self, suffix, checked):
        self._common_guard = True
        try:
            for chk in self.tier_checkboxes.get(suffix, []):
                chk.setChecked(checked)
        finally:
            self._common_guard = False
        # Underlying data: toggled signal was blocked by guard, so update directly.
        for k in list(self.data.keys()):
            if k.endswith(suffix):
                set_simple_value(self.data, k, checked)

    def _unlock_everything(self):
        for suffix, _label in TIER_SUFFIXES:
            self._set_all_tier(suffix, True)

    # -- Tab 2: Tree view ----------------------------------------------------

    def _build_tree_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter top-level keys:"))
        self.tree_filter_edit = QLineEdit()
        self.tree_filter_edit.setPlaceholderText("Type to filter (e.g. Tier, Bone, Money)")
        self.tree_filter_edit.textChanged.connect(self._apply_tree_filter)
        filter_row.addWidget(self.tree_filter_edit)

        expand_btn = QPushButton("Expand All")
        expand_btn.clicked.connect(lambda: self.tree.expandAll())
        filter_row.addWidget(expand_btn)

        collapse_btn = QPushButton("Collapse All")
        collapse_btn.clicked.connect(lambda: self.tree.collapseAll())
        filter_row.addWidget(collapse_btn)

        layout.addLayout(filter_row)

        hint = QLabel("Double-click a Value cell to edit it. Press Enter to confirm.")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Key", "Type", "Value"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        layout.addWidget(self.tree)

        return widget

    def _rebuild_tree(self):
        self._tree_guard = True
        try:
            self.tree.clear()
            if self.data is None:
                return
            self._add_tree_children(self.tree.invisibleRootItem(), self.data)
            self._apply_tree_filter()
        finally:
            self._tree_guard = False

    def _add_tree_children(self, parent_item, container):
        if isinstance(container, dict):
            pairs = list(container.items())
        elif isinstance(container, list):
            pairs = list(enumerate(container))
        else:
            return

        for key, value in pairs:
            node = QTreeWidgetItem(parent_item)
            display_key = f"[{key}]" if isinstance(container, list) else str(key)
            node.setText(0, display_key)
            node.setFlags(node.flags() & ~Qt.ItemIsEditable)

            if isinstance(value, dict):
                node.setText(1, "object")
                node.setText(2, f"{{{len(value)} keys}}")
                self._add_tree_children(node, value)
            elif isinstance(value, list):
                node.setText(1, "array")
                node.setText(2, f"[{len(value)} items]")
                self._add_tree_children(node, value)
            else:
                type_name = "null" if value is None else type(value).__name__
                node.setText(1, type_name)
                node.setText(2, format_value(value))
                # Store (container, key, original_type) so we can write back edits.
                node.setData(2, Qt.ItemDataRole.UserRole, (container, key, type(value)))

    def _apply_tree_filter(self, text=None):
        """Apply filter to tree view. If text is None, use current filter text."""
        if text is None:
            text = self.tree_filter_edit.text()
        text = text.strip().lower()
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            top_item = root.child(i)
            match = text == "" or text in top_item.text(0).lower()
            top_item.setHidden(not match)

    def _on_tree_item_double_clicked(self, item, column):
        if column != 2:
            return
        role_data = item.data(2, Qt.ItemDataRole.UserRole)
        if role_data is None:
            return  # container node (object/array), nothing to edit directly
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.tree.editItem(item, 2)

    def _on_tree_item_changed(self, item, column):
        if self._tree_guard or column != 2:
            return
        role_data = item.data(2, Qt.ItemDataRole.UserRole)
        if role_data is None:
            return
        container, key, orig_type = role_data
        text = item.text(2)

        self._tree_guard = True
        try:
            try:
                new_value = convert_text_to_type(text, orig_type)
            except ValueError as e:
                QMessageBox.warning(
                    self,
                    "Invalid value",
                    f"Could not parse '{text}' as {orig_type.__name__}: {e}",
                )
                item.setText(2, format_value(container[key]))
                return

            container[key] = new_value
            item.setText(2, format_value(new_value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        finally:
            self._tree_guard = False

    # -- Tab 3: Raw JSON -------------------------------------------------

    def _build_raw_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        hint = QLabel(
            "Edit the JSON directly, then click 'Apply JSON to Data' to update the "
            "other tabs before saving. This does not save to disk by itself."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.raw_text = QPlainTextEdit()
        self.raw_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.raw_text)

        btn_row = QHBoxLayout()
        self.refresh_raw_btn = QPushButton("Refresh from Data")
        self.refresh_raw_btn.clicked.connect(self._refresh_raw_tab)
        btn_row.addWidget(self.refresh_raw_btn)

        btn_row.addStretch()

        self.apply_raw_btn = QPushButton("Apply JSON to Data")
        self.apply_raw_btn.setStyleSheet("font-weight: bold;")
        self.apply_raw_btn.clicked.connect(self._apply_raw_json)
        btn_row.addWidget(self.apply_raw_btn)

        layout.addLayout(btn_row)
        return widget

    def _refresh_raw_tab(self):
        if self.data is None:
            self.raw_text.setPlainText("")
            return
        self.raw_text.setPlainText(json.dumps(self.data, indent=4, ensure_ascii=False))

    def _apply_raw_json(self):
        text = self.raw_text.toPlainText()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Invalid JSON", f"Could not parse JSON:\n{e}")
            return

        if not isinstance(parsed, dict):
            QMessageBox.critical(self, "Invalid JSON", "The root of the JSON must be an object.")
            return

        self.data = parsed
        self._set_data_loaded_state(True)
        self._refresh_all_tabs()
        self.status.showMessage("Raw JSON applied to in-memory data.", 5000)

    # -- Tab switching -----------------------------------------------------

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.tree_tab:
            self._rebuild_tree()
        elif widget is self.raw_tab:
            self._refresh_raw_tab()

    def _refresh_all_tabs(self):
        self._rebuild_common_tab()
        if self.tabs.currentWidget() is self.tree_tab:
            self._rebuild_tree()
        if self.tabs.currentWidget() is self.raw_tab:
            self._refresh_raw_tab()

    # -- File operations -----------------------------------------------------

    def _get_es3(self):
        password = self.password_edit.text()
        if not password:
            raise ValueError("Password cannot be empty.")
        return EasySave3(password)

    def open_save_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Phasmophobia Save File", "", "All Files (*)")
        if not path:
            return
        try:
            es3 = self._get_es3()
            data = es3.load(path)
        except ES3Error as e:
            QMessageBox.critical(self, "Failed to open save", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Failed to open save", f"Unexpected error:\n{traceback.format_exc()}")
            return

        self.data = data
        self.current_save_path = path
        self.path_edit.setText(path)
        self._set_data_loaded_state(True)
        self._refresh_all_tabs()
        self.status.showMessage(f"Loaded save file: {path}", 5000)

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import JSON Save Data", "", "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.critical(self, "Failed to import JSON", str(e))
            return

        if not isinstance(data, dict):
            QMessageBox.critical(self, "Failed to import JSON", "The root of the JSON must be an object.")
            return

        self.data = data
        # A JSON import isn't tied to an encrypted save path until the user saves it.
        self.current_save_path = None
        self.path_edit.setText(f"(imported from {path}, not yet saved to a save file)")
        self._set_data_loaded_state(True)
        self._refresh_all_tabs()
        self.status.showMessage(f"Imported JSON: {path}", 5000)

    def export_json(self):
        if self.data is None:
            return
        default_name = Path(self.current_save_path).with_suffix('.json').name if self.current_save_path else "SaveFile.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export as JSON", default_name, "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            es3 = self._get_es3()
            es3.export_json(self.data, path)
            self.status.showMessage(f"Exported JSON to {path}", 5000)
        except ES3Error as e:
            QMessageBox.critical(self, "Failed to export JSON", str(e))

    def save_as_encrypted(self):
        if self.data is None:
            return

        # Make sure any pending edits in the raw JSON tab are not silently discarded.
        if self.tabs.currentWidget() is self.raw_tab:
            reply = QMessageBox.question(
                self,
                "Apply raw JSON edits?",
                "You're viewing the Raw JSON tab. Apply its contents before saving?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Yes:
                self._apply_raw_json()
                if self.data is None:
                    return

        default_name = Path(self.current_save_path).name if self.current_save_path else "SaveFile.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Save As (Encrypted Save File)", default_name, "All Files (*)")
        if not path:
            return
        try:
            es3 = self._get_es3()
            es3.save(self.data, path)
        except ES3Error as e:
            QMessageBox.critical(self, "Failed to save", str(e))
            return
        except Exception:
            QMessageBox.critical(self, "Failed to save", f"Unexpected error:\n{traceback.format_exc()}")
            return

        self.current_save_path = path
        self.path_edit.setText(path)
        self.status.showMessage(f"Saved encrypted save file to {path}", 5000)

    # -- Misc ----------------------------------------------------------------

    def _set_data_loaded_state(self, loaded):
        self.export_json_btn.setEnabled(loaded)
        self.save_as_btn.setEnabled(loaded)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Phasmophobia Save Editor")
    window = SaveEditorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
"""创建实验模板对话框。

模板只保存“该复制的东西”：名称、类型、优先级、目标、步骤、预计耗时、
提醒设置、备注。不含具体开始/结束时间（那些是创建实验时才填的）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...models import experiment
from ...models import template
from ..components import make_expand_button


class TemplateEditDialog(QDialog):
    """新建 / 编辑模板（填写后保存到 templates 表）。"""

    def __init__(self, parent=None, template_id=None):
        super().__init__(parent)
        self.template_id = template_id
        self.setWindowTitle("编辑模板" if template_id else "创建模板")
        self.setMinimumWidth(560)
        self._build_ui()
        if template_id is not None:
            self._load(template_id)

    def _load(self, template_id: int) -> None:
        t = template.get(template_id)
        if t is None:
            return
        self.name_edit.setText(t["name"] or "")
        self.type_combo.setCurrentText(t["type"] or "")
        idx = self.priority_combo.findData(t["priority"])
        self.priority_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self.goal_edit.setText(t["goal"] or "")
        self.steps_edit.setPlainText(t["steps"] or "")
        dur = int(t["duration_min"] or 0)
        self.hour_spin.setValue(dur // 60)
        self.min_spin.setValue(dur % 60)
        adv = int(t["remind_advance_min"] or 0)
        self.remind_check.setChecked(bool(adv or t["remind_on_time"] or t["remind_end_min"]))
        self.advance_spin.setValue(adv if adv > 0 else 10)
        self.on_time_check.setChecked(bool(t["remind_on_time"]))
        end_min = int(t["remind_end_min"] or 0)
        self.end_check.setChecked(end_min > 0)
        self.end_min_spin.setValue(end_min if end_min > 0 else 10)
        self.notes_edit.setPlainText(t["notes"] or "")

    def _build_ui(self) -> None:
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("必填，如：质粒构建")

        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItem("")
        for t in experiment.all_types():
            self.type_combo.addItem(t)

        self.priority_combo = QComboBox()
        for key, label in experiment.PRIORITY_LABELS.items():
            self.priority_combo.addItem(label, key)
        self.priority_combo.setCurrentIndex(1)

        self.goal_edit = QLineEdit()
        self.goal_edit.setPlaceholderText("实验目标，如：构建 xxx 质粒")

        self.steps_edit = QPlainTextEdit()
        self.steps_edit.setPlaceholderText("实验步骤，每行一步")
        self.steps_edit.setFixedHeight(90)

        self.hour_spin = QSpinBox()
        self.hour_spin.setRange(0, 999)
        self.hour_spin.setSuffix(" 小时")
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 59)
        self.min_spin.setSuffix(" 分钟")
        dur_row = QHBoxLayout()
        dur_row.addWidget(self.hour_spin)
        dur_row.addWidget(self.min_spin)
        dur_widget = QWidget()
        dur_widget.setLayout(dur_row)

        # 提醒设置（模板里只存默认开关，具体时间创建实验时再定）
        self.remind_check = QCheckBox("默认开启提醒")
        self.advance_spin = QSpinBox()
        self.advance_spin.setRange(0, 720)
        self.advance_spin.setValue(10)
        self.advance_spin.setSuffix(" 分钟")
        self.on_time_check = QCheckBox("到点提醒")
        self.on_time_check.setChecked(True)
        self.end_check = QCheckBox("结束前提醒")
        self.end_min_spin = QSpinBox()
        self.end_min_spin.setRange(0, 720)
        self.end_min_spin.setValue(10)
        self.end_min_spin.setSuffix(" 分钟")
        remind_row1 = QHBoxLayout()
        remind_row1.addWidget(self.remind_check)
        remind_row1.addWidget(QLabel("提前"))
        remind_row1.addWidget(self.advance_spin)
        remind_row1.addWidget(self.on_time_check)
        remind_row1.addStretch()
        remind_row2 = QHBoxLayout()
        remind_row2.addWidget(self.end_check)
        remind_row2.addWidget(self.end_min_spin)
        remind_row2.addStretch()
        remind_vbox = QVBoxLayout()
        remind_vbox.setSpacing(4)
        remind_vbox.addLayout(remind_row1)
        remind_vbox.addLayout(remind_row2)
        remind_widget = QWidget()
        remind_widget.setLayout(remind_vbox)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("备注，如：注意事项")
        self.notes_edit.setFixedHeight(70)

        form.addRow("模板名称 *", self.name_edit)
        form.addRow("类型", self.type_combo)
        form.addRow("优先级", self.priority_combo)
        form.addRow("目标", self.goal_edit)
        form.addRow("步骤", self._with_expand(self.steps_edit, "实验步骤"))
        form.addRow("预计耗时", dur_widget)
        form.addRow("提醒", remind_widget)
        form.addRow("备注", self._with_expand(self.notes_edit, "备注"))

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryBtn")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addLayout(form)
        root.addLayout(btn_row)

    @staticmethod
    def _with_expand(edit, title: str) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(make_expand_button(edit, title))
        v.addLayout(row)
        v.addWidget(edit)
        return wrap

    def accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, config.APP_NAME, "请填写模板名称。")
            return
        remind_on = self.remind_check.isChecked()
        data = {
            "name": name,
            "type": self.type_combo.currentText().strip(),
            "priority": self.priority_combo.currentData(),
            "goal": self.goal_edit.text(),
            "steps": self.steps_edit.toPlainText(),
            "duration_min": self.hour_spin.value() * 60 + self.min_spin.value(),
            "remind_advance_min": self.advance_spin.value() if remind_on else 0,
            "remind_on_time": int(self.on_time_check.isChecked()) if remind_on else 0,
            "remind_end_min": self.end_min_spin.value() if (remind_on and self.end_check.isChecked()) else 0,
            "notes": self.notes_edit.toPlainText(),
        }
        if self.template_id is None:
            template.create(data)
        else:
            template.update(self.template_id, data)
        super().accept()


class TemplateManagerDialog(QDialog):
    """管理模板：列出所有模板，可删除。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理模板")
        self.setMinimumSize(420, 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._edit_selected())
        lay.addWidget(self.list, 1)

        btn = QHBoxLayout()
        add_btn = QPushButton("创建")
        add_btn.setObjectName("primaryBtn")
        add_btn.clicked.connect(self._create)
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_selected)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_selected)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        for b in (add_btn, edit_btn, del_btn, close_btn):
            b.setCursor(Qt.PointingHandCursor)
        btn.addStretch()
        btn.addWidget(add_btn)
        btn.addWidget(edit_btn)
        btn.addWidget(del_btn)
        btn.addWidget(close_btn)
        lay.addLayout(btn)

        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        for t in template.list_templates():
            self.list.addItem(f"{t['name']}　（{t['type'] or '无类型'}）")

    def _create(self) -> None:
        TemplateEditDialog(self).exec()
        self._reload()

    def _selected(self):
        row = self.list.currentRow()
        tpls = template.list_templates()
        if row < 0 or row >= len(tpls):
            return None
        return tpls[row]

    def _edit_selected(self) -> None:
        t = self._selected()
        if t is None:
            return
        TemplateEditDialog(self, template_id=t["id"]).exec()
        self._reload()

    def _delete_selected(self) -> None:
        t = self._selected()
        if t is None:
            return
        if QMessageBox.question(self, config.APP_NAME,
                                f"删除模板「{t['name']}」？") == QMessageBox.Yes:
            template.delete(t["id"])
            self._reload()

"""新建 / 编辑实验对话框。

核心：输入计划开始时间 + 预计耗时后实时计算并显示预计结束时间，
正确处理跨天（如 23:00 + 3h -> 次日 02:00，显示“（跨天）”标记）。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...models import experiment
from ...models import template
from ...utils import time_utils
from ..components import TypeManagerDialog, make_expand_button


class ExperimentEditDialog(QDialog):
    """新建（exp_id=None）或编辑实验。保存成功后 self.saved_id 为实验 id。"""

    def __init__(self, exp_id: int | None = None, parent=None, template_id: int | None = None):
        super().__init__(parent)
        self.exp_id = exp_id
        self.saved_id: int | None = None
        self.setWindowTitle("新建实验" if exp_id is None else "编辑实验")
        self.setMinimumWidth(560)
        self._build_ui()
        if exp_id is not None:
            self._load(experiment.get(exp_id))
        elif template_id is not None:
            self._load_template(template_id)
        self._recompute_end()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # 从模板载入（可选）：选了自动填充类型/目标/步骤/提醒等
        self.template_combo = QComboBox()
        self.template_combo.addItem("（不使用模板）", None)
        for t in template.list_templates():
            self.template_combo.addItem(t["name"], t["id"])
        self.template_combo.currentIndexChanged.connect(self._on_template_selected)
        form.addRow("从模板载入", self.template_combo)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("必填，如：合成质粒")

        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self._reload_types()

        self.priority_combo = QComboBox()
        for key, label in experiment.PRIORITY_LABELS.items():
            self.priority_combo.addItem(label, key)
        self.priority_combo.setCurrentIndex(1)  # 默认“中”

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("逗号分隔，如：克隆, 质粒")

        self.goal_edit = QLineEdit()

        # 计划开始：日期 + 时间
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.time_edit = QTimeEdit(QTime.currentTime())
        self.time_edit.setDisplayFormat("HH:mm")
        start_row = QHBoxLayout()
        start_row.addWidget(self.date_edit)
        start_row.addWidget(self.time_edit)
        start_widget = QWidget()
        start_widget.setLayout(start_row)

        # 预计耗时：小时 + 分钟
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

        self.end_label = QLabel("—")
        self.end_label.setObjectName("cardTitle")

        # 提醒
        self.remind_check = QCheckBox("开启提醒")
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
        remind_row = QHBoxLayout()
        remind_row.addWidget(self.remind_check)
        remind_row.addWidget(QLabel("提前"))
        remind_row.addWidget(self.advance_spin)
        remind_row.addWidget(self.on_time_check)
        remind_row.addStretch()
        remind_row2 = QHBoxLayout()
        remind_row2.addWidget(self.end_check)
        remind_row2.addWidget(self.end_min_spin)
        remind_row2.addStretch()
        remind_vbox = QVBoxLayout()
        remind_vbox.setSpacing(4)
        remind_vbox.addLayout(remind_row)
        remind_vbox.addLayout(remind_row2)
        remind_widget = QWidget()
        remind_widget.setLayout(remind_vbox)

        self.status_combo = QComboBox()
        for key, label in experiment.STATUS_LABELS.items():
            self.status_combo.addItem(label, key)

        self.steps_edit = QPlainTextEdit()
        self.steps_edit.setPlaceholderText("实验步骤，每行一步")
        self.steps_edit.setFixedHeight(90)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("备注")
        self.notes_edit.setFixedHeight(70)

        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        type_row.addWidget(self.type_combo, 1)
        manage_btn = QPushButton("管理类型")
        manage_btn.setCursor(Qt.PointingHandCursor)
        manage_btn.clicked.connect(self._manage_types)
        type_row.addWidget(manage_btn)
        type_widget = QWidget()
        type_widget.setLayout(type_row)

        form.addRow("标题 *", self.title_edit)
        form.addRow("类型", type_widget)
        form.addRow("优先级", self.priority_combo)
        form.addRow("标签", self.tags_edit)
        form.addRow("目标", self.goal_edit)
        form.addRow("计划开始", start_widget)
        form.addRow("预计耗时", dur_widget)
        form.addRow("预计结束", self.end_label)
        form.addRow("提醒", remind_widget)
        form.addRow("状态", self.status_combo)
        form.addRow("步骤", self._with_expand(self.steps_edit, "实验步骤"))
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

        # 实时重算结束时间
        self.date_edit.dateChanged.connect(lambda *_: self._recompute_end())
        self.time_edit.timeChanged.connect(lambda *_: self._recompute_end())
        self.hour_spin.valueChanged.connect(lambda *_: self._recompute_end())
        self.min_spin.valueChanged.connect(lambda *_: self._recompute_end())

    # ------------------------------------------------------------------ 逻辑

    def _start_str(self) -> str:
        d = self.date_edit.date().toString("yyyy-MM-dd")
        t = self.time_edit.time().toString("HH:mm")
        return f"{d} {t}"

    def _duration(self) -> int:
        return self.hour_spin.value() * 60 + self.min_spin.value()

    def _recompute_end(self) -> None:
        """实时计算预计结束时间，跨天时加“（跨天）”标记。"""
        start = self._start_str()
        dur = self._duration()
        if dur > 0:
            end = time_utils.end_time_str(start, dur)
            if end and end[:10] != start[:10]:
                self.end_label.setText(f"{end}  （跨天）")
            else:
                self.end_label.setText(end or "—")
        else:
            self.end_label.setText("—")

    @staticmethod
    def _with_expand(edit, title: str) -> QWidget:
        """把编辑区包上一层“展开”按钮，可弹大窗口编辑。"""
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

    def _load_template(self, template_id: int) -> None:
        """从模板新建：构造时预填表单。"""
        t = template.get(template_id)
        if t is not None:
            self._fill_from_template(t)

    def _on_template_selected(self, _idx: int) -> None:
        """下拉选中模板后一键填充表单。"""
        tpl_id = self.template_combo.currentData()
        if tpl_id is None:
            return
        t = template.get(tpl_id)
        if t is not None:
            self._fill_from_template(t)

    def _fill_from_template(self, t: dict) -> None:
        self.type_combo.setCurrentText(t["type"] or "")
        self.goal_edit.setText(t["goal"] or "")
        self.steps_edit.setPlainText(t["steps"] or "")
        self.notes_edit.setPlainText(t["notes"] or "")
        dur = int(t["duration_min"] or 0)
        self.hour_spin.setValue(dur // 60)
        self.min_spin.setValue(dur % 60)
        idx_p = self.priority_combo.findData(t["priority"])
        self.priority_combo.setCurrentIndex(idx_p if idx_p >= 0 else 1)
        adv = int(t["remind_advance_min"] or 0)
        self.remind_check.setChecked(bool(adv or t["remind_on_time"] or t["remind_end_min"]))
        self.advance_spin.setValue(adv if adv > 0 else 10)
        self.on_time_check.setChecked(bool(t["remind_on_time"]))
        end_min = int(t["remind_end_min"] or 0)
        self.end_check.setChecked(end_min > 0)
        self.end_min_spin.setValue(end_min if end_min > 0 else 10)
        if not self.title_edit.text().strip():
            self.title_edit.setText(t["name"])
        self._recompute_end()

    def _reload_types(self) -> None:
        """重新填充类型下拉（保留当前选择）。"""
        cur = self.type_combo.currentText()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItem("")
        for t in experiment.all_types():
            self.type_combo.addItem(t)
        if cur:
            self.type_combo.setCurrentText(cur)
        self.type_combo.blockSignals(False)

    def _manage_types(self) -> None:
        dlg = TypeManagerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._reload_types()

    def _collect(self) -> dict:
        remind_on = self.remind_check.isChecked()
        return {
            "title": self.title_edit.text(),
            "type": self.type_combo.currentText().strip(),
            "priority": self.priority_combo.currentData(),
            "tags": [t.strip() for t in self.tags_edit.text().split(",") if t.strip()],
            "goal": self.goal_edit.text(),
            "planned_start": self._start_str(),
            "duration_min": self._duration(),
            "status": self.status_combo.currentData(),
            "remind_enabled": int(remind_on),
            "remind_advance_min": self.advance_spin.value() if remind_on else 0,
            "remind_on_time": int(self.on_time_check.isChecked()) if remind_on else 0,
            "remind_end_min": self.end_min_spin.value() if (remind_on and self.end_check.isChecked()) else 0,
            "steps": self.steps_edit.toPlainText(),
            "notes": self.notes_edit.toPlainText(),
        }

    def _load(self, exp: dict) -> None:
        if exp is None:
            return
        self.title_edit.setText(exp["title"])
        self.type_combo.setCurrentText(exp["type"] or "")
        idx = self.priority_combo.findData(exp["priority"])
        self.priority_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self.tags_edit.setText(experiment.tags_to_str(exp))
        self.goal_edit.setText(exp["goal"] or "")
        if exp["planned_start"]:
            try:
                dt = datetime.strptime(exp["planned_start"], "%Y-%m-%d %H:%M")
                self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
                self.time_edit.setTime(QTime(dt.hour, dt.minute))
            except ValueError:
                pass
        dur = int(exp["duration_min"] or 0)
        self.hour_spin.setValue(dur // 60)
        self.min_spin.setValue(dur % 60)
        self.remind_check.setChecked(bool(exp["remind_enabled"]))
        self.advance_spin.setValue(int(exp["remind_advance_min"] or 0))
        self.on_time_check.setChecked(bool(exp["remind_on_time"]))
        end_min = int(exp.get("remind_end_min") or 0)
        self.end_check.setChecked(end_min > 0)
        self.end_min_spin.setValue(end_min if end_min > 0 else 10)
        idx = self.status_combo.findData(exp["status"])
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.steps_edit.setPlainText(exp["steps"] or "")
        self.notes_edit.setPlainText(exp["notes"] or "")

    def accept(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, config.APP_NAME, "请填写实验标题。")
            return
        data = self._collect()
        if self.exp_id is None:
            self.saved_id = experiment.create(data)
        else:
            experiment.update(self.exp_id, data)
            self.saved_id = self.exp_id
        super().accept()

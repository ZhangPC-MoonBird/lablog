"""可复用的实验表单与跟随实验编辑器。

ExperimentCoreForm 同时用于“新建/编辑实验”和“规划项按实验填写”，
保证两边字段完全一致，转规划 / 转实验时不需要重新填写。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QDateTime, QTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ...models import experiment
from ...models import template
from ...utils import time_utils
from ..components import TypeManagerDialog, make_expand_button


def _duration_text(minutes: int) -> str:
    minutes = int(minutes or 0)
    return time_utils.format_duration(minutes) or "0分"


class FollowupEditor(QWidget):
    """跟随实验编辑器：一条主实验可并行挂多条跟随实验。

    每条跟随实验都是完整的实验子记录（目标/步骤/记录/结论），
    跟随时间 = 主实验结束时间 + “结束 + N 天/小时/分钟”。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._parent_end = ""
        self.setObjectName("followupEditor")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.add_btn = QPushButton("＋ 一键添加跟随实验")
        self.add_btn.setObjectName("primaryBtn")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setToolTip("实验结束后需要继续测量/观察时，添加一条完整实验")
        self.add_btn.clicked.connect(lambda: self.add_row())
        hint = QLabel("可添加多个；每个跟随实验有自己的目标、步骤、记录和结论")
        hint.setObjectName("muted")
        head.addWidget(self.add_btn)
        head.addWidget(hint)
        head.addStretch()
        root.addLayout(head)

        self.empty_label = QLabel(
            "暂无跟随实验。例：主实验结束后 1 天开始，持续测量 3 天，按步骤取样并记录结论。")
        self.empty_label.setObjectName("muted")
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        root.addLayout(self.rows_layout)
        self._refresh_empty()

    # ------------------------------------------------------------------ 行

    def add_row(self, spec: dict | None = None, focus: bool = True) -> None:
        spec = spec or {}
        row = QFrame()
        row.setObjectName("subCard")
        v = QVBoxLayout(row)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLineEdit()
        title.setPlaceholderText("跟随实验标题，如：24h 测量")
        title.setText(spec.get("title") or f"跟随实验 {len(self._rows) + 1}")
        type_combo = QComboBox()
        type_combo.setEditable(True)
        type_combo.addItem("")
        for t in experiment.all_types():
            type_combo.addItem(t)
        type_combo.setCurrentText(spec.get("type") or "")
        type_combo.setMinimumWidth(110)
        remove_btn = QPushButton("移除")
        remove_btn.setCursor(Qt.PointingHandCursor)
        head.addWidget(title, 1)
        head.addWidget(QLabel("类型"))
        head.addWidget(type_combo)
        head.addWidget(remove_btn)

        goal_row = QHBoxLayout()
        goal_row.setSpacing(6)
        goal = QLineEdit()
        goal.setPlaceholderText("目标（可选），如：检测 CCR2 表达效率")
        goal.setText(spec.get("goal") or "")
        goal_row.addWidget(QLabel("目标"))
        goal_row.addWidget(goal, 1)

        offset = spec.get("offset_min")
        offset = 0 if offset is None else int(offset)
        duration = int(spec.get("duration_min") or 0)
        if spec.get("duration_min") is None and not spec:
            duration = 24 * 60  # 一键添加的默认值：跟随测量 24 小时（1 天）
        offset_d = QSpinBox()
        offset_d.setRange(0, 999)
        offset_d.setSuffix(" 天")
        offset_d.setValue(offset // (24 * 60))
        offset_h = QSpinBox()
        offset_h.setRange(0, 23)
        offset_h.setSuffix(" 小时")
        offset_h.setValue((offset % (24 * 60)) // 60)
        offset_m = QSpinBox()
        offset_m.setRange(0, 59)
        offset_m.setSuffix(" 分")
        offset_m.setValue(offset % 60)
        dur_d = QSpinBox()
        dur_d.setRange(0, 999)
        dur_d.setSuffix(" 天")
        dur_d.setValue(duration // (24 * 60))
        dur_h = QSpinBox()
        dur_h.setRange(0, 23)
        dur_h.setSuffix(" 小时")
        dur_h.setValue((duration % (24 * 60)) // 60)
        dur_m = QSpinBox()
        dur_m.setRange(0, 59)
        dur_m.setSuffix(" 分")
        dur_m.setValue(duration % 60)
        offset_row = QHBoxLayout()
        offset_row.setSpacing(6)
        offset_row.addWidget(QLabel("实验结束后 +"))
        offset_row.addWidget(offset_d)
        offset_row.addWidget(offset_h)
        offset_row.addWidget(offset_m)
        offset_row.addStretch()
        dur_row = QHBoxLayout()
        dur_row.setSpacing(6)
        dur_row.addWidget(QLabel("跟随耗时"))
        dur_row.addWidget(dur_d)
        dur_row.addWidget(dur_h)
        dur_row.addWidget(dur_m)
        dur_row.addStretch()

        time_label = QLabel()
        time_label.setObjectName("followTime")
        time_label.setWordWrap(True)
        steps = QPlainTextEdit()
        steps.setPlaceholderText("实验步骤，每行一步（可选）")
        steps.setFixedHeight(64)
        steps.setPlainText(spec.get("steps") or "")
        notes = QLineEdit()
        notes.setPlaceholderText("备注（可选）")
        notes.setText(spec.get("notes") or "")

        v.addLayout(head)
        v.addLayout(goal_row)
        v.addLayout(offset_row)
        v.addLayout(dur_row)
        v.addWidget(time_label)
        v.addWidget(QLabel("步骤"))
        v.addWidget(steps)
        v.addWidget(notes)

        entry = {
            "id": spec.get("id"),
            "widget": row,
            "title": title,
            "type": type_combo,
            "goal": goal,
            "steps": steps,
            "offset_d": offset_d,
            "offset_h": offset_h,
            "offset_m": offset_m,
            "dur_d": dur_d,
            "dur_h": dur_h,
            "dur_m": dur_m,
            "time_label": time_label,
            "notes": notes,
        }
        self._rows.append(entry)
        self.rows_layout.addWidget(row)
        remove_btn.clicked.connect(lambda _=False, e=entry: self._remove_row(e))
        for widget in (offset_d, offset_h, offset_m, dur_d, dur_h, dur_m):
            widget.valueChanged.connect(lambda *_, e=entry: self._refresh_row_time(e))
        self._refresh_row_time(entry)
        self._refresh_empty()
        if focus:
            title.setFocus()
            title.selectAll()

    def _remove_row(self, entry: dict) -> None:
        if entry in self._rows:
            self._rows.remove(entry)
            entry["widget"].deleteLater()
            self._refresh_empty()

    def _refresh_empty(self) -> None:
        self.empty_label.setVisible(not self._rows)

    def _refresh_row_time(self, entry: dict) -> None:
        offset = (entry["offset_d"].value() * 24 * 60
                  + entry["offset_h"].value() * 60 + entry["offset_m"].value())
        duration = (entry["dur_d"].value() * 24 * 60
                    + entry["dur_h"].value() * 60 + entry["dur_m"].value())
        offset_text = "立即" if offset == 0 else f"{_duration_text(offset)}后"
        if self._parent_end:
            start = time_utils.end_time_str(self._parent_end, offset)
            end = time_utils.end_time_str(start, duration) if start else ""
            entry["time_label"].setText(
                f"跟随时间：{start or '—'} ~ {end or '—'}（结束后 {offset_text}开始，耗时 "
                f"{_duration_text(duration)}）"
            )
        else:
            entry["time_label"].setText(
                f"跟随时间：实验结束后 {offset_text}开始，耗时 {_duration_text(duration)}"
            )

    # ------------------------------------------------------------------ 数据

    def set_parent_schedule(self, start: str, duration_min: int) -> None:
        """主实验时间变化时刷新每条跟随实验的绝对时间预览。"""
        self._parent_end = time_utils.end_time_str(start, int(duration_min or 0)) if start else ""
        for entry in self._rows:
            self._refresh_row_time(entry)

    def set_specs(self, specs: list[dict] | None) -> None:
        for entry in list(self._rows):
            self._remove_row(entry)
        for spec in specs or []:
            self.add_row(spec, focus=False)
        self._refresh_empty()

    def specs(self) -> list[dict]:
        result: list[dict] = []
        for entry in self._rows:
            title = entry["title"].text().strip()
            goal = entry["goal"].text().strip()
            steps = entry["steps"].toPlainText().strip()
            notes = entry["notes"].text().strip()
            if not title and not goal and not steps and not notes:
                continue
            offset = (entry["offset_d"].value() * 24 * 60
                      + entry["offset_h"].value() * 60 + entry["offset_m"].value())
            duration = (entry["dur_d"].value() * 24 * 60
                        + entry["dur_h"].value() * 60 + entry["dur_m"].value())
            item = {
                "title": title or "跟随实验",
                "type": entry["type"].currentText().strip(),
                "goal": goal,
                "steps": steps,
                "offset_min": offset,
                "duration_min": duration,
                "notes": notes,
            }
            if entry.get("id"):
                item["id"] = int(entry["id"])
            result.append(item)
        return result


class ExperimentCoreForm(QWidget):
    """实验核心字段（新建/编辑实验、规划项实验模式共用）。"""

    schedule_changed = Signal()

    def __init__(
        self,
        parent=None,
        show_template_picker: bool = True,
        show_actual_status: bool = True,
    ):
        super().__init__(parent)
        self._show_template_picker = show_template_picker
        self._show_actual_status = show_actual_status
        self._base_exp: dict | None = None
        self._build_ui()
        self._recompute_end()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        form = QFormLayout(self)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        if self._show_template_picker:
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
        self.priority_combo.setCurrentIndex(1)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("逗号分隔，如：克隆, 质粒")

        self.goal_edit = QLineEdit()

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

        self.actual_start_edit: QDateTimeEdit | None = None
        self.actual_end_edit: QDateTimeEdit | None = None
        self.status_combo: QComboBox | None = None
        if self._show_actual_status:
            self.actual_start_edit = self._actual_edit()
            self.actual_end_edit = self._actual_edit()
            self.status_combo = QComboBox()
            for key, label in experiment.STATUS_LABELS.items():
                self.status_combo.addItem(label, key)

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

        self.followup_editor = FollowupEditor()

        form.addRow("标题 *", self.title_edit)
        form.addRow("类型", type_widget)
        form.addRow("优先级", self.priority_combo)
        form.addRow("标签", self.tags_edit)
        form.addRow("目标", self.goal_edit)
        form.addRow("实验时间", start_widget)
        form.addRow("耗时", dur_widget)
        form.addRow("结束时间", self.end_label)
        if self._show_actual_status:
            form.addRow("实际开始", self.actual_start_edit)
            form.addRow("实际结束", self.actual_end_edit)
        form.addRow("提醒", remind_widget)
        if self._show_actual_status:
            form.addRow("状态", self.status_combo)
        form.addRow("跟随实验", self.followup_editor)
        form.addRow("步骤", self._with_expand(self.steps_edit, "实验步骤"))
        form.addRow("备注", self._with_expand(self.notes_edit, "备注"))

        self.date_edit.dateChanged.connect(lambda *_: self._recompute_end())
        self.time_edit.timeChanged.connect(lambda *_: self._recompute_end())
        self.hour_spin.valueChanged.connect(lambda *_: self._recompute_end())
        self.min_spin.valueChanged.connect(lambda *_: self._recompute_end())

    @staticmethod
    def _actual_edit() -> QDateTimeEdit:
        edit = QDateTimeEdit()
        edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        edit.setCalendarPopup(True)
        edit.setSpecialValueText("未填写")
        edit.setMinimumDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0, 0)))
        edit.setDateTime(edit.minimumDateTime())
        return edit

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

    # ------------------------------------------------------------------ 逻辑

    def _start_str(self) -> str:
        d = self.date_edit.date().toString("yyyy-MM-dd")
        t = self.time_edit.time().toString("HH:mm")
        return f"{d} {t}"

    def _duration(self) -> int:
        return self.hour_spin.value() * 60 + self.min_spin.value()

    def _recompute_end(self) -> None:
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
        self.followup_editor.set_parent_schedule(start, dur)
        self.schedule_changed.emit()

    def _load_template(self, template_id: int) -> None:
        t = template.get(template_id)
        if t is not None:
            self._fill_from_template(t)

    def _on_template_selected(self, _idx: int) -> None:
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
        self.followup_editor.set_specs(template.followups_list(t))
        self._recompute_end()

    def _reload_types(self) -> None:
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

    @staticmethod
    def _actual_str(edit: QDateTimeEdit) -> str:
        if edit.dateTime() <= edit.minimumDateTime():
            return ""
        return edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")

    @staticmethod
    def _set_actual(edit: QDateTimeEdit, value: str) -> None:
        if value:
            dt = QDateTime.fromString(value, "yyyy-MM-dd HH:mm:ss")
            if dt.isValid():
                edit.setDateTime(dt)
                return
        edit.setDateTime(edit.minimumDateTime())

    # ------------------------------------------------------------------ 载入 / 收集

    def load(self, exp: dict) -> None:
        if exp is None:
            return
        self._base_exp = exp
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
        if self._show_actual_status and self.actual_start_edit is not None:
            self._set_actual(self.actual_start_edit, exp.get("actual_start") or "")
            self._set_actual(self.actual_end_edit, exp.get("actual_end") or "")
            idx = self.status_combo.findData(exp["status"])
            self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.remind_check.setChecked(bool(exp["remind_enabled"]))
        self.advance_spin.setValue(int(exp["remind_advance_min"] or 0))
        self.on_time_check.setChecked(bool(exp["remind_on_time"]))
        end_min = int(exp.get("remind_end_min") or 0)
        self.end_check.setChecked(end_min > 0)
        self.end_min_spin.setValue(end_min if end_min > 0 else 10)
        self.steps_edit.setPlainText(exp["steps"] or "")
        self.notes_edit.setPlainText(exp["notes"] or "")
        self.followup_editor.set_specs(experiment.followup_specs(int(exp["id"])))
        self._recompute_end()

    def load_plan_item(self, item: dict) -> None:
        """把规划项（实验模式）载入同一套表单。"""
        self._base_exp = None
        self.title_edit.setText(item.get("title") or "")
        self.type_combo.setCurrentText(item.get("type") or "")
        idx = self.priority_combo.findData(item.get("priority") or "medium")
        self.priority_combo.setCurrentIndex(idx if idx >= 0 else 1)
        import json

        tags = item.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags or "[]")
            except (TypeError, ValueError):
                tags = []
        self.tags_edit.setText(", ".join(tags) if isinstance(tags, list) else "")
        self.goal_edit.setText(item.get("goal") or "")
        d = item.get("planned_date") or QDate.currentDate().toString("yyyy-MM-dd")
        t = item.get("planned_start") or "09:00"
        try:
            dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
        except ValueError:
            dt = datetime.now()
        self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
        self.time_edit.setTime(QTime(dt.hour, dt.minute))
        dur = int(item.get("duration_min") or 0)
        self.hour_spin.setValue(dur // 60)
        self.min_spin.setValue(dur % 60)
        self.remind_check.setChecked(bool(item.get("remind_enabled")))
        self.advance_spin.setValue(int(item.get("remind_advance_min") or 0))
        self.on_time_check.setChecked(bool(item.get("remind_on_time")))
        end_min = int(item.get("remind_end_min") or 0)
        self.end_check.setChecked(end_min > 0)
        self.end_min_spin.setValue(end_min if end_min > 0 else 10)
        self.steps_edit.setPlainText(item.get("steps") or "")
        self.notes_edit.setPlainText(item.get("notes") or "")
        followups = item.get("followups")
        if isinstance(followups, str):
            try:
                followups = json.loads(followups or "[]")
            except (TypeError, ValueError):
                followups = []
        self.followup_editor.set_specs(followups if isinstance(followups, list) else [])
        self._recompute_end()

    def set_basic(
        self, title: str, type_: str, priority: str, date_str: str,
        time_str: str, duration_min: int, notes: str,
    ) -> None:
        """普通规划切到实验模式时，把共用字段带过来，不要求重填。"""
        self.title_edit.setText(title)
        self.type_combo.setCurrentText(type_ or "")
        idx = self.priority_combo.findData(priority)
        self.priority_combo.setCurrentIndex(idx if idx >= 0 else 1)
        try:
            dt = datetime.strptime(f"{date_str} {time_str or '09:00'}", "%Y-%m-%d %H:%M")
        except ValueError:
            dt = datetime.now()
        self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
        self.time_edit.setTime(QTime(dt.hour, dt.minute))
        self.hour_spin.setValue(int(duration_min or 0) // 60)
        self.min_spin.setValue(int(duration_min or 0) % 60)
        self.notes_edit.setPlainText(notes or "")

    def collect(self) -> dict:
        remind_on = self.remind_check.isChecked()
        data = {
            "title": self.title_edit.text(),
            "type": self.type_combo.currentText().strip(),
            "priority": self.priority_combo.currentData(),
            "tags": [t.strip() for t in self.tags_edit.text().split(",") if t.strip()],
            "goal": self.goal_edit.text(),
            "planned_start": self._start_str(),
            "duration_min": self._duration(),
            "remind_enabled": int(remind_on),
            "remind_advance_min": self.advance_spin.value() if remind_on else 0,
            "remind_on_time": int(self.on_time_check.isChecked()) if remind_on else 0,
            "remind_end_min": self.end_min_spin.value() if (remind_on and self.end_check.isChecked()) else 0,
            "steps": self.steps_edit.toPlainText(),
            "notes": self.notes_edit.toPlainText(),
            "followups": self.followup_editor.specs(),
        }
        if self._show_actual_status:
            data.update({
                "actual_start": self._actual_str(self.actual_start_edit),
                "actual_end": self._actual_str(self.actual_end_edit),
                "status": self.status_combo.currentData(),
            })
        else:
            data.update({"actual_start": "", "actual_end": "", "status": "planned"})
        if self._base_exp is not None:
            data["parent_id"] = self._base_exp.get("parent_id")
            data["follow_offset_min"] = self._base_exp.get("follow_offset_min") or 0
        return data

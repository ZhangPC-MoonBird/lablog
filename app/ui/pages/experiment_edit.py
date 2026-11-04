"""新建 / 编辑实验对话框。

表单字段与“规划项按实验填写”共用 ExperimentCoreForm：
标题、类型、标签、目标、时间、耗时、提醒、步骤、备注、跟随实验。
保存后跟随实验落成 experiments 子记录，主实验时间变化时自动平移。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...models import experiment, template
from .experiment_form import ExperimentCoreForm


class ExperimentEditDialog(QDialog):
    """新建（exp_id=None）或编辑实验。保存成功后 self.saved_id 为实验 id。"""

    def __init__(
        self,
        exp_id: int | None = None,
        parent=None,
        template_id: int | None = None,
        initial_title: str = "",
        initial_date: str = "",
        initial_time: str = "",
        initial_duration: int = 0,
    ):
        super().__init__(parent)
        self.exp_id = exp_id
        self.saved_id: int | None = None
        self.setWindowTitle("新建实验" if exp_id is None else "编辑实验")
        self.setMinimumSize(640, 720)
        self.resize(720, 820)
        self._build_ui()

        if exp_id is not None:
            self.form.load(experiment.get(exp_id))
        elif template_id is not None:
            t = template.get(template_id)
            if t is not None:
                self.form._fill_from_template(t)
        else:
            if initial_title:
                self.form.title_edit.setText(initial_title)
            if initial_date and initial_time:
                from PySide6.QtCore import QDate, QTime

                d = QDate.fromString(initial_date, "yyyy-MM-dd")
                t = QTime.fromString(initial_time, "HH:mm")
                if d.isValid():
                    self.form.date_edit.setDate(d)
                if t.isValid():
                    self.form.time_edit.setTime(t)
            if initial_duration:
                self.form.hour_spin.setValue(int(initial_duration) // 60)
                self.form.min_spin.setValue(int(initial_duration) % 60)
        self.form._recompute_end()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        self.form = ExperimentCoreForm(
            show_template_picker=True, show_actual_status=True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(2, 2, 8, 8)
        lay.setSpacing(0)
        lay.addWidget(self.form)
        lay.addStretch()
        scroll.setWidget(container)

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
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        root.addWidget(scroll, 1)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------ 保存

    def accept(self) -> None:
        data = self.form.collect()
        if not (data.get("title") or "").strip():
            QMessageBox.warning(self, config.APP_NAME, "请填写实验标题。")
            return
        followups = data.pop("followups", [])
        if self.exp_id is None:
            self.saved_id = experiment.create(data)
        else:
            experiment.update(self.exp_id, data)
            self.saved_id = self.exp_id
        if self.saved_id:
            experiment.sync_followups(self.saved_id, followups)
        super().accept()

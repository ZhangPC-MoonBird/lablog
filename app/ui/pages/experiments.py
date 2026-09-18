"""实验计划页：搜索/类型/状态筛选 + 列表⇄看板切换 + 新建。

- 双击表格行 / 右键“查看详情”进入实验详情页（经信号交给主窗口）
- 右键菜单：查看详情 / 编辑 / 删除
- 看板四列（未开始/进行中/已完成/失败），卡片内下拉框可改状态
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...models import experiment
from ...utils import time_utils
from ..components import EmptyState, TypeManagerDialog, badge, badge_cell
from .placeholder import PlaceholderPage

_BOARD_COLS = (
    ("planned", "未开始"),
    ("running", "进行中"),
    ("done", "已完成"),
    ("failed", "失败"),
)


def _board_col(status: str) -> str:
    return status if status in ("running", "done", "failed") else "planned"


class _BoardCard(QWidget):
    """看板里的单张实验卡片。"""

    status_changed = Signal()

    def __init__(self, exp: dict):
        super().__init__()
        self.exp_id = exp["id"]
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)

        title = QLabel(exp["title"])
        title.setWordWrap(True)
        title.setObjectName("cardTitle")

        meta = QHBoxLayout()
        meta.setSpacing(6)
        if exp["type"]:
            t = QLabel(exp["type"])
            t.setObjectName("muted")
            meta.addWidget(t)
        meta.addWidget(badge(experiment.PRIORITY_LABELS.get(exp["priority"], "中"),
                             experiment.PRIORITY_COLORS.get(exp["priority"], "warning")))
        meta.addStretch()

        time_label = QLabel(self._time_text(exp))
        time_label.setObjectName("muted")

        self.status_combo = QComboBox()
        for s, label in experiment.STATUS_LABELS.items():
            self.status_combo.addItem(label, s)
        idx = self.status_combo.findData(exp["status"])
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.status_combo.currentIndexChanged.connect(self._on_status)

        lay.addWidget(title)
        lay.addLayout(meta)
        lay.addWidget(time_label)
        lay.addWidget(self.status_combo)

    @staticmethod
    def _time_text(exp: dict) -> str:
        start = exp["planned_start"] or ""
        dur = time_utils.format_duration(exp["duration_min"])
        if start:
            text = start[5:16].replace("-", "/")  # 'MM/DD HH:MM'
            if exp["planned_end"]:
                text += f" ~ {exp['planned_end'][11:16]}"
            if dur:
                text += f"（{dur}）"
            return text
        return dur or "未安排时间"

    def _on_status(self) -> None:
        experiment.set_status(self.exp_id, self.status_combo.currentData())
        self.status_changed.emit()


class ExperimentsPage(QWidget):
    open_experiment = Signal(int)
    new_experiment = Signal()
    edit_experiment = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._exps: list[dict] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        # 顶栏
        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel("实验内容")
        title.setObjectName("pageTitle")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索标题 / 目标 / 备注…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(220)
        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(120)
        self.status_combo = QComboBox()
        self.status_combo.setMinimumWidth(100)
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self.list_btn = QPushButton("列表")
        self.board_btn = QPushButton("看板")
        for b in (self.list_btn, self.board_btn):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self._view_group.addButton(b)
        self.list_btn.setChecked(True)
        new_btn = QPushButton("＋ 新建实验")
        new_btn.setObjectName("primaryBtn")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self.new_experiment.emit)
        manage_tpl_btn = QPushButton("管理模板")
        manage_tpl_btn.setCursor(Qt.PointingHandCursor)
        manage_tpl_btn.setToolTip("创建/编辑/删除实验模板")
        manage_tpl_btn.clicked.connect(self._manage_templates)
        manage_type_btn = QPushButton("管理类型")
        manage_type_btn.setCursor(Qt.PointingHandCursor)
        manage_type_btn.clicked.connect(self._manage_types)

        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.search_edit)
        top.addWidget(self.type_combo)
        top.addWidget(self.status_combo)
        top.addWidget(manage_type_btn)
        top.addSpacing(6)
        top.addWidget(self.list_btn)
        top.addWidget(self.board_btn)
        top.addWidget(manage_tpl_btn)
        top.addWidget(new_btn)
        outer.addLayout(top)

        # 列表 + 看板 + 空状态
        self.stack = QStackedWidget()
        self.list_table = self._build_table()
        self.stack.addWidget(self.list_table)
        self.board = self._build_board()
        self.stack.addWidget(self.board)
        self.empty_state = EmptyState("还没有实验", "点击右上角「＋ 新建实验」开始记录你的实验内容")
        self.stack.addWidget(self.empty_state)
        outer.addWidget(self.stack, 1)

        # 信号
        self.search_edit.textChanged.connect(self.refresh)
        self.type_combo.currentIndexChanged.connect(self.refresh)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        self.list_btn.clicked.connect(self._apply_view)
        self.board_btn.clicked.connect(self._apply_view)

        self.refresh()

    # ------------------------------------------------------------------ 构建

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, 9)
        table.setHorizontalHeaderLabels(
            ["#", "标题", "类型", "计划开始", "预计耗时", "预计结束", "状态", "优先级", "标签"]
        )
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in range(2, 9):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        table.cellDoubleClicked.connect(lambda r, c: self._open_row(r))
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_menu)
        return table

    def _build_board(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._board_layouts: dict[str, QVBoxLayout] = {}
        self._board_headers: dict[str, QLabel] = {}
        self._board_cards: dict[str, list[_BoardCard]] = {s: [] for s, _ in _BOARD_COLS}
        for status, label in _BOARD_COLS:
            col = QWidget()
            v = QVBoxLayout(col)
            v.setSpacing(10)
            h = QLabel(f"{label} · 0")
            h.setObjectName("cardTitle")
            v.addWidget(h)
            v.addStretch()
            self._board_layouts[status] = v
            self._board_headers[status] = h
            lay.addWidget(col, 1)
        return wrap

    # ------------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        """重新加载数据并重建筛选下拉与列表/看板。"""
        self._rebuild_filters()
        self._exps = experiment.list_experiments(
            status=self.status_combo.currentData(),
            type_=self.type_combo.currentData(),
            keyword=self.search_edit.text(),
        )
        self._rebuild_table()
        self._rebuild_board()
        self._apply_view()

    def _apply_view(self) -> None:
        """无数据时显示空状态；有数据时按当前视图按钮显示列表/看板。"""
        if not self._exps:
            self.stack.setCurrentWidget(self.empty_state)
        else:
            self.stack.setCurrentIndex(0 if self.list_btn.isChecked() else 1)

    def _rebuild_filters(self) -> None:
        # 类型
        cur_type = self.type_combo.currentData()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItem("全部类型", "all")
        for t in experiment.all_types():
            self.type_combo.addItem(t, t)
        idx = self.type_combo.findData(cur_type)
        self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.type_combo.blockSignals(False)
        # 状态
        cur_status = self.status_combo.currentData()
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.addItem("全部状态", "all")
        for s, label in experiment.STATUS_LABELS.items():
            self.status_combo.addItem(label, s)
        idx = self.status_combo.findData(cur_status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.status_combo.blockSignals(False)

    def _rebuild_table(self) -> None:
        self.list_table.setRowCount(0)
        for exp in self._exps:
            r = self.list_table.rowCount()
            self.list_table.insertRow(r)
            self._set(r, 0, str(r + 1))  # 序号
            self.list_table.setCellWidget(r, 1, self._title_cell(exp))  # 色块 + 标题
            self._set(r, 2, exp["type"] or "—")
            self._set(r, 3, (exp["planned_start"] or "—")[5:16].replace("-", "/"))
            self._set(r, 4, time_utils.format_duration(exp["duration_min"]) or "—")
            self._set(r, 5, (exp["planned_end"] or "—")[5:16].replace("-", "/"))
            self.list_table.setCellWidget(
                r, 6, badge_cell(experiment.STATUS_LABELS.get(exp["status"], exp["status"]),
                                 experiment.STATUS_COLORS.get(exp["status"], "subtext"))
            )
            self.list_table.setCellWidget(
                r, 7, badge_cell(experiment.PRIORITY_LABELS.get(exp["priority"], exp["priority"]),
                                 experiment.PRIORITY_COLORS.get(exp["priority"], "subtext"))
            )
            self._set(r, 8, experiment.tags_to_str(exp))

    def _title_cell(self, exp: dict) -> QWidget:
        """标题单元格：状态色块 + 标题。"""
        from .. import theme

        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(8)
        color = theme.current().get(
            experiment.STATUS_COLORS.get(exp["status"], "subtext"), "#9CA3AF")
        block = QLabel()
        block.setFixedSize(12, 12)
        block.setStyleSheet(f"background: {color}; border-radius: 3px;")
        h.addWidget(block)
        title = QLabel(exp["title"])
        h.addWidget(title)
        h.addStretch()
        return wrap

    def _set(self, r: int, c: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.list_table.setItem(r, c, item)

    def _rebuild_board(self) -> None:
        for status, _ in _BOARD_COLS:
            for card in self._board_cards[status]:
                self._board_layouts[status].removeWidget(card)
                card.deleteLater()
            self._board_cards[status].clear()
        counts = {s: 0 for s, _ in _BOARD_COLS}
        for exp in self._exps:
            col = _board_col(exp["status"])
            card = _BoardCard(exp)
            card.status_changed.connect(self.refresh)
            self._board_layouts[col].insertWidget(
                self._board_layouts[col].count() - 1, card
            )
            self._board_cards[col].append(card)
            counts[col] += 1
        for status, _ in _BOARD_COLS:
            self._board_headers[status].setText(f"{dict(_BOARD_COLS)[status]} · {counts[status]}")

    # ------------------------------------------------------------------ 交互

    def _manage_types(self) -> None:
        dlg = TypeManagerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    # ------------------------------------------------------------------ 模板

    def _manage_templates(self) -> None:
        from .template_edit import TemplateManagerDialog

        TemplateManagerDialog(parent=self.window()).exec()

    def _selected_id(self) -> int | None:
        row = self.list_table.currentRow()
        if row < 0 or row >= len(self._exps):
            return None
        return self._exps[row]["id"]

    def _open_row(self, row: int) -> None:
        if 0 <= row < len(self._exps):
            self.open_experiment.emit(self._exps[row]["id"])

    def _show_menu(self, pos) -> None:
        exp_id = self._selected_id()
        if exp_id is None:
            return
        menu = QMenu(self)
        act_start = menu.addAction("开始实验")
        act_plan = menu.addAction("转为今日规划")
        act_view = menu.addAction("查看详情")
        act_edit = menu.addAction("编辑")
        act_del = menu.addAction("删除")
        chosen = menu.exec(self.list_table.viewport().mapToGlobal(pos))
        # 菜单关闭后取消行选中，避免残留蓝色选中条
        self.list_table.clearSelection()
        if chosen == act_start:
            experiment.mark_started(exp_id)
            self.refresh()
        elif chosen == act_plan:
            from datetime import datetime

            from ...models import weekly

            today = datetime.now().strftime("%Y-%m-%d")
            weekly.convert_experiment_to_plan(exp_id, today)
            self.refresh()
        elif chosen == act_view:
            self.open_experiment.emit(exp_id)
        elif chosen == act_edit:
            self.edit_experiment.emit(exp_id)
        elif chosen == act_del:
            self._delete(exp_id)

    def _delete(self, exp_id: int) -> None:
        exp = experiment.get(exp_id)
        if exp is None:
            return
        ret = QMessageBox.question(
            self, config.APP_NAME, f"确定删除实验「{exp['title']}」吗？\n相关记录与图片将一并删除。"
        )
        if ret == QMessageBox.Yes:
            experiment.delete(exp_id)
            self.refresh()

    def on_theme_changed(self) -> None:
        self.refresh()

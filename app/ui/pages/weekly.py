"""周整理页：周切换 + 自动汇总（实时统计）+ 三栏编辑（Markdown 自动保存）+ 导出 MD/HTML。"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...models import experiment
from ...models import weekly
from ...services import export_service
from ...utils import image_utils
from ...utils import time_utils
from ..components import (
    Card,
    ClickableImageLabel,
    FlowLayout,
    ImagePreviewDialog,
    ImageTextEdit,
    badge,
    make_expand_button,
)

_FIELDS = (("summary", "本周总结"), ("problems", "遇到的问题"), ("next_plan", "下周计划"))

_IMG_PATH_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _extract_images(text: str) -> list[str]:
    """从 Markdown 文本里提取图片相对路径。"""
    return [m for m in _IMG_PATH_RE.findall(text or "") if m.startswith("images/")]


class WeeklyReviewPage(QWidget):
    open_experiment = Signal(int)  # 点击本周实验标题 → 打开实验详情

    def __init__(self, parent=None):
        super().__init__(parent)
        self.week_start = time_utils.monday_of(date.today()).strftime("%Y-%m-%d")
        self._following_today = True
        self._editors: dict[str, QPlainTextEdit] = {}
        self._timers: dict[str, QTimer] = {}
        self._image_flows: dict[str, FlowLayout] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        # 顶栏：标题 + 周切换 + 导出
        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel("周整理")
        title.setObjectName("pageTitle")
        self.prev_btn = QPushButton("◀ 上一周")
        self.week_label = QLabel()
        self.week_label.setObjectName("cardTitle")
        self.next_btn = QPushButton("下一周 ▶")
        self.today_btn = QPushButton("回到本周")
        for b in (self.prev_btn, self.next_btn, self.today_btn):
            b.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self._shift_week(-7))
        self.next_btn.clicked.connect(lambda: self._shift_week(7))
        self.today_btn.clicked.connect(self._go_today)
        export_md = QPushButton("导出 Markdown")
        export_html = QPushButton("导出 HTML")
        export_docx = QPushButton("导出 Word")
        for b in (export_md, export_html, export_docx):
            b.setCursor(Qt.PointingHandCursor)
        export_md.clicked.connect(lambda: self._export("md"))
        export_html.clicked.connect(lambda: self._export("html"))
        export_docx.clicked.connect(lambda: self._export("docx"))

        top.addWidget(title)
        top.addSpacing(8)
        top.addWidget(self.prev_btn)
        top.addWidget(self.week_label)
        top.addWidget(self.next_btn)
        top.addWidget(self.today_btn)
        top.addStretch()
        top.addWidget(export_md)
        top.addWidget(export_html)
        top.addWidget(export_docx)
        outer.addLayout(top)

        # 汇总条
        self.stats_card = Card()
        self.stats_layout = QHBoxLayout(self.stats_card)
        self.stats_layout.setContentsMargins(20, 14, 20, 14)
        self.stats_layout.setSpacing(28)
        self._stat_labels: dict[str, QLabel] = {}
        for key, caption in (
            ("done", "完成实验"), ("running", "进行中"), ("records", "记录数"),
            ("images", "图片数"), ("failed", "失败"), ("overdue", "超时"),
        ):
            col = QVBoxLayout()
            col.setSpacing(0)
            val = QLabel("0")
            val.setObjectName("statValue")
            cap = QLabel(caption)
            cap.setObjectName("muted")
            col.addWidget(val)
            col.addWidget(cap)
            self.stats_layout.addLayout(col)
            self._stat_labels[key] = val
        self.stats_layout.addStretch()
        outer.addWidget(self.stats_card)

        # 本周实验内容（可引用结论到总结）
        self.week_card = Card()
        wc = QVBoxLayout(self.week_card)
        wc.setContentsMargins(20, 14, 20, 14)
        wc.setSpacing(8)
        whead = QHBoxLayout()
        wl = QLabel("本周实验内容")
        wl.setObjectName("cardTitle")
        self.week_count = QLabel("")
        self.week_count.setObjectName("muted")
        whead.addWidget(wl)
        whead.addStretch()
        whead.addWidget(self.week_count)
        wc.addLayout(whead)
        self.week_list = QVBoxLayout()
        self.week_list.setSpacing(4)
        wc.addLayout(self.week_list)
        outer.addWidget(self.week_card)

        # 三栏编辑区（并排三列）
        self.editors_card = Card()
        ec = QHBoxLayout(self.editors_card)
        ec.setContentsMargins(20, 16, 20, 16)
        ec.setSpacing(14)
        for field, caption in _FIELDS:
            col = QVBoxLayout()
            col.setSpacing(8)

            edit = ImageTextEdit()
            edit.setPlaceholderText(f"填写{caption}…（支持 Markdown、粘贴截图 Ctrl+V、拖入图片）")
            edit.setMinimumHeight(140)
            edit.paste_image.connect(lambda img, f=field: self._add_qimage(f, img))
            edit.drop_image_file.connect(lambda p, f=field: self._add_image_file(f, p))
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda f=field: self._autosave(f))
            edit.textChanged.connect(lambda t=edit: self._on_edited(t))
            self._editors[field] = edit
            self._timers[field] = timer

            head = QHBoxLayout()
            head.setSpacing(8)
            lbl = QLabel(caption)
            lbl.setObjectName("cardTitle")
            expand_btn = make_expand_button(edit, caption)
            img_btn = QPushButton("插入图片")
            img_btn.setCursor(Qt.PointingHandCursor)
            img_btn.clicked.connect(lambda _=False, f=field: self._choose_image(f))
            head.addWidget(lbl)
            head.addStretch()
            head.addWidget(expand_btn)
            head.addWidget(img_btn)
            col.addLayout(head)
            col.addWidget(edit, 1)

            flow = FlowLayout()
            self._image_flows[field] = flow
            col.addLayout(flow)
            ec.addLayout(col, 1)
        outer.addWidget(self.editors_card, 2)

        self._load()

    # ------------------------------------------------------------------ 行为

    def _shift_week(self, delta_days: int) -> None:
        self._save_all()  # 切周前先落库当前周未保存的内容，避免丢失
        self.week_start = (
            datetime.strptime(self.week_start, "%Y-%m-%d") + timedelta(days=delta_days)
        ).strftime("%Y-%m-%d")
        self._following_today = False
        self._load()

    def _go_today(self) -> None:
        """回到本周（本周一）。"""
        self._save_all()
        self.week_start = time_utils.monday_of(date.today()).strftime("%Y-%m-%d")
        self._following_today = True
        self._load()

    def _on_edited(self, edit: QPlainTextEdit) -> None:
        for field, e in self._editors.items():
            if e is edit:
                self._timers[field].start(800)

    def _autosave(self, field: str) -> None:
        weekly.save_review_field(self.week_start, field, self._editors[field].toPlainText())

    def _save_all(self) -> None:
        """立即保存三栏当前内容（用于切周/跨周前）。"""
        for field, _caption in _FIELDS:
            weekly.save_review_field(self.week_start, field, self._editors[field].toPlainText())

    # ------------------------------------------------------------------ 图片

    def _choose_image(self, field: str) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        for p in paths:
            self._add_image_file(field, p)

    def _add_qimage(self, field: str, img) -> None:
        rel = image_utils.save_image(img)
        self._append_image(field, rel)

    def _add_image_file(self, field: str, path: str) -> None:
        rel = image_utils.save_image_file(path)
        if rel:
            self._append_image(field, rel)

    def _append_image(self, field: str, rel: str) -> None:
        self._editors[field].appendPlainText(f"![图片]({rel})")
        self._reload_images(field)

    def _reload_images(self, field: str) -> None:
        flow = self._image_flows[field]
        while flow.count():
            item = flow.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for path in _extract_images(self._editors[field].toPlainText()):
            flow.addWidget(self._image_thumb(field, path))

    def _image_thumb(self, field: str, path: str) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        thumb = ClickableImageLabel(path, max_edge=120)
        thumb.clicked.connect(lambda p=path: self._preview(p))
        rm = QPushButton("移除")
        rm.setCursor(Qt.PointingHandCursor)
        rm.clicked.connect(lambda _=False, f=field, p=path: self._remove_image(f, p))
        v.addWidget(thumb)
        v.addWidget(rm)
        return wrap

    def _remove_image(self, field: str, path: str) -> None:
        edit = self._editors[field]
        txt = edit.toPlainText().replace(f"![图片]({path})", "")
        edit.setPlainText(txt)  # 触发 textChanged → 防抖自动保存
        image_utils.delete_image(path)
        self._reload_images(field)

    def _preview(self, path: str) -> None:
        pm = image_utils.load_pixmap(path)
        if pm is not None:
            ImagePreviewDialog(pm, path.split("/")[-1], self).exec()

    def _load(self) -> None:
        monday, sunday = weekly.week_bounds(self.week_start)
        iso = datetime.strptime(monday, "%Y-%m-%d").date().isocalendar()
        self.week_label.setText(f"{iso[0]}年 第{iso[1]}周  {monday[5:]} ~ {sunday[5:]}")
        review = weekly.get_or_create_review(self.week_start)
        for field, _caption in _FIELDS:
            self._editors[field].blockSignals(True)
            self._editors[field].setPlainText(review.get(field) or "")
            self._editors[field].blockSignals(False)
            self._reload_images(field)
        stats = weekly.week_stats(monday, sunday)
        for key, lbl in self._stat_labels.items():
            lbl.setText(str(stats[key]))

        # 本周实验内容
        exps = weekly.week_experiments(monday, sunday)
        self.week_count.setText(f"共 {len(exps)} 项")
        self._rebuild_week_list(exps)

    def _rebuild_week_list(self, exps: list[dict]) -> None:
        while self.week_list.count():
            item = self.week_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not exps:
            empty = QLabel("本周暂无实验")
            empty.setObjectName("muted")
            self.week_list.addWidget(empty)
            return
        for exp in exps:
            self.week_list.addWidget(self._exp_row(exp))

    def _exp_row(self, exp: dict) -> QWidget:
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 3, 0, 3)
        v.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QPushButton(exp["title"])
        title.setObjectName("expTitleBtn")
        title.setCursor(Qt.PointingHandCursor)
        title.setToolTip("点击查看实验详情")
        title.clicked.connect(lambda _=False, eid=exp["id"]: self.open_experiment.emit(eid))
        head.addWidget(title)
        head.addWidget(badge(
            experiment.STATUS_LABELS.get(exp["status"], exp["status"]),
            experiment.STATUS_COLORS.get(exp["status"], "subtext")))
        head.addStretch()
        view_btn = QPushButton("查看详情")
        view_btn.setCursor(Qt.PointingHandCursor)
        view_btn.clicked.connect(lambda _=False, eid=exp["id"]: self.open_experiment.emit(eid))
        head.addWidget(view_btn)
        v.addLayout(head)

        concl = (exp.get("conclusion") or "").strip()
        if concl:
            cl = QLabel(concl)
            cl.setWordWrap(True)
            cl.setObjectName("muted")
            v.addWidget(cl)
        return row

    def refresh(self) -> None:
        """跨日 / 切页刷新：跟随“本周”，重算统计与内容。"""
        today_monday = time_utils.monday_of(date.today()).strftime("%Y-%m-%d")
        if self._following_today and today_monday != self.week_start:
            self._save_all()  # 跨周切换前先落库
            self.week_start = today_monday
        self._load()

    def _export(self, fmt: str) -> None:
        monday, sunday = weekly.week_bounds(self.week_start)
        review = weekly.get_or_create_review(self.week_start)
        stats = weekly.week_stats(monday, sunday)
        experiments = weekly.week_experiments(monday, sunday)
        plan_items = weekly.list_items_range(monday, sunday)
        label = self.week_label.text()

        if fmt == "md":
            default = f"实验周报_{monday}.md"
            filter_str = "Markdown (*.md)"
        elif fmt == "html":
            default = f"实验周报_{monday}.html"
            filter_str = "HTML (*.html)"
        else:
            default = f"实验周报_{monday}.docx"
            filter_str = "Word 文档 (*.docx)"

        path, _ = QFileDialog.getSaveFileName(
            self, "导出周报", str(config.EXPORTS_DIR / default), filter_str)
        if not path:
            return

        try:
            if fmt == "md":
                content = export_service.build_markdown(
                    self.week_start, review, stats, experiments, plan_items, label)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self._copy_export_images(path, content)
            elif fmt == "html":
                content = export_service.build_html(
                    self.week_start, review, stats, experiments, plan_items, label)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                export_service.export_docx(
                    self.week_start, review, stats, experiments, plan_items, label, path)
        except OSError:
            return

    @staticmethod
    def _copy_export_images(md_path: str, content: str) -> None:
        import shutil
        from pathlib import Path

        dest_dir = Path(md_path).parent / "images"
        for rel in export_service.extract_image_paths(content):
            src = config.DATA_DIR / rel
            if src.exists():
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest_dir / src.name)

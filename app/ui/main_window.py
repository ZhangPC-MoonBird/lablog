"""主窗口：左侧导航栏 + 顶部状态栏 + 卡片式内容区 + 系统托盘 + 提醒。

- 顶栏时钟 HH:MM:SS 每秒刷新；日期 YYYY年MM月DD日 星期X
- 每 30 秒检查日期变化（跨零点检测），M3 起接入今日记录/实验/周整理的全量刷新
- 提醒服务：30 秒扫描，触发后播放声音 + 托盘通知 + 应用内弹窗
- 关闭窗口最小化到托盘，后台继续提醒
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PySide6.QtCore import QPoint, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..database import get_setting, set_setting
from ..models import daily_log
from ..services import backup_service
from ..services.reminder_service import ReminderService
from ..services.weather_service import WeatherService
from ..utils import sound_gen
from ..utils import time_utils
from . import theme
from .components import ReminderPopup, nav_icon, render_pixmap, svg_icon
from .pages.dashboard import DashboardPage
from .pages.experiment_detail import ExperimentDetailPage
from .pages.experiment_edit import ExperimentEditDialog
from .pages.experiments import ExperimentsPage
from .pages.planner import PlannerPage
from .pages.settings_page import SettingsPage
from .pages.weekly import WeeklyReviewPage

log = logging.getLogger(__name__)

NAV_ITEMS = (
    ("dashboard", "仪表盘", "home", "今日概览与每日记录"),
    ("experiments", "实验内容", "flask", "新建、编辑、删除实验，自动计算结束时间与提醒"),
    ("planner", "实验规划", "calendar", "下周七天规划视图、拖拽排程、一键转实验（M4）"),
    ("weekly", "周整理", "doc", "自动汇总本周工作，导出 Markdown / HTML（M4）"),
    ("settings", "设置", "settings", "主题、天气、备份与提醒默认值（M5）"),
)
NAV_ICONS = {item[0]: item[2] for item in NAV_ITEMS}


class _TitleBar(QFrame):
    """自绘标题栏：拖动窗口、双击最大化、窗口控制按钮（最小化/最大化/关闭）。"""

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self._window = window
        self._press_pos: QPoint | None = None
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(48)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 6, 0)
        lay.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(render_pixmap("logo", theme.current()["primary"], 20))
        name = QLabel(config.APP_NAME)
        name.setObjectName("appName")
        lay.addWidget(logo)
        lay.addWidget(name)

        self.date_label = QLabel()
        self.date_label.setObjectName("dateLabel")

        self.weather_chip = QWidget()
        self.weather_chip.setObjectName("weatherChip")
        self.weather_chip.setAttribute(Qt.WA_StyledBackground, True)
        wl = QHBoxLayout(self.weather_chip)
        wl.setContentsMargins(10, 3, 12, 3)
        wl.setSpacing(5)
        self.weather_icon = QLabel()
        self.weather_text = QLabel("天气未启用")
        self.weather_text.setObjectName("muted")
        wl.addWidget(self.weather_icon)
        wl.addWidget(self.weather_text)

        self.clock_label = QLabel()
        self.clock_label.setObjectName("clockLabel")

        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("iconBtn")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setIconSize(QSize(18, 18))
        self.theme_btn.setToolTip("切换亮色 / 暗色主题")
        self.theme_btn.clicked.connect(window.toggle_theme)

        lay.addWidget(self.date_label)
        lay.addWidget(self.weather_chip)
        lay.addStretch()
        lay.addWidget(self.clock_label)
        lay.addWidget(self.theme_btn)

        self.min_btn = QPushButton()
        self.max_btn = QPushButton()
        self.close_btn = QPushButton()
        for icon_name, tip, slot in (
            ("win_min", "最小化", window.showMinimized),
            ("win_max", "最大化 / 还原", self._toggle_max),
            ("win_close", "关闭", self._on_close_clicked),
        ):
            btn = self.min_btn if icon_name == "win_min" else (
                self.max_btn if icon_name == "win_max" else self.close_btn)
            btn.setObjectName("closeBtn" if icon_name == "win_close" else "iconBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIcon(svg_icon(icon_name, theme.current()["subtext"], 14))
            btn.setIconSize(QSize(14, 14))
            btn.setFixedSize(32, 28)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            lay.addWidget(btn)

    def _toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _on_close_clicked(self) -> None:
        """点关闭按钮：弹出菜单，可选“最小化到托盘”或“退出程序”。"""
        menu = QMenu(self)
        act_tray = menu.addAction("最小化到托盘")
        act_quit = menu.addAction("退出程序")
        pos = self.close_btn.mapToGlobal(QPoint(0, self.close_btn.height()))
        chosen = menu.exec(pos)
        if chosen == act_tray:
            self._window.hide()
            if self._window.tray is not None and self._window.tray.isVisible():
                self._window.tray.showMessage(
                    config.APP_NAME, "已最小化到托盘，提醒仍会正常触发。",
                    QSystemTrayIcon.Information, 3000)
        elif chosen == act_quit:
            self._window.quit_app()

    def refresh_theme(self) -> None:
        c = theme.current()
        self.min_btn.setIcon(svg_icon("win_min", c["subtext"], 14))
        self.max_btn.setIcon(svg_icon("win_max", c["subtext"], 14))
        self.close_btn.setIcon(svg_icon("win_close", c["subtext"], 14))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is not None and (event.buttons() & Qt.LeftButton):
            if self._window.isMaximized():
                self._window.showNormal()
            self._window.move(event.globalPosition().toPoint() - self._press_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._toggle_max()
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    """应用主窗口。"""

    day_changed = Signal(str)  # 跨零点信号，参数为新日期 YYYY-MM-DD

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setWindowTitle(config.APP_NAME)
        self._theme = get_setting("theme", "light")
        self.setWindowIcon(svg_icon("logo", theme.current()["primary"], 24))
        self.resize(1200, 800)
        self.setMinimumSize(1024, 680)

        self._current_day = datetime.now().strftime("%Y-%m-%d")
        self._nav_buttons: dict[str, QPushButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._detail_page: ExperimentDetailPage | None = None
        self._detail_return_key = "experiments"
        self._popups: list[ReminderPopup] = []
        self._allow_close = False

        self._build_ui()
        self.switch_page("dashboard")
        self._setup_tray()

        # 提醒服务：30 秒扫描一次
        self.reminder = ReminderService(self)
        self.reminder.fired.connect(self._on_reminder)

        # 天气服务（子线程获取，不阻塞 UI）+ 定时刷新
        self.weather = WeatherService(self)
        self.weather.ready.connect(self._on_weather_ready)
        self.weather.failed.connect(self._on_weather_failed)
        self._weather_timer = QTimer(self)
        self._weather_timer.timeout.connect(self.weather.refresh)
        self._weather_timer.start(int(get_setting("weather_update_min", 30) or 30) * 60_000)
        self.weather.refresh()

        # 启动时确保今日记录存在；跨零点做全量刷新
        daily_log.get_or_create(self._current_day)
        self.day_changed.connect(self._on_day_changed)

        # 时钟：每秒刷新一次
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(1000)
        # 跨日检测：每 30 秒检查一次日期
        self._day_timer = QTimer(self)
        self._day_timer.timeout.connect(self._check_day)
        self._day_timer.start(30_000)
        # 每日自动备份：每 60 秒检查一次是否到点
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._check_auto_backup)
        self._backup_timer.start(60_000)
        self._tick()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        root.setAttribute(Qt.WA_StyledBackground, True)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        root_lay.addWidget(self._build_titlebar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_stack(), 1)
        root_lay.addLayout(body, 1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(204)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(12, 18, 12, 14)
        lay.setSpacing(4)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        logo_icon = QLabel()
        logo_icon.setPixmap(render_pixmap("logo", theme.current()["primary"], 24))
        name = QLabel(config.APP_NAME)
        name.setObjectName("appName")
        logo_row.addWidget(logo_icon)
        logo_row.addWidget(name)
        logo_row.addStretch()
        lay.addLayout(logo_row)
        lay.addSpacing(20)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for key, label, icon_name, _tip in NAV_ITEMS:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            c = theme.current()
            btn.setIcon(nav_icon(icon_name, c["primary"], c["subtext"], 18))
            btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            self._nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch()
        version = QLabel(f"v{config.APP_VERSION} · M2")
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignCenter)
        lay.addWidget(version)
        return sidebar

    def _build_titlebar(self) -> _TitleBar:
        self.titlebar = _TitleBar(self)
        # 同步引用，便于 _tick / 天气 / 主题等方法访问
        self.date_label = self.titlebar.date_label
        self.clock_label = self.titlebar.clock_label
        self.weather_chip = self.titlebar.weather_chip
        self.weather_icon = self.titlebar.weather_icon
        self.weather_text = self.titlebar.weather_text
        self.theme_btn = self.titlebar.theme_btn
        self._refresh_theme_icon()
        return self.titlebar

    def _build_stack(self) -> QStackedWidget:
        self.stack = QStackedWidget()
        self._pages["dashboard"] = DashboardPage()
        self.stack.addWidget(self._pages["dashboard"])

        exp_page = ExperimentsPage()
        exp_page.open_experiment.connect(self.open_experiment)
        exp_page.new_experiment.connect(lambda: self.open_edit(None))
        exp_page.edit_experiment.connect(self.open_edit)
        self._pages["experiments"] = exp_page
        self.stack.addWidget(exp_page)

        self._pages["planner"] = PlannerPage()
        self.stack.addWidget(self._pages["planner"])

        weekly_page = WeeklyReviewPage()
        weekly_page.open_experiment.connect(lambda eid: self.open_experiment(eid, "weekly"))
        self._pages["weekly"] = weekly_page
        self.stack.addWidget(weekly_page)

        settings_page = SettingsPage()
        settings_page.theme_changed.connect(self.apply_theme)
        settings_page.weather_changed.connect(lambda: self.weather.refresh())
        self._pages["settings"] = settings_page
        self.stack.addWidget(settings_page)
        return self.stack

    # ------------------------------------------------------------------ 托盘

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        show_act = menu.addAction("显示主窗口")
        show_act.triggered.connect(self.show_and_raise)
        new_act = menu.addAction("快速新建实验")
        new_act.triggered.connect(lambda: self.open_edit(None))
        menu.addSeparator()
        quit_act = menu.addAction("退出")
        quit_act.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(config.APP_NAME)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_and_raise()

    def show_and_raise(self) -> None:
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        if not self._maybe_prompt_backup():
            return
        self._allow_close = True
        if self.tray is not None:
            self.tray.hide()
        QApplication.instance().quit()

    def _maybe_prompt_backup(self) -> bool:
        """退出前检查今天是否备份过，没备份则提示。返回 True 表示可继续退出。"""
        from PySide6.QtWidgets import QMessageBox

        today = datetime.now().strftime("%Y-%m-%d")
        last = get_setting("last_backup_at", "") or ""
        if last.startswith(today):
            return True
        ret = QMessageBox.question(
            self, config.APP_NAME,
            "今天还没有备份数据，是否现在备份？\n\n"
            "（备份后数据更安全，选“取消”则不退出）",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if ret == QMessageBox.Yes:
            try:
                backup_service.backup()
            except Exception:
                pass
            return True
        if ret == QMessageBox.No:
            return True
        return False  # Cancel

    def closeEvent(self, event) -> None:
        if self.tray is not None and self.tray.isVisible() and not self._allow_close:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                config.APP_NAME, "已最小化到托盘，提醒仍会正常触发。",
                QSystemTrayIcon.Information, 3000,
            )
        else:
            event.accept()

    # ------------------------------------------------------------------ 导航

    def switch_page(self, key: str) -> None:
        """切换内容页并高亮对应导航按钮。"""
        btn = self._nav_buttons.get(key)
        page = self._pages.get(key)
        if btn is None or page is None:
            return
        btn.setChecked(True)
        self.stack.setCurrentWidget(page)
        self._fade_in(page)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _fade_in(self, widget: QWidget) -> None:
        """页面切换淡入动画（120ms）。"""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(120)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._page_anim = anim  # 保持引用防止被 GC

    def open_experiment(self, exp_id: int, return_key: str = "experiments") -> None:
        """打开（或刷新）实验详情页；返回时回到来源页面。"""
        self._detail_return_key = return_key
        if self._detail_page is None:
            self._detail_page = ExperimentDetailPage()
            self._detail_page.back_requested.connect(self._back_from_detail)
            self._detail_page.edit_requested.connect(self.open_edit)
            self._detail_page.deleted.connect(self._on_detail_deleted)
            self.stack.addWidget(self._detail_page)
        self._detail_page.load(exp_id)
        for b in self._nav_buttons.values():
            b.setChecked(False)
        self.stack.setCurrentWidget(self._detail_page)

    def _back_from_detail(self) -> None:
        self.switch_page(self._detail_return_key)

    def open_edit(self, exp_id: int | None = None) -> None:
        """打开新建 / 编辑实验对话框。"""
        dlg = ExperimentEditDialog(exp_id, self)
        if dlg.exec() == QDialog.Accepted:
            self._pages["experiments"].refresh()
            if self._detail_page is not None and self._detail_page.exp_id is not None:
                self._detail_page.load(self._detail_page.exp_id)

    def _on_detail_deleted(self, _exp_id: int) -> None:
        self._pages["experiments"].refresh()
        self.switch_page("experiments")

    # ------------------------------------------------------------------ 提醒

    def _on_reminder(self, evt: dict) -> None:
        sound_gen.play()
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(
                config.APP_NAME,
                f"{evt['message']}：{evt['title']}",
                QSystemTrayIcon.Information,
                5000,
            )
        self._popups = [p for p in self._popups if p.isVisible()]

        def _confirm() -> None:
            # 用户点了“知道了/查看详情”，确认后停止到点提醒的重复响铃
            if evt["kind"] == "on_time":
                self.reminder.mark_confirmed(evt["experiment_id"], evt["kind"])

        popup = ReminderPopup(
            evt["message"], evt["title"],
            on_view=lambda: self.open_experiment(evt["experiment_id"]),
            on_confirm=_confirm,
            auto_close=(evt["kind"] != "on_time"),
        )
        self._popups.append(popup)
        popup.show_top_right()

    # ------------------------------------------------------------------ 时钟 / 跨日

    def _tick(self) -> None:
        """每秒刷新：时钟 HH:MM:SS + 中文日期。"""
        now = datetime.now()
        self.clock_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(time_utils.format_date_cn(now))

    def _check_day(self) -> None:
        """每 30 秒检查是否跨零点。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_day:
            log.info("检测到跨零点：%s -> %s", self._current_day, today)
            self._current_day = today
            self._tick()
            self.day_changed.emit(today)

    def _check_auto_backup(self) -> None:
        """每日自动备份：到设定时间且当天尚未备份过则备份一次。"""
        if not get_setting("auto_backup_enabled", False):
            return
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        hour = get_setting("auto_backup_hour", "21:00") or "21:00"
        last = get_setting("last_backup_at", "") or ""
        if now.strftime("%H:%M") >= hour and not last.startswith(today):
            try:
                path = backup_service.backup()
                set_setting("last_backup_at", f"{today} {now.strftime('%H:%M')}")
                log.info("每日自动备份完成: %s", path)
            except Exception as exc:
                log.warning("每日自动备份失败: %s", exc)

    def _on_day_changed(self, new_date: str) -> None:
        """跨零点全量刷新：结转（可选）→ 今日记录 → 今日实验 → 周整理（预留）→ 提醒重扫。"""
        # 1. 未完成实验结转到新一天（设置开关）
        if get_setting("carry_over_enabled", False):
            yesterday = (datetime.strptime(new_date, "%Y-%m-%d") - timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            notes = daily_log.carry_over_unfinished(yesterday, new_date)
            if notes:
                daily_log.append_content(new_date, "【自动结转】" + "；".join(notes))
        # 2. 确保今日记录存在（dashboard.refresh 检测日期变化会重载内容）
        daily_log.get_or_create(new_date)
        # 3. 刷新今日记录 + 今日实验
        dash = self._pages.get("dashboard")
        if dash is not None and callable(getattr(dash, "refresh", None)):
            dash.refresh()
        # 4. 周整理 + 实验规划刷新
        for key in ("weekly", "planner"):
            page = self._pages.get(key)
            if page is not None and callable(getattr(page, "refresh", None)):
                page.refresh()
        # 5. 提醒队列立即重扫（新一天可能有到点的实验）
        self.reminder.check()

    # ------------------------------------------------------------------ 主题

    def apply_theme(self, name: str) -> None:
        """切换主题并刷新所有依赖主题的控件。"""
        self._theme = name
        theme.apply(QApplication.instance(), name)
        set_setting("theme", name)
        self._refresh_theme_icon()
        self._recolor_nav_icons()
        self.titlebar.refresh_theme()
        self.weather_icon.setPixmap(render_pixmap("cloud", "#FFFFFF", 22, directory=config.WEATHER_ICONS_DIR))
        for page in self._pages.values():
            hook = getattr(page, "on_theme_changed", None)
            if callable(hook):
                hook()
        if self._detail_page is not None:
            hook = getattr(self._detail_page, "on_theme_changed", None)
            if callable(hook):
                hook()

    def toggle_theme(self) -> None:
        self.apply_theme("dark" if self._theme == "light" else "light")

    # ------------------------------------------------------------------ 天气显示

    def _on_weather_ready(self, data: dict) -> None:
        c = theme.current()
        icon = data.get("icon", "cloud")
        self.weather_icon.setPixmap(render_pixmap(icon, "#FFFFFF", 22, directory=config.WEATHER_ICONS_DIR))
        parts = []
        if data.get("city"):
            parts.append(str(data["city"]))
        parts.append(f"{data.get('temp', '—')}°C")
        if data.get("text"):
            parts.append(str(data["text"]))
        self.weather_text.setText("  ".join(parts))
        src = "缓存" if data.get("from_cache") else data.get("provider", "")
        self.weather_text.setToolTip(f"更新于 {data.get('updated_at', '')}（{src}）")

    def _on_weather_failed(self, err: str) -> None:
        c = theme.current()
        self.weather_icon.setPixmap(render_pixmap("cloud", "#FFFFFF", 22, directory=config.WEATHER_ICONS_DIR))
        self.weather_text.setText("天气获取失败" if err != "天气未启用" else "天气未启用")
        self.weather_text.setToolTip(err)

    def _refresh_theme_icon(self) -> None:
        """暗色主题下显示太阳（点击切回亮色），亮色显示月亮。"""
        c = theme.current()
        icon_name = "sun" if self._theme == "dark" else "moon"
        self.theme_btn.setIcon(svg_icon(icon_name, c["subtext"], 20))

    def _recolor_nav_icons(self) -> None:
        c = theme.current()
        for key, btn in self._nav_buttons.items():
            btn.setIcon(nav_icon(NAV_ICONS[key], c["primary"], c["subtext"], 18))

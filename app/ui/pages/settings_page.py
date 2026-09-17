"""设置页：外观 / 提醒默认 / 每日记录 / 天气 / 数据（备份恢复）。

所有设置项即时读写 settings 表（database.set_setting），重启生效；
主题切换即时全局生效，天气配置变更后触发刷新。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...database import get_setting, set_setting
from ...services import backup_service
from ..components import Card


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    weather_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        title = QLabel("设置")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        # 外观
        outer.addWidget(self._appearance_card())
        # 提醒默认 + 每日记录
        outer.addWidget(self._remind_card())
        # 天气
        outer.addWidget(self._weather_card())
        # 数据
        outer.addWidget(self._data_card())
        outer.addStretch()

        scroll.setWidget(container)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _card(self, title: str) -> tuple[Card, QVBoxLayout]:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lbl = QLabel(title)
        lbl.setObjectName("cardTitle")
        lay.addWidget(lbl)
        return card, lay

    def _appearance_card(self) -> Card:
        card, lay = self._card("外观")
        row = QHBoxLayout()
        row.setSpacing(20)
        self.light_radio = QRadioButton("亮色")
        self.dark_radio = QRadioButton("暗色")
        self._theme_group = QButtonGroup(self)
        self._theme_group.addButton(self.light_radio)
        self._theme_group.addButton(self.dark_radio)
        self.light_radio.toggled.connect(self._on_theme_toggled)
        row.addWidget(self.light_radio)
        row.addWidget(self.dark_radio)
        row.addStretch()
        lay.addLayout(row)
        return card

    def _remind_card(self) -> Card:
        card, lay = self._card("提醒默认值")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("提前"))
        self.advance_spin = QSpinBox()
        self.advance_spin.setRange(0, 720)
        self.advance_spin.setSuffix(" 分钟")
        self.advance_spin.valueChanged.connect(
            lambda v: set_setting("remind_default_advance_min", v))
        row.addWidget(self.advance_spin)
        self.on_time_check = QCheckBox("到点提醒（默认开启）")
        self.on_time_check.toggled.connect(
            lambda v: set_setting("remind_default_on_time", bool(v)))
        row.addWidget(self.on_time_check)
        row.addStretch()
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.carry_check = QCheckBox("未完成实验自动结转到下一天")
        self.carry_check.toggled.connect(
            lambda v: set_setting("carry_over_enabled", bool(v)))
        row2.addWidget(self.carry_check)
        row2.addStretch()
        lay.addLayout(row2)

        # 到点未确认的重复响铃间隔
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        row3.addWidget(QLabel("到点未确认重复响铃间隔"))
        self.repeat_interval_spin = QSpinBox()
        self.repeat_interval_spin.setRange(5, 600)
        self.repeat_interval_spin.setSuffix(" 秒")
        self.repeat_interval_spin.valueChanged.connect(
            lambda v: set_setting("remind_repeat_interval_sec", v))
        row3.addWidget(self.repeat_interval_spin)
        row3.addStretch()
        lay.addLayout(row3)

        # 提示音选择
        sound_row = QHBoxLayout()
        sound_row.setSpacing(8)
        sound_row.addWidget(QLabel("提示音"))
        self.sound_path_label = QLabel("默认")
        self.sound_path_label.setObjectName("muted")
        choose_btn = QPushButton("选择铃声…")
        choose_btn.setCursor(Qt.PointingHandCursor)
        choose_btn.clicked.connect(self._choose_sound)
        reset_btn = QPushButton("恢复默认")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_sound)
        sound_row.addWidget(self.sound_path_label)
        sound_row.addWidget(choose_btn)
        sound_row.addWidget(reset_btn)
        sound_row.addStretch()
        lay.addLayout(sound_row)
        return card

    def _weather_card(self) -> Card:
        card, lay = self._card("天气")
        row = QHBoxLayout()
        self.weather_check = QCheckBox("启用天气")
        self.weather_check.toggled.connect(self._on_weather_toggled)
        row.addWidget(self.weather_check)
        row.addStretch()
        lay.addLayout(row)

        form_row = QHBoxLayout()
        form_row.setSpacing(8)
        form_row.addWidget(QLabel("服务商"))
        self.provider_combo = QComboBox()
        for key, label in (("qweather", "和风 QWeather"), ("openweathermap", "OpenWeatherMap"),
                           ("wttr", "wttr.in（免 Key）")):
            self.provider_combo.addItem(label, key)
        self.provider_combo.currentIndexChanged.connect(self._on_weather_config)
        form_row.addWidget(self.provider_combo)
        form_row.addSpacing(10)
        form_row.addWidget(QLabel("城市"))
        self.city_edit = QLineEdit()
        self.city_edit.setFixedWidth(120)
        self.city_edit.textChanged.connect(self._on_weather_city)
        form_row.addWidget(self.city_edit)
        form_row.addSpacing(10)
        form_row.addWidget(QLabel("更新间隔"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 240)
        self.interval_spin.setSuffix(" 分钟")
        self.interval_spin.valueChanged.connect(
            lambda v: set_setting("weather_update_min", v))
        form_row.addWidget(self.interval_spin)
        form_row.addStretch()
        lay.addLayout(form_row)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("和风 / OpenWeatherMap 需要；wttr.in 可留空")
        self.key_edit.textChanged.connect(
            lambda t: set_setting("weather_api_key", t.strip()))
        key_row.addWidget(self.key_edit, 1)
        lay.addLayout(key_row)

        tip = QLabel("无 Key 时自动回退 wttr.in；天气失败不影响其他功能。")
        tip.setObjectName("muted")
        lay.addWidget(tip)
        return card

    def _data_card(self) -> Card:
        card, lay = self._card("数据")
        row = QHBoxLayout()
        row.setSpacing(8)
        backup_btn = QPushButton("立即备份")
        backup_btn.clicked.connect(self._do_backup_default)
        backup_to_btn = QPushButton("备份到指定位置…")
        backup_to_btn.clicked.connect(self._do_backup_custom)
        restore_btn = QPushButton("恢复备份")
        restore_btn.clicked.connect(self._do_restore)
        row.addWidget(backup_btn)
        row.addWidget(backup_to_btn)
        row.addWidget(restore_btn)
        row.addStretch()
        lay.addLayout(row)

        auto_row = QHBoxLayout()
        auto_row.setSpacing(8)
        self.auto_backup_check = QCheckBox("每日自动备份")
        self.auto_backup_check.toggled.connect(
            lambda v: set_setting("auto_backup_enabled", bool(v)))
        auto_row.addWidget(self.auto_backup_check)
        auto_row.addWidget(QLabel("备份时间"))
        self.backup_time_edit = QTimeEdit()
        self.backup_time_edit.setDisplayFormat("HH:mm")
        self.backup_time_edit.timeChanged.connect(self._on_backup_time_changed)
        auto_row.addWidget(self.backup_time_edit)
        auto_row.addStretch()
        lay.addLayout(auto_row)

        help_text = QLabel(
            "· 手动备份：点「立即备份」存到 data/backups/（与自动备份同位置）；\n"
            "   点「备份到指定位置…」可存到 U 盘 / 网盘等任意位置。\n"
            "· 自动备份：勾选「每日自动备份」并设好时间，软件运行期间到点自动备份到 data/backups/。")
        help_text.setObjectName("muted")
        help_text.setWordWrap(True)
        lay.addWidget(help_text)

        tip = QLabel(f"数据目录：{config.DATA_DIR}")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return card

    # ------------------------------------------------------------------ 加载 / 行为

    def _load(self) -> None:
        self._loading = True
        self.light_radio.setChecked(get_setting("theme", "light") == "light")
        self.dark_radio.setChecked(get_setting("theme", "light") == "dark")
        self.advance_spin.setValue(int(get_setting("remind_default_advance_min", 10) or 0))
        self.on_time_check.setChecked(bool(get_setting("remind_default_on_time", True)))
        self.repeat_interval_spin.setValue(int(get_setting("remind_repeat_interval_sec", 5) or 5))
        self.carry_check.setChecked(bool(get_setting("carry_over_enabled", False)))
        self.weather_check.setChecked(bool(get_setting("weather_enabled", False)))
        idx = self.provider_combo.findData(get_setting("weather_provider", "qweather"))
        self.provider_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.city_edit.setText(get_setting("weather_city", "北京"))
        self.key_edit.setText(get_setting("weather_api_key", ""))
        self.interval_spin.setValue(int(get_setting("weather_update_min", 30) or 30))
        self.auto_backup_check.setChecked(bool(get_setting("auto_backup_enabled", False)))
        self.backup_time_edit.setTime(
            QTime.fromString(get_setting("auto_backup_hour", "21:00") or "21:00", "HH:mm"))
        self._refresh_sound_label()
        self._loading = False

    def _on_theme_toggled(self) -> None:
        if getattr(self, "_loading", False):
            return
        name = "dark" if self.dark_radio.isChecked() else "light"
        set_setting("theme", name)
        # 主题由 MainWindow.apply_theme 统一应用（需作用于 QApplication 全局）
        self.theme_changed.emit(name)

    def _on_weather_toggled(self, checked: bool) -> None:
        if getattr(self, "_loading", False):
            return
        set_setting("weather_enabled", bool(checked))
        self.weather_changed.emit()

    def _on_weather_config(self) -> None:
        if getattr(self, "_loading", False):
            return
        set_setting("weather_provider", self.provider_combo.currentData())
        self.weather_changed.emit()

    def _on_weather_city(self) -> None:
        if getattr(self, "_loading", False):
            return
        set_setting("weather_city", self.city_edit.text().strip())
        self.weather_changed.emit()

    def _on_backup_time_changed(self, t: QTime) -> None:
        if getattr(self, "_loading", False):
            return
        set_setting("auto_backup_hour", t.toString("HH:mm"))

    # ------------------------------------------------------------------ 提示音

    def _choose_sound(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "选择提示音", "", "音频文件 (*.wav *.mp3)")
        if not path:
            return
        import shutil

        dest_dir = config.DATA_DIR / "sounds"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(path).name
        shutil.copy2(path, dest)
        set_setting("remind_sound_path", str(dest))
        self._refresh_sound_label()

    def _reset_sound(self) -> None:
        set_setting("remind_sound_path", "")
        self._refresh_sound_label()

    def _refresh_sound_label(self) -> None:
        p = get_setting("remind_sound_path", "") or ""
        self.sound_path_label.setText(Path(p).name if p else "默认")

    def _do_backup_default(self) -> None:
        """一键备份到默认位置 data/backups/（与自动备份同一位置）。"""
        try:
            path = backup_service.backup()
            QMessageBox.information(self, config.APP_NAME, f"备份成功：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, config.APP_NAME, f"备份失败：{exc}")

    def _do_backup_custom(self) -> None:
        """备份到用户指定的位置（U 盘 / 网盘文件夹等）。"""
        from PySide6.QtWidgets import QFileDialog

        default_name = f"实验助手备份_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "备份到…（可选 U 盘 / 网盘文件夹）", str(Path.home() / default_name),
            "备份文件 (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            backup_service.backup(path)
            QMessageBox.information(self, config.APP_NAME, f"备份成功：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, config.APP_NAME, f"备份失败：{exc}")

    def _do_restore(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        backups = backup_service.list_backups()
        if not backups:
            QMessageBox.information(self, config.APP_NAME, "暂无备份文件。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", str(config.BACKUPS_DIR), "备份 (*.zip)")
        if not path:
            return
        if not backup_service.validate_backup(path):
            QMessageBox.critical(self, config.APP_NAME, "备份文件无效或已损坏。")
            return
        ret = QMessageBox.question(
            self, config.APP_NAME,
            "恢复将覆盖当前数据（数据库、图片、附件）。\n恢复后请重启应用。是否继续？")
        if ret != QMessageBox.Yes:
            return
        try:
            backup_service.restore(path)
            QMessageBox.information(
                self, config.APP_NAME, "恢复完成，请重启应用以加载数据。")
        except Exception as exc:
            QMessageBox.critical(self, config.APP_NAME, f"恢复失败：{exc}")

    def refresh(self) -> None:
        """切回设置页时同步最新设置。"""
        self._load()

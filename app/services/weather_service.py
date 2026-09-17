"""天气服务：三源回退（和风 QWeather → OpenWeatherMap → wttr.in）。

- 网络请求在 QThread 子线程执行，绝不阻塞主线程
- 结果本地缓存到 data/weather_cache.json，离线显示上次缓存
- 任何源失败都静默回退，最终失败只发 failed 信号，不弹错误
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal

from .. import config
from ..database import get_setting, set_setting

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (LabLog/0.1)"


def _http_get_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _map_icon(raw) -> str:
    """把各源天气代码归一为图标名：sun/cloud/rain/snow/thunder/fog/wind。"""
    c = str(raw)
    if c.startswith("1") or c in ("01d", "01n", "113", "0"):
        return "sun"
    if c.startswith("3") or c in ("10d", "10n", "09d", "09n", "176", "263", "266", "293",
                                  "299", "305", "306", "307", "308", "309"):
        return "rain"
    if c.startswith("4") or c.startswith("5") or c in ("13d", "13n", "326", "329", "332",
                                                       "335", "338", "350", "371"):
        return "snow"
    if c.startswith("2") and len(c) > 1 and c[1] in "012" or c in ("11d", "11n", "200",
                                                                    "201", "202", "230"):
        return "thunder"
    if c in ("04d", "04n", "143", "248", "260"):
        return "fog"
    return "cloud"


def _fetch_qweather(city: str, key: str) -> dict | None:
    if not key:
        return None
    url = ("https://devapi.qweather.com/v7/weather/now?location="
           f"{urllib.parse.quote(city)}&key={key}")
    data = _http_get_json(url)
    if data.get("code") == "200" and data.get("now"):
        now = data["now"]
        return {"temp": float(now.get("temp", 0)), "text": now.get("text", ""),
                "icon": _map_icon(now.get("icon", "")), "provider": "qweather"}
    return None


def _fetch_openweather(city: str, key: str) -> dict | None:
    if not key:
        return None
    url = ("https://api.openweathermap.org/data/2.5/weather?q="
           f"{urllib.parse.quote(city)}&appid={key}&units=metric&lang=zh_cn")
    data = _http_get_json(url)
    if data.get("main") and data.get("weather"):
        return {"temp": float(data["main"].get("temp", 0)),
                "text": data["weather"][0].get("description", ""),
                "icon": _map_icon(data["weather"][0].get("icon", "")),
                "provider": "openweathermap"}
    return None


def _fetch_wttr(city: str, _key: str = "") -> dict | None:
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=zh"
    data = _http_get_json(url)
    cur = (data.get("current_condition") or [{}])[0]
    if cur.get("temp_C") is not None:
        desc = ""
        for d in cur.get("lang_zh", []) or []:
            desc = d.get("value", "")
            break
        return {"temp": float(cur["temp_C"]), "text": desc,
                "icon": _map_icon(cur.get("weatherCode", "")), "provider": "wttr"}
    return None


class _FetchThread(QThread):
    """子线程：按三源顺序抓取，第一个成功的返回。"""

    done = Signal(object, str)  # (data_dict | None, error_str)

    def __init__(self, city: str, key: str, parent=None):
        super().__init__(parent)
        self._city = city
        self._key = key

    def run(self) -> None:
        for fetch in (_fetch_qweather, _fetch_openweather, _fetch_wttr):
            try:
                data = fetch(self._city, self._key)
                if data:
                    self.done.emit(data, "")
                    return
            except Exception as exc:  # 单源失败继续回退
                log.debug("天气源 %s 失败: %s", fetch.__name__, exc)
        self.done.emit(None, "所有天气源均获取失败")


class WeatherService(QObject):
    """天气服务：refresh() 触发子线程抓取，结果经信号回主线程。"""

    ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: _FetchThread | None = None

    def refresh(self) -> None:
        if not get_setting("weather_enabled", False):
            self.failed.emit("天气未启用")
            return
        if self._thread is not None and self._thread.isRunning():
            return
        city = get_setting("weather_city", "北京") or "北京"
        key = get_setting("weather_api_key", "") or ""
        self._thread = _FetchThread(city, key)
        self._thread.done.connect(self._on_done)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self) -> None:
        """线程结束后清空引用，避免下次 refresh 访问已删除对象。"""
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()

    def _on_done(self, data: dict | None, err: str) -> None:
        if data:
            data["city"] = get_setting("weather_city", "北京")
            data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._save_cache(data)
            self.ready.emit(data)
            return
        cached = self.load_cache()
        if cached:
            cached["from_cache"] = True
            self.ready.emit(cached)
        else:
            self.failed.emit(err)

    def load_cache(self) -> dict | None:
        try:
            return json.loads(config.WEATHER_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_cache(self, data: dict) -> None:
        try:
            config.WEATHER_CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            set_setting("last_weather_at", data.get("updated_at", ""))
        except Exception as exc:
            log.debug("天气缓存写入失败: %s", exc)

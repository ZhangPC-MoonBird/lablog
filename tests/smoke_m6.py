"""M6 冒烟测试（离屏运行，临时数据库隔离）：
- 跟随实验：一对多创建、主实验改时间后自动平移、删除级联
- 模板保存跟随实验规格
- 规划项“实验模式”转实验：目标/步骤/标签/提醒/跟随完整带入
- 规划项改时间/改字段 → 已关联实验同步，跟随实验一起平移
- 实验 → 规划去重与完整字段回写
- 实验总览页面、实验编辑对话框、规划项对话框可正常构建

运行：python tests/smoke_m6.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtCore import QDate, QTime, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTextBrowser

from app import config
from app.database import init_db
from app.models import experiment, template, weekly
from app.ui import theme
from app.ui.components import TextViewDialog
from app.ui.main_window import MainWindow
from app.ui.pages.experiment_edit import ExperimentEditDialog
from app.ui.pages.experiment_form import ExperimentCoreForm
from app.ui.pages.overview import OverviewPage
from app.ui.pages.planner import PlanItemDialog
from app.utils import time_utils

# ---- 临时数据库隔离 ----
tmp = Path(tempfile.mkdtemp(prefix="lablog_m6_"))
config.DATA_DIR = tmp
config.DB_PATH = tmp / "lab.db"
config.IMAGES_DIR = tmp / "images"
config.FILES_DIR = tmp / "files"
config.BACKUPS_DIR = tmp / "backups"
config.EXPORTS_DIR = tmp / "exports"
config.SOUND_FILE = tmp / "reminder.wav"
config.WEATHER_CACHE = tmp / "weather_cache.json"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def main() -> int:
    app = QApplication(sys.argv)
    init_db()
    theme.apply(app, "light")

    # ---- 1. 跟随实验：一对多 + 自动时间 + 改主实验时间 ----
    parent_id = experiment.create({
        "title": "主实验", "type": "细胞培养", "goal": "看表达",
        "steps": "1. 铺板\n2. 转染", "planned_start": "2026-11-03 09:00",
        "duration_min": 120, "priority": "high",
    })
    specs = [
        {"title": "24h 测量", "type": "测量", "offset_min": 0,
         "duration_min": 24 * 60, "notes": "到点取样",
         "goal": "检测 CCR2 表达", "steps": "1. 取样\n2. 离心\n3. 上机"},
        {"title": "48h 复测", "type": "测量", "offset_min": 120,
         "duration_min": 60, "notes": "", "goal": "", "steps": ""},
    ]
    synced = experiment.sync_followups(parent_id, specs)
    followups = experiment.list_followups(parent_id)
    check("跟随实验创建两条", len(followups) == 2, str(len(followups)))
    check("跟随实验返回真实 id", all(s.get("id") for s in synced))
    starts = [f["planned_start"] for f in followups]
    check("跟随时间=主实验结束后+偏移", starts == ["2026-11-03 11:00", "2026-11-03 13:00"], str(starts))
    check("跟随耗时独立", [f["duration_min"] for f in followups] == [1440, 60])
    check("跟随实验保存目标", followups[0]["goal"] == "检测 CCR2 表达")
    check("跟随实验保存多步骤", followups[0]["steps"].count("\n") == 2)
    check("主实验跟随计数", experiment.followup_count(parent_id) == 2)

    # 跟随间隔支持“天 + 小时 + 分钟”
    parent_days = experiment.create({
        "title": "天级跟随主实验", "planned_start": "2026-11-03 09:00",
        "duration_min": 60,
    })
    experiment.sync_followups(parent_days, [{
        "title": "3天2小时后复测", "offset_min": 3 * 24 * 60 + 2 * 60,
        "duration_min": 24 * 60, "goal": "天级目标", "steps": "1. 第一天\n2. 第二天",
    }])
    fu_days = experiment.list_followups(parent_days)[0]
    check("跟随间隔支持天+小时", fu_days["planned_start"] == "2026-11-06 12:00",
          str(fu_days["planned_start"]))
    check("时长格式包含天", time_utils.format_duration(3 * 24 * 60 + 2 * 60) == "3天2小时")

    parent = experiment.get(parent_id)
    parent.update({"planned_start": "2026-11-03 10:00", "duration_min": 120})
    experiment.update(parent_id, parent)
    starts = [f["planned_start"] for f in experiment.list_followups(parent_id)]
    check("主实验时间变化跟随平移", starts == ["2026-11-03 12:00", "2026-11-03 14:00"], str(starts))

    # ---- 2. 实验总览查询 ----
    rows = experiment.list_for_overview()
    parent_row = next((r for r in rows if r["id"] == parent_id), None)
    check("总览包含主实验", parent_row is not None)
    check("总览显示跟随数量", parent_row is not None and parent_row["followup_count"] == 2)
    child_rows = [r for r in rows if r["parent_id"] == parent_id]
    check("总览包含跟随实验", len(child_rows) == 2)
    check("总览显示所属主实验", child_rows and child_rows[0]["parent_title"] == "主实验")

    # ---- 3. 模板保存跟随实验 ----
    tpl_id = template.create({
        "name": "24h 测量模板", "type": "细胞培养", "duration_min": 120,
        "goal": "模板目标", "steps": "模板步骤", "priority": "high",
        "remind_advance_min": 5, "remind_on_time": 1, "remind_end_min": 10,
        "followups": specs,
    })
    tpl = template.get(tpl_id)
    tpl_specs = template.followups_list(tpl)
    check("模板保存跟随实验", len(tpl_specs) == 2)
    check("模板保存跟随步骤", "取样" in tpl_specs[0].get("steps", ""))
    check("模板保存跟随目标", tpl_specs[0].get("goal") == "检测 CCR2 表达")

    # 跟随实验从模板添加：目标/步骤/耗时/优先级/提醒一起带入
    form = ExperimentCoreForm()
    combo = form.followup_editor.template_add_combo
    idx_tpl = combo.findData(tpl_id)
    check("跟随模板下拉存在", idx_tpl >= 0)
    combo.setCurrentIndex(idx_tpl)
    check("从模板添加跟随行", len(form.followup_editor._rows) == 1)
    row = form.followup_editor._rows[0]
    check("模板填充跟随标题", row["title"].text() == tpl["name"], row["title"].text())
    check("模板填充跟随步骤", "模板步骤" in row["steps"].toPlainText())
    ui_specs = form.followup_editor.specs()
    check("模板填充跟随优先级", ui_specs and ui_specs[0].get("priority") == "high")
    check("模板填充跟随提醒",
          ui_specs and ui_specs[0].get("remind_enabled") == 1
          and ui_specs[0].get("remind_advance_min") == 5
          and ui_specs[0].get("remind_end_min") == 10)
    tpl_parent = experiment.create({
        "title": "模板跟随主实验", "planned_start": "2026-11-08 10:00",
        "duration_min": 60,
    })
    experiment.sync_followups(tpl_parent, ui_specs)
    tpl_fu = experiment.list_followups(tpl_parent)[0]
    check("跟随模板优先级落库", tpl_fu["priority"] == "high")
    check("跟随模板提醒落库",
          tpl_fu["remind_enabled"] == 1 and tpl_fu["remind_advance_min"] == 5
          and tpl_fu["remind_end_min"] == 10)

    # ---- 4. 规划项“实验模式” -> 实验：完整字段带入 ----
    week_start = time_utils.monday_of(date(2026, 11, 3)).strftime("%Y-%m-%d")
    plan_id = weekly.create_item({
        "week_start": week_start, "title": "规划中的实验", "type": "分子克隆",
        "planned_date": "2026-11-04", "planned_start": "15:00", "duration_min": 90,
        "priority": "high", "notes": "规划备注", "is_experiment": 1,
        "goal": "规划目标", "steps": "规划步骤", "tags": ["质粒", "克隆"],
        "remind_enabled": 1, "remind_advance_min": 5, "remind_on_time": 1,
        "remind_end_min": 15, "followups": specs,
    })
    exp_id = weekly.convert_to_experiment(plan_id)
    exp = experiment.get(exp_id)
    check("规划转实验成功", exp is not None)
    check("规划目标带入实验", exp["goal"] == "规划目标")
    check("规划步骤带入实验", exp["steps"] == "规划步骤")
    check("规划标签带入实验", experiment.tags_to_str(exp) == "质粒, 克隆")
    check("规划提醒带入实验", exp["remind_advance_min"] == 5 and exp["remind_end_min"] == 15)
    check("规划跟随实验带入", len(experiment.list_followups(exp_id)) == 2)
    item = weekly.get_item(plan_id)
    check("规划项回写 linked_experiment_id", item["linked_experiment_id"] == exp_id)
    check("规划项回写跟随 id", all(s.get("id") for s in weekly._json_list(item["followups"])))

    # ---- 5. 规划项改动 -> 已关联实验同步 ----
    weekly.update_item(plan_id, {
        "title": "规划中的实验V2", "goal": "新目标",
        "planned_start": "16:00", "duration_min": 60,
        "followups": experiment.followup_specs(exp_id),
    })
    exp = experiment.get(exp_id)
    check("规划改标题同步实验", exp["title"] == "规划中的实验V2")
    check("规划改目标同步实验", exp["goal"] == "新目标")
    check("规划改时间同步实验", exp["planned_start"] == "2026-11-04 16:00")
    starts = [f["planned_start"] for f in experiment.list_followups(exp_id)]
    check("规划改时间跟随平移", starts == ["2026-11-04 17:00", "2026-11-04 19:00"], str(starts))

    # 跨天拖动规划项 -> 实验日期同步
    weekly.set_item_date_order(plan_id, "2026-11-06", 0)
    exp = experiment.get(exp_id)
    check("规划拖到另一天同步实验", exp["planned_start"] == "2026-11-06 16:00")
    starts = [f["planned_start"] for f in experiment.list_followups(exp_id)]
    check("拖动后跟随仍在同一天", starts == ["2026-11-06 17:00", "2026-11-06 19:00"], str(starts))

    # ---- 6. 实验 -> 规划：默认按实验开始日期，去重 ----
    item2 = weekly.convert_experiment_to_plan(exp_id)
    check("实验转规划复用原规划项", item2 == plan_id, f"{item2} vs {plan_id}")
    plan_item2 = weekly.get_item(item2)
    check("实验转规划默认使用开始日期", plan_item2["planned_date"] == "2026-11-06",
          str(plan_item2["planned_date"]))
    all_items = weekly.list_items_range("2026-11-02", "2026-11-08")
    linked = [it for it in all_items if it["linked_experiment_id"] == exp_id]
    check("实验转规划不重复创建", len(linked) == 1, str(len(linked)))

    # 跟随实验转规划也使用跟随实验自己的开始日期
    fu = experiment.list_followups(exp_id)[0]
    fu_item = weekly.convert_experiment_to_plan(fu["id"])
    fu_plan = weekly.get_item(fu_item)
    check("跟随实验转规划使用跟随开始日",
          fu_plan["planned_date"] == fu["planned_start"][:10],
          f"{fu_plan['planned_date']} vs {fu['planned_start'][:10]}")

    # ---- 7. 删除主实验级联删除跟随实验 ----
    child_ids = [f["id"] for f in experiment.list_followups(parent_id)]
    experiment.delete(parent_id)
    check("删除主实验", experiment.get(parent_id) is None)
    check("跟随实验级联删除", all(experiment.get(cid) is None for cid in child_ids))

    # ---- 8. UI 构建 ----
    win = MainWindow()
    win.show()
    check("总览页已注册", "overview" in win._pages and isinstance(win._pages["overview"], OverviewPage))
    win.switch_page("overview")
    check("总览页切换无异常", True)
    check("总览页有实验结果", len(win._pages["overview"]._exps) >= 2)

    # 到点提醒重复触发时不叠弹窗，点“知道了”后全部关闭
    import app.ui.main_window as mw_mod

    original_play = mw_mod.sound_gen.play
    mw_mod.sound_gen.play = lambda: None
    evt = {
        "experiment_id": exp_id, "title": "提醒弹窗测试", "kind": "on_time",
        "message": "到点提醒", "planned_start": "2026-11-09 10:00",
    }
    win._on_reminder(evt)
    win._on_reminder(evt)
    QTest.qWait(100)
    visible_popups = [p for p in win._popups if p.isVisible()]
    check("同一到点提醒只弹一个窗", len(visible_popups) == 1, str(len(visible_popups)))
    btn = None
    if visible_popups:
        btn = next(
            (b for b in visible_popups[0].findChildren(QPushButton) if b.text() == "知道了"),
            None,
        )
    check("提醒弹窗有知道了按钮", btn is not None)
    if btn is not None:
        btn.click()
    QTest.qWait(50)
    check("点击知道了后弹窗全部关闭",
          not any(p.isVisible() for p in win._popups))
    mw_mod.sound_gen.play = original_play

    dlg = ExperimentEditDialog(exp_id)
    check("实验编辑框载入跟随实验", len(dlg.form.followup_editor._rows) == 2)
    dlg.close()

    pdlg = PlanItemDialog("2026-11-06", item_id=plan_id)
    check("规划项实验模式", pdlg.mode_combo.currentData() == 1)
    check("规划项载入跟随实验", len(pdlg.exp_form.followup_editor._rows) == 2)
    pdlg.close()

    view_dlg = TextViewDialog("查看测试", "**加粗** 内容", markdown=True)
    browser = view_dlg.findChild(QTextBrowser)
    check("只读查看对话框可构建", view_dlg.windowTitle() == "查看测试")
    check("只读查看渲染 Markdown",
          browser is not None and "加粗" in browser.toPlainText())
    view_dlg.close()

    # ---- 9. 对话框真实保存 ----
    new_dlg = ExperimentEditDialog()
    new_dlg.form.title_edit.setText("对话框新建实验")
    new_dlg.form.date_edit.setDate(QDate(2026, 11, 9))
    new_dlg.form.time_edit.setTime(QTime(9, 0))
    new_dlg.form.hour_spin.setValue(1)
    new_dlg.form.goal_edit.setText("对话框目标")
    new_dlg.form.followup_editor.add_row()
    first_row = new_dlg.form.followup_editor._rows[0]
    first_row["title"].setText("对话框跟随")
    first_row["offset_d"].setValue(1)
    first_row["steps"].setPlainText("1. 取样\n2. 检测")
    new_dlg.accept()
    new_exp = experiment.get(new_dlg.saved_id)
    check("对话框保存实验", new_exp is not None and new_exp["title"] == "对话框新建实验")
    new_followups = experiment.list_followups(new_dlg.saved_id)
    check("对话框保存跟随实验", len(new_followups) == 1)
    check("对话框保存跟随步骤", "取样" in (new_followups[0]["steps"] if new_followups else ""))
    check("对话框跟随支持天级间隔",
          bool(new_followups) and new_followups[0]["planned_start"] == "2026-11-10 10:00",
          str(new_followups[0]["planned_start"] if new_followups else ""))

    new_plan = PlanItemDialog("2026-11-10")
    new_plan.mode_combo.setCurrentIndex(1)
    new_plan.exp_form.title_edit.setText("对话框规划实验")
    new_plan.exp_form.goal_edit.setText("规划对话框目标")
    new_plan.exp_form.date_edit.setDate(QDate(2026, 11, 10))
    new_plan.exp_form.time_edit.setTime(QTime(13, 0))
    new_plan.exp_form.hour_spin.setValue(2)
    new_plan.exp_form.followup_editor.add_row()
    plan_row = new_plan.exp_form.followup_editor._rows[0]
    plan_row["title"].setText("规划跟随")
    plan_row["steps"].setPlainText("规划步骤A\n规划步骤B")
    new_plan._accept()
    created_item = weekly.get_item(new_plan.saved_id)
    check("规划对话框保存实验字段", created_item["is_experiment"] == 1 and created_item["goal"] == "规划对话框目标")
    plan_specs = weekly._json_list(created_item["followups"])
    check("规划对话框保存跟随", len(plan_specs) == 1)
    check("规划对话框保存跟随步骤", plan_specs and "规划步骤A" in plan_specs[0].get("steps", ""))

    QTimer.singleShot(300, app.quit)
    app.exec()

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

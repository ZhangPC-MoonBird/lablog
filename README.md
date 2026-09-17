# 实验助手（LabLog）

一个**完全本地运行**的实验计划与记录助手桌面应用。帮科研/实验人员管理实验计划、到点提醒、实验记录（Markdown + 图片）、每日记录、周报整理和下周实验规划。

> 核心功能不依赖任何云服务；天气为**可选联网**功能，无网络时不影响其他功能。

## ✨ 功能特性

- **实验管理**：新建/编辑/删除实验，自动计算结束时间（含跨天，如 23:00 + 3h → 次日 02:00）
- **智能提醒**：提前提醒、到点提醒、结束前提醒；到点未确认会**按你设定的间隔重复响铃**（可自选铃声），锁屏也能响
- **实验记录**：文字 / Markdown / 图片（文件选择、拖拽、Ctrl+V 粘贴截图），图片自动压缩
- **实验结论**：每个实验可写结论（含图片），周报自动汇总
- **每日记录**：每天自动建一条，防抖自动保存
- **周整理**：自动汇总本周完成/进行中/记录/图片/超时，三栏手写总结，一键导出 **Markdown / HTML / Word**
- **实验规划**：下周七天格子视图，卡片按时序排列，拖拽跨天/跨周，一键转正式实验（自动带提醒）
- **天气**：三源回退（和风 QWeather → OpenWeatherMap → wttr.in），本地缓存，离线显示上次结果
- **数据安全**：SQLite 本地存储、手动备份到任意位置、每日自动备份、退出前备份提醒
- **界面**：无边框窗口、亮/暗主题、彩色天气图标、空状态插画

## 🛠 技术栈

Python 3.11+ · PySide6 (Qt6) · SQLite (WAL) · python-markdown · python-docx · PyInstaller

## 📥 直接使用（免安装版）

**不用装 Python、不用任何环境**，下载即用：

1. 到 [Releases](https://github.com/ZhangPC-MoonBird/lablog/releases) 下载 `实验助手_发布包.zip`
2. 解压到任意位置（如 D 盘）
3. 双击 `实验助手.exe` 即可运行

> - 数据自动保存在 exe 同级的 `data/` 文件夹（数据库、图片、备份都在里面）
> - 想备份/换电脑：直接把整个 `实验助手` 文件夹拷走即可，数据跟着走
> - 桌面快捷方式：右键 exe → 发送到 → 桌面快捷方式

## 🚀 源码运行（开发者）

```bash
pip install -r requirements.txt
python main.py
```

打包成 exe：

```bash
python build.py   # 自动备份数据 → 打包 → 恢复数据，安全
```

## 📁 目录结构

```
main.py               程序入口
app/                  应用代码（config / database / models / services / ui / utils）
assets/icons          本地 SVG 图标（原创）
assets/weather        彩色天气图标（原创）
assets/illustrations  空状态插画（原创）
docs/                 设计文档、里程碑
tests/                冒烟测试（离屏运行）
build.py              安全打包脚本
data/                 运行时数据（lab.db、images、files、backups、exports）
```

## 💾 数据

- 数据**全部本地**：数据库 `data/lab.db`，图片 `data/images/`，附件 `data/files/`，备份 `data/backups/`
- 数据是**标准 SQLite + 普通文件**，可完整迁移到新电脑（把 exe 文件夹 + data 一起拷走即可）
- 删除 `data/` 目录即清空全部数据，请先用「设置 → 立即备份」

## 📦 发布

源码不含打包产物（`dist/`、`data/` 已 gitignore）。发布 exe 时：

1. `python build.py` 生成 `dist/实验助手/`（exe + 使用说明）
2. 压缩成 zip，上传到 GitHub Releases 供他人下载

## 📄 许可

[MIT License](LICENSE)

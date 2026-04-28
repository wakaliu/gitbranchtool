# Git 拉线切线工具 (Git GUI Pull-Switch Tool)

跨平台 Git 图形化工具，专注于**本地工程管理**、**批量 Fetch** 和 **一键切分支 (Switch)** 操作。

专为 Unity/大型项目多仓库场景设计，支持 Windows 和 macOS (Intel & Apple Silicon)。

## 特性 (v1.0)

- 工程级管理：添加多个项目目录，自动扫描所有 Git 仓库
- 仓库列表：支持多选、拖拽排序、批量操作
- 一键切线：目标分支输入 + 收藏 + Stash 选项 + 强制更新
- 并行执行：多仓库同时处理，高效低占用
- 反馈直达 GitHub Issues
- 主题切换 (浅色/深色) + 中英双语
- 详细运行日志 + 耗时统计

## 安装与运行

```bash
pip install -r requirements.txt
python -m src.git_gui.main
```

## 打包成可执行程序

```bash
# 安装打包工具
pip install pyinstaller

# Windows
pyinstaller --onefile --windowed --name "GitPullSwitchTool" src/git_gui/main.py

# macOS (Universal2)
pyinstaller --onefile --windowed --name "GitPullSwitchTool" --target-arch universal2 src/git_gui/main.py
```

## 项目结构

```
src/git_gui/
├── main.py                 # 入口
├── config/                 # 配置管理
├── models/                 # 数据模型
├── core/                   # Git 业务逻辑 (核心)
├── ui/                     # UI 层 (完全解耦)
├── utils/                  # 通用工具
├── config.yaml             # 用户配置
└── ...
```

详细规范见 `.cursor/rules/python-qt-standards.mdc`。

## 后续计划

- 完整“新建拉线”功能
- 一键瘦身 (gc, prune, LFS)
- 更多 Git 操作
- 自动更新与插件系统

欢迎反馈！(菜单 → 反馈)

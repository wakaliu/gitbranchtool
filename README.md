# Git 拉线切线工具 (Git GUI Pull-Switch Tool)

跨平台 Git 图形化工具，专注于**本地工程管理**、**批量 Fetch** 和 **一键切分支 (Switch)** 操作。

专为 Unity/大型项目多仓库场景设计，支持 Windows 和 macOS (Intel & Apple Silicon)。

## 特性 (v1.0.1)

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

## 打包发布

### 产物说明

| 平台 | 便携形态 | 安装包 |
|------|-----------|--------|
| Windows | `dist/GitPullSwitchTool.exe`（onefile） | `dist/windows-installer/GitPullSwitchTool-Setup-*.exe`（Inno Setup） |
| macOS | `dist/macos-portable/GitPullSwitchTool.app`（onedir + `.app`） | `dist/macos-installer/GitPullSwitchTool.dmg`（`hdiutil`） |

- 默认配置与 `sausage_projects.yaml` 模板来自 [`src/git_gui/bundle_data/`](src/git_gui/bundle_data/)，由 PyInstaller 打入 `bundle_data/`；首次启动在用户目录生成可写 `config.yaml`（Windows：`%LOCALAPPDATA%\\GitPullSwitchTool\\`；macOS：`~/Library/Application Support/GitPullSwitchTool/`）。
- 图标可选：将 `assets/icon.ico` / `assets/icon.icns` 放入仓库后重新打包即可，见 [`assets/README.md`](assets/README.md)。
- 未做代码签名时，macOS 可能出现 Gatekeeper 拦截，可在「隐私与安全性」中放行或使用开发者证书签名/公证后分发。

### 本机构建

依赖：`pip install -r requirements.txt pyinstaller`；Windows 安装包另需 [Inno Setup 6](https://jrsoftware.org/isinfo.php)。

```powershell
# Windows（仓库根目录）
.\scripts\build_windows.ps1
```

```bash
# macOS（仓库根目录）
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

底层 spec 位于 [`packaging/pyinstaller/`](packaging/pyinstaller/)，便于与 `.gitignore` 中的通用 `build/` 临时目录区分。

### CI

推送 `v*` 标签或手动触发 **Build release** 工作流后，在 Actions 产物中下载 `windows-packages` / `macos-packages` 压缩包。

### 最小验收清单

1. 在未安装 Python 的机器上双击便携 exe 或安装后启动，主窗口可打开。
2. 主题切换、语言切换无报错。
3. 对任一本地 Git 仓库执行 Fetch / Switch 类操作可完成；日志区有输出。
4. 关闭应用后，用户目录下 `config.yaml` 已生成且再次启动设置保留。

## 项目结构

```
packaging/
├── pyinstaller/            # PyInstaller .spec
├── windows/              # Inno Setup 脚本
└── macos/                # DMG 封装脚本
scripts/
├── build_windows.ps1
└── build_macos.sh
src/git_gui/
├── main.py                 # 入口
├── bundle_data/            # 打包内置默认配置（只读）
├── config/                 # 配置管理
├── models/                 # 数据模型
├── core/                   # Git 业务逻辑 (核心)
├── ui/                     # UI 层 (完全解耦)
├── utils/                  # 通用工具
└── ...
config.yaml                 # 开发模式下仓库根目录用户配置（可选）
```

详细规范见 `.cursor/rules/python-qt-standards.mdc`。

## 后续计划

- 完整“新建拉线”功能
- 一键瘦身 (gc, prune, LFS)
- 更多 Git 操作
- 自动更新与插件系统

欢迎反馈！(菜单 → 反馈)

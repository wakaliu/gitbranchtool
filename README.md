# Git 拉线切线工具 (Git GUI Pull-Switch Tool)

跨平台 Git 图形化工具，专注于**本地工程管理**、**批量 Fetch** 和 **一键切分支 (Switch)** 操作。

专为 Unity/大型项目多仓库场景设计，支持 Windows 和 macOS (Intel & Apple Silicon)。

## 特性 (v1.0.2)

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
| Windows | `dist/GitPullSwitchTool.exe`（onefile） | `dist/windows-installer/GitPullSwitchTool-Setup-*.exe`；内部版另有 `GitPullSwitchTool-Sausage-Setup-*.exe` |
| macOS（公开） | `dist/macos-portable/GitPullSwitchTool.app` | `dist/macos-installer/GitPullSwitchTool.dmg` |
| macOS（内部） | `dist/macos-portable/GitPullSwitchTool-Sausage.app` | `dist/macos-installer/GitPullSwitchTool-Sausage.dmg` |

- 默认配置与 `sausage_projects.yaml` 模板来自 [`src/git_gui/bundle_data/`](src/git_gui/bundle_data/)，由 PyInstaller 打入 `bundle_data/`；首次启动在用户目录生成可写 `config.yaml`（Windows：`%LOCALAPPDATA%\\GitPullSwitchTool\\`；macOS：`~/Library/Application Support/GitPullSwitchTool/`）。
- 图标可选：将 `assets/icon.ico` / `assets/icon.icns` 放入仓库后重新打包即可，见 [`assets/README.md`](assets/README.md)。
- 未做代码签名时，macOS 可能出现 Gatekeeper 拦截，可在「隐私与安全性」中放行或使用开发者证书签名/公证后分发。
- **macOS 系统要求（打包版）**：当前依赖 **PySide6 6.5 / Qt 6.5**，官方预编译框架的最低系统为 **macOS 11（Big Sur）**（`QtCore` 等库为 `minos 11.0`）。**macOS 10.15（Catalina）及更早版本无法运行**，在 Intel 上会表现为启动即闪退或 dyld 报错，与「仅 M 芯片能开」无关，实为系统版本过低。
- **备注（旧系统兼容，当前未实施）**：无法在保留「单包 + 仅 PySide6」的前提下支持 10.15。若日后确有需求，可选方案包括：单独打 **legacy** 包（**PySide2 5.15 + Qt 5**，通常 **x86_64** 面向 Intel 旧机），或引入 **qtpy** 统一 import 后维护 **两套依赖与两次 PyInstaller**；自编译 Qt6 降 deployment target 成本高且不推荐。仓库当前不落地上述改造，仅作文档备忘。

### 本机构建

依赖：`pip install -r requirements.txt pyinstaller`；Windows 安装包另需 [Inno Setup 6](https://jrsoftware.org/isinfo.php)。

```powershell
# Windows（仓库根目录）：便携 exe + zip + Inno 安装包
.\scripts\build_windows.ps1

# 公开版 + 香肠内部版（各含便携 zip 与 Setup-*.exe）
.\scripts\build_windows_dual.ps1
```

安装包输出：`dist/windows-installer/GitPullSwitchTool-Setup-*.exe`、`GitPullSwitchTool-Sausage-Setup-*.exe`（需本机 [Inno Setup 6](https://jrsoftware.org/isinfo.php) 或 `winget install JRSoftware.InnoSetup`）。

```bash
# macOS（仓库根目录，universal2：M 芯片 + Intel）
chmod +x scripts/build_macos.sh scripts/build_macos_dual.sh
./scripts/build_macos.sh              # 公开版 + 内部版（根目录无 yaml 时用 bundle 模板临时复制，与 Windows 双轨一致）
./scripts/build_macos.sh --public-only # 仅公开版
```

内部版默认会再打一份 `GitPullSwitchTool-Sausage`（含对应 Inno Setup）：若仓库根已有 `sausage_projects.yaml`（勿提交 Git，见 `.gitignore`）则打入该文件；否则与 `scripts/build_windows_dual.ps1` 相同，临时复制 `src/git_gui/bundle_data/sausage_projects.yaml` 到根目录参与打包并在结束后删除。

底层 spec 位于 [`packaging/pyinstaller/`](packaging/pyinstaller/)，便于与 `.gitignore` 中的通用 `build/` 临时目录区分。

### CI

推送 `v*` 标签或手动触发 **Build release** 工作流后，在 Actions 产物中下载 `windows-packages` / `macos-packages` 压缩包。

### 应用内更新（打包版）

- **帮助 → 检查更新**：从 GitHub Releases 拉取版本列表，若存在比当前版本新且带对应安装包的 Release，可下载并退出后安装。
- **启动自动检查**（默认开启，可在 `config.yaml` 的 `update.check_on_startup` 关闭）：同一新版本仅自动提示一次；点「暂不更新」后写入 `update.auto_dismissed_version`，该版本下次启动不再弹窗。
- **API 节流**：`update.startup_check_cooldown_minutes`（默认 30）内重复启动不再次请求；命中 GitHub 限流后写入 `update.rate_limit_backoff_until`，退避期内手动/自动检查均不再访问 API（手动检查会提示剩余等待时间）。
- **Release 资产命名**（须与渠道、平台一致，否则不会提示更新）：
  - 公开版 Windows：`GitPullSwitchTool-Setup-{版本号}.exe`（版本号无 `v` 前缀，如 `1.0.3`）
  - 香肠内部版 Windows：`GitPullSwitchTool-Sausage-Setup-{版本号}.exe`
  - 公开版 macOS：`GitPullSwitchTool.dmg`
  - 香肠内部版 macOS：`GitPullSwitchTool-Sausage.dmg`
- macOS 未签名 DMG 更新后若被 Gatekeeper 拦截，请在「隐私与安全性」中放行；配置 GitHub Token 可提高 API 检查频率。

### 最小验收清单

1. 在未安装 Python 的机器上双击便携 exe 或安装后启动，主窗口可打开。
2. 主题切换、语言切换无报错。
3. 对任一本地 Git 仓库执行 Fetch / Switch 类操作可完成；日志区有输出。
4. 关闭应用后，用户目录下 `config.yaml` 已生成且再次启动设置保留。
5. （打包版）帮助 → 检查更新可正常请求 GitHub；有新版且 Release 含对应资产时可进入下载流程（可不真装完，仅验证弹窗与进度）。

## 项目结构

```
packaging/
├── pyinstaller/            # PyInstaller .spec
├── windows/              # Inno Setup 脚本
└── macos/                # DMG 封装脚本
scripts/
├── build_windows.ps1
├── build_windows_dual.ps1
├── build_macos.sh
└── build_macos_dual.sh
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

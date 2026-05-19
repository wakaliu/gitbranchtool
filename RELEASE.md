# 发版说明

## 版本号（单一来源）

编辑 `pyproject.toml` 中的 `version`，然后执行：

```powershell
python scripts/sync_version.py
```

会同步到 `constants.py`、`config.embedded.yaml`、`packaging/windows/GitPullSwitchTool.iss`。

## 检查更新（应用内）

- 菜单：**帮助 → 检查更新**（仅手动，不自动检查）
- 数据源：GitHub 公开仓库 Releases（默认 `github.repo`）
- Windows：优先打开 `GitPullSwitchTool-Setup-{version}.exe`
- macOS：打开 `.dmg` 或 Release 页面
- 测试预发布：在 **设置** 中勾选「包含预发布版本（测试用）」

## 本地打包

```powershell
# 公开 + 香肠内部双轨
.\scripts\build_windows_dual.ps1

# 仅公开版 + Inno 安装包（若已安装 Inno Setup 6）
.\scripts\build_windows.ps1
```

## 发布到 GitHub

### 正式版

```bash
git tag v1.0.3
git push origin v1.0.3
```

推送 `v*` 标签后，CI 会构建 Windows 安装包与 macOS DMG，并创建 GitHub Release 上传资产。

### 预发布（测试）

```bash
git tag v1.0.4-beta.1
git push origin v1.0.4-beta.1
```

标签名含 `-beta` / `-rc` 时，CI 将 Release 标记为 **Pre-release**。

## Release 资产命名约定

| 文件 | 用途 |
|------|------|
| `GitPullSwitchTool-Setup-{ver}.exe` | Windows 安装包（检查更新首选） |
| `GitPullSwitchTool.exe` | Windows 便携版（可选附件） |
| `GitPullSwitchTool.dmg` | macOS 安装镜像 |

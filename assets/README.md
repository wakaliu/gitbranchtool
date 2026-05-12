# 可选资源

- **`app_icon.png`**：应用窗口/任务栏图标源图（提交到仓库；同步一份到 `src/git_gui/bundle_data/` 供运行时与 PyInstaller 打入包内）。
- **`icon.ico`**：Windows 可执行文件图标，由 `app_icon.png` 生成（示例：`pip install pillow` 后执行下方命令），放入后重新运行 PyInstaller。
- **`icon.icns`**：macOS `.app` / DMG 图标。在 **macOS** 上执行 `bash scripts/macos_build_icns.sh`（依赖 `sips` / `iconutil`）由 `app_icon.png` 生成后提交到 `assets/`。

从 `app_icon.png` 生成多尺寸 `icon.ico`（Windows）：

```bash
python -c "from pathlib import Path; from PIL import Image; p=Path('assets/app_icon.png'); i=Image.open(p).convert('RGBA'); i.save(Path('assets/icon.ico'), format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(24,24),(16,16)])"
```

未放置 `icon.ico` 时 Windows 打包仍可通过，但 exe 使用 PyInstaller 默认图标。

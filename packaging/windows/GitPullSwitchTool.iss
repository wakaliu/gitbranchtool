; Inno Setup 安装包：将 PyInstaller 产出的 onefile exe 安装到 Program Files。
; 需要已安装 Inno Setup 6，或将 ISCC 加入 PATH；scripts/build_windows.ps1 会尝试常见安装路径。
#define MyAppName "GitPullSwitchTool"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "SausageDev"
#define MyAppExeName "GitPullSwitchTool.exe"

[Setup]
AppId={{B8F3A1D2-4E5C-4F6A-9B0D-1E2F3A4B5C6D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\windows-installer
OutputBaseFilename=GitPullSwitchTool-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; 应用内更新会先退出再跑 Setup；若仍检测到占用进程则强制结束，避免卡在「无法关闭应用」页
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 应用内更新由 apply_update_setup.bat 在静默安装后启动；交互安装仍可在向导末步勾选运行
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

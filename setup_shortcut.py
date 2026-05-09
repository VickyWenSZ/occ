import os, sys, platform, subprocess, pathlib, stat

proj    = pathlib.Path(__file__).parent.resolve()
system  = platform.system()

def windows():
    vbs     = proj / 'occ_launcher.vbs'
    ico     = proj / 'node' / 'apps' / 'gui' / 'static' / 'occ.ico'
    desktop = pathlib.Path(
        subprocess.check_output(
            ['powershell', '-NoProfile', '-Command',
             "[Environment]::GetFolderPath('Desktop')"],
            text=True
        ).strip()
    )
    lnk = desktop / 'OCC Node.lnk'
    ps  = f"""
$shell = New-Object -COM WScript.Shell
$lnk   = $shell.CreateShortcut('{lnk}')
$lnk.TargetPath   = '{vbs}'
$lnk.IconLocation = '{ico}'
$lnk.Description  = 'Launch OCC Node'
$lnk.Save()
""".strip()
    tmp = pathlib.Path(os.environ.get('TEMP', proj)) / 'occ_shortcut.ps1'
    tmp.write_text(ps, encoding='utf-8')
    subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(tmp)],
        check=True
    )
    tmp.unlink(missing_ok=True)
    print(f' [OK] Shortcut on Desktop: OCC Node')

def macos():
    desktop = pathlib.Path.home() / 'Desktop'
    cmd     = desktop / 'OCC Node.command'
    cmd.write_text(f'#!/bin/bash\ncd "{proj}"\nbash launch.sh\n', encoding='utf-8')
    cmd.chmod(cmd.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f' [OK] Shortcut on Desktop: OCC Node.command')

def linux():
    desktop = pathlib.Path.home() / 'Desktop'
    desktop.mkdir(exist_ok=True)
    icon    = proj / 'node' / 'apps' / 'gui' / 'static' / 'occ.png'
    df      = desktop / 'OCC Node.desktop'
    df.write_text(
        f'[Desktop Entry]\n'
        f'Type=Application\n'
        f'Name=OCC Node\n'
        f'Comment=Launch OCC Node\n'
        f'Exec="{proj}/launch.sh"\n'
        f'Icon={icon}\n'
        f'Terminal=false\n'
        f'Categories=Utility;\n',
        encoding='utf-8'
    )
    df.chmod(df.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f' [OK] Shortcut on Desktop: OCC Node.desktop')

if system == 'Windows':
    windows()
elif system == 'Darwin':
    macos()
else:
    linux()

# Build with: pyinstaller packaging/feishu-job-radar.spec
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("job_monitor")

a = Analysis(
    ["src/job_monitor/desktop_entry.py"],
    pathex=["src"],
    hiddenimports=hiddenimports,
    datas=[("data/jobs_seed.sqlite", "data")],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="FeishuJobRadar", console=False)

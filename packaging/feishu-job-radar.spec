# Build with: pyinstaller packaging/feishu-job-radar.spec
from PyInstaller.utils.hooks import collect_submodules
from pathlib import Path

hiddenimports = collect_submodules("job_monitor")
project_root = Path(SPECPATH).parent
source_root = project_root / "src"

a = Analysis(
    [str(source_root / "job_monitor" / "desktop_entry.py")],
    pathex=[str(source_root)],
    hiddenimports=hiddenimports,
    datas=[(str(project_root / "data" / "jobs_seed.sqlite"), "data")],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="FeishuJobRadar", console=False)

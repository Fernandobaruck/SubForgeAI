"""Build only the portable Studio launcher; Qt stays in runtime/python."""
from pathlib import Path
import sys
import shutil
import filecmp

ROOT = Path(__file__).resolve().parents[1]


def main():
    from PyInstaller.__main__ import run
    run(['--noconfirm', '--clean', '--onedir', '--windowed',
         '--contents-directory', '_studio_boot',
         '--name', 'SubForgeAI Studio', '--icon', str(ROOT / 'assets/brand/subforge-studio.ico'),
         '--workpath', str(ROOT / 'build/studio'),
         '--specpath', str(ROOT / 'build/studio'),
         '--distpath', str(ROOT / 'dist/studio'),
         str(ROOT / 'studio_bootstrap.py')])
    package = ROOT / 'dist/studio/SubForgeAI Studio'
    built = package / 'SubForgeAI Studio.exe'
    target = ROOT / 'SubForgeAI Studio.exe'
    staged = target.with_suffix('.exe.new')
    # Install persistent boot resources before switching the launcher. Unlike
    # onefile, onedir does not extract a _MEI directory into Windows TEMP.
    def copy_changed(source, destination):
        if Path(destination).is_file() and filecmp.cmp(source, destination, shallow=False):
            return str(destination)
        return shutil.copy2(source, destination)
    shutil.copytree(package / '_studio_boot', ROOT / '_studio_boot', dirs_exist_ok=True, copy_function=copy_changed)
    shutil.copy2(built, staged)
    staged.replace(target)
    # Explorer can retain the previous executable icon under the same path.
    # Notify the shell after replacement without restarting Explorer or deleting
    # the user's icon cache files.
    if sys.platform == 'win32':
        import ctypes
        notify = ctypes.windll.shell32.SHChangeNotify
        notify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        path = ctypes.create_unicode_buffer(str(target))
        notify(0x2000, 0x1005, ctypes.cast(path, ctypes.c_void_p), None)
        notify(0x08000000, 0, None, None)
    print(f'Studio instalado em: {target}')


if __name__ == '__main__': main()

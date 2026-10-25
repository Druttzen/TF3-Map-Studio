"""Reject incomplete build environments before generating an executable."""
import importlib
from pathlib import Path
import ssl
import sys


def check():
    failures = []
    for module in ('PyInstaller', 'tkinter', 'numpy', 'PIL', 'scipy.ndimage',
                   'rasterio.warp', 'certifi', 'affine', 'attr', 'click',
                   'pyparsing', 'laspy', 'lazrs', 'pyproj', 'ijson'):
        try:
            importlib.import_module(module)
        except Exception as exc:
            failures.append(f'{module}: {exc}')
    if not failures:
        try:
            import certifi
            ssl.create_default_context(cafile=certifi.where())
            # Exercise the same import chain that runs at application startup.
            importlib.import_module('gui')
        except Exception as exc:
            failures.append(f'Application startup: {exc}')
    if failures:
        print('Required build dependencies are missing or unusable:', file=sys.stderr)
        print('\n'.join(failures), file=sys.stderr)
        requirements = Path(__file__).resolve().parents[1] / 'requirements-dev.txt'
        print(f'Install {requirements} with this same Python interpreter.', file=sys.stderr)
        return 1
    print('Build dependencies, HTTPS certificates and application imports verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(check())

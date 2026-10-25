"""Regression for a successful-looking build made without runtime packages."""
import subprocess
import sys
from pathlib import Path


def test_build_preflight_rejects_environment_without_site_packages():
    script = Path(__file__).resolve().parents[1] / 'tools/build_check.py'
    result = subprocess.run([sys.executable, '-I', '-S', str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert 'certifi' in result.stderr
    assert 'rasterio.warp' in result.stderr
    assert 'requirements-dev.txt' in result.stderr
    assert 'Build dependencies, HTTPS certificates' not in result.stdout

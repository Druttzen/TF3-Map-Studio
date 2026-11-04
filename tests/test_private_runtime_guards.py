"""Private tools must reject external environments and venv bootstraps."""
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest

spec = importlib.util.spec_from_file_location('private_runtime',Path(__file__).resolve().parents[1]/'scripts/private_runtime.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)


def tool(tmp_path):
    root = tmp_path/'OSM-TF3-Vanilla-Converter'; root.mkdir()
    (root/'README.md').write_text('fixture')
    return root


def test_child_environment_excludes_foreign_python_conda_and_global_paths(tmp_path):
    root = tool(tmp_path)
    hostile = {'PATH':'foreign-bin', 'PYTHONHOME':'foreign-python', 'PYTHONPATH':'foreign-packages',
               'VIRTUAL_ENV':'foreign-venv', 'CONDA_PREFIX':'foreign-conda', 'PIP_TARGET':'foreign-site'}
    with patch.dict(os.environ, hostile):
        env = runtime.child_environment(root)
        assert 'PYTHONHOME' not in env and 'PYTHONPATH' not in env
        assert all(key not in env for key in ('VIRTUAL_ENV','CONDA_PREFIX','PIP_TARGET'))
        assert 'foreign-bin' not in env['PATH']
        assert env['PIP_CONFIG_FILE'] == os.devnull
        assert Path(env['TEMP']).is_relative_to(root)
        assert os.environ['PATH'] == 'foreign-bin'


def test_venv_is_rejected_before_provisioning(tmp_path):
    root = tool(tmp_path); source = tmp_path/'source'; (source/'Lib/encodings').mkdir(parents=True)
    (source/'python.exe').write_bytes(b'fixture'); (source/'pyvenv.cfg').write_text('home=foreign')
    with pytest.raises(ValueError,match='not a venv'):
        runtime.provision(root, source)
    assert not (root/'.runtime').exists()


def test_interpreter_with_external_base_is_rejected(tmp_path):
    root = tool(tmp_path); private = root/'.runtime'
    response = {'prefix':str(private),'basePrefix':str(tmp_path/'foreign'), 'paths':[str(private)], 'userSite':False}
    with patch.object(runtime.subprocess,'check_output',return_value=json.dumps(response)), pytest.raises(ValueError,match='external interpreter'):
        runtime.inventory(root)

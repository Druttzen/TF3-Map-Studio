import json
from trf3_mod_converter.runtime_check import check


def test_fictional_runtime_check_exports_and_recovers_without_changing_sources(tmp_path):
    report = tmp_path/'runtime.json'
    status = check(report)
    result = json.loads(report.read_text())
    assert status == 0, result
    assert result['ok'] is True and result['networkUsed'] is False

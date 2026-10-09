import json
import pytest

from test_gui import app, wait_for_work
from test_batch import mod


def test_reopen_results_and_retry_still_verify_existing_exports(app, tmp_path):
    source = mod(tmp_path, 'source', 'Saved results')
    output = tmp_path / 'out'
    app._set_source(str(source))
    wait_for_work(app)
    app.variables['destination'].set(str(output))
    app.convert_all()
    wait_for_work(app)
    app.load_results(output / '.tf3-batch-report.json')
    assert app.items[0].status == 'completed'
    assert '1 exported' in app.status.get()
    (output / app.items[0].mod_id / 'mod.json').write_text('{}')
    app.convert_all()
    wait_for_work(app)
    assert app.items[0].status == 'failed'
    assert 'not overwritten' in app.items[0].message


def test_saved_running_item_reopens_pending(app, tmp_path):
    report = tmp_path / 'report.json'
    report.write_text(json.dumps({'format':'tf3-converter-batch-v1', 'items':[
        {'source':str(tmp_path/'mod'), 'display_name':'Interrupted', 'mod_id':'interrupted',
         'metadata_signature':'signature', 'status':'running'}], 'destination':str(tmp_path/'out')}))
    app.load_results(report)
    assert app.items[0].status == 'pending'
    assert app.variables['destination'].get() == str(tmp_path/'out')


def test_corrupt_receipts_are_rejected_as_a_readable_report_error(app, tmp_path):
    report = tmp_path/'corrupt.json'
    report.write_text(json.dumps({'format':'tf3-converter-batch-v1', 'items':[], 'receipts':[]}))
    with pytest.raises(ValueError, match='Invalid saved conversion receipts'):
        app.load_results(report)

import json

import pytest

from test_gui import app, wait_for_work
from test_batch import mod


def test_noise_choice_applies_only_to_selected_mod_and_keeps_strict_control(app, tmp_path):
    collection = tmp_path / 'collection'
    mod(collection, 'a', 'First')
    mod(collection, 'b', 'Second')
    app._set_source(str(collection))
    wait_for_work(app)
    first, second = app.items
    first.status = 'failed'
    first.message = 'Explicit TF2 emissions require a noise/pollution balancing decision'
    app.show_item(first)
    assert app.choice_frame.winfo_manager() == 'grid'
    app.emissions_choice.set('Keep original values as noise')
    app._choose_emissions()
    assert first.emissions_policy == 'legacy_noise'
    assert second.emissions_policy == 'strict'
    assert first.status == 'pending'
    app.emissions_choice.set('Review required')
    app._choose_emissions()
    assert first.emissions_policy == 'strict'
    assert app.choice_frame.winfo_manager() == 'grid'
    app.show_item(second)
    assert app.choice_frame.winfo_manager() == ''


def test_saved_choice_round_trip_and_new_queue_clear_selection(app, tmp_path):
    source = mod(tmp_path, 'source', 'Saved choice')
    app._set_source(str(source))
    wait_for_work(app)
    app.variables['destination'].set(str(tmp_path / 'out'))
    first = app.items[0]
    first.message = 'Explicit TF2 emissions require a noise/pollution balancing decision'
    app.show_item(first)
    app.emissions_choice.set('Use TF3 automatic values')
    app._choose_emissions()
    app.convert_all()
    wait_for_work(app)
    report_path = tmp_path / 'out' / '.tf3-batch-report.json'
    state = json.loads(report_path.read_text())
    assert state['items'][0]['emissions_policy'] == 'tf3_automatic'
    assert state['receipts'][first.key]['conversionChoices'] == {'emissionsPolicy':'tf3_automatic'}
    app.load_results(report_path)
    assert app.selected_item is app.items[0]
    assert app.selected_item is not first
    assert app.emissions_choice.get() == 'Use TF3 automatic values'
    app.variables['source'].set(str(tmp_path / 'other'))
    assert app.selected_item is None
    assert not app.emissions_eligible
    assert app.choice_frame.winfo_manager() == ''


def test_busy_choice_is_disabled_and_cannot_change_queue(app, tmp_path):
    source = mod(tmp_path, 'source', 'One')
    app._set_source(str(source))
    wait_for_work(app)
    item = app.items[0]
    item.message = 'noise/pollution decision'
    app.show_item(item)
    app.busy = True
    app._buttons()
    assert str(app.emissions_selector['state']) == 'disabled'
    app.emissions_choice.set('Use TF3 automatic values')
    app._choose_emissions()
    assert item.emissions_policy == 'strict'
    app.busy = False
    app._buttons()
    assert str(app.emissions_selector['state']) == 'readonly'


@pytest.mark.parametrize('policy', ['unknown', None, 1])
def test_invalid_saved_choice_is_rejected_before_replacing_queue(app, tmp_path, policy):
    report = tmp_path / 'bad.json'
    report.write_text(json.dumps({'format':'tf3-converter-batch-v1', 'items':[
        {'source':str(tmp_path/'mod'), 'display_name':'Invalid', 'mod_id':'invalid',
         'metadata_signature':'signature', 'emissions_policy':policy}]}))
    with pytest.raises(ValueError, match='noise and pollution policy'):
        app.load_results(report)
    assert app.items == []

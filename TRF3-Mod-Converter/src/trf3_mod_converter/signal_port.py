"""Migrate literal TF2 rail signal models into native edge constructions."""
from copy import deepcopy
import math


IDENTITY = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]


def port_signal(data, model_reference, construction_reference, native, *, report=None, resource=''):
    from .tf2_vehicle_port import lua_value
    result = deepcopy(data)
    metadata = result.get('metadata', {})
    signal = metadata.pop('signal', None)
    if not isinstance(signal, dict) or set(signal)-{'type','soundevent'} or signal.get('type') not in ('PATH_SIGNAL','WAYPOINT','ONE_WAY_PATH_SIGNAL'):
        raise ValueError('Rail signal requires a literal supported signal type; custom signal fields need migration')
    from .lua_metadata import TranslatedString
    soundevent = signal.get('soundevent', '')
    if isinstance(soundevent, TranslatedString) or type(soundevent) is not str or soundevent not in ('','horn'):
        raise ValueError('Rail signal sound event requires a verified literal native event identifier')
    category = metadata.pop('category', {})
    if not isinstance(category, dict) or set(category)-{'categories'}:
        raise ValueError('Rail signal categories require a literal categories list')
    categories = category.get('categories', [])
    if not isinstance(categories, list) or any(not isinstance(value, str) for value in categories):
        raise ValueError('Rail signal categories require literal names')
    cost = metadata.get('cost', {})
    maintenance = metadata.get('maintenance', {})
    if not isinstance(cost, dict) or set(cost)-{'price'} or not isinstance(maintenance, dict) or set(maintenance)-{'runningCosts'}:
        raise ValueError('Rail signal economy requires explicit literal cost and maintenance values')
    price, running = cost.get('price', 0), maintenance.get('runningCosts', 0)
    if any(type(value) not in (int,float) or not math.isfinite(value) or value < 0 for value in (price,running)):
        raise ValueError('Automatic TF2 signal economy requires a native balancing policy')
    native.read('infrastructure/signal/signal_path_c.con.lua')
    native.read('infrastructure/signal/signal_path_c.script.lua')
    construction = {
        'availability':deepcopy(metadata.get('availability', {})),
        'description':deepcopy(metadata.get('description', {})),
        'menuCategory':{'categories':[{'category':'rail_tools','filterCategories':categories,'order':1000}]},
        'edgeObject':{'snapToTrack':True},
        'updateScript':{'fileName':construction_reference[:-4]+'.script@updateFn','params':{}},
    }
    update = {'signal':dict(signal, soundevent=soundevent), 'edgeModels':[{'model':{'id':model_reference,'transf':IDENTITY}}],
              'cost':price, 'maintenanceCost':running}
    script = 'function data()\nreturn { updateFn = function(captureParams, params)\nreturn '+lua_value(update)+'\nend }\nend\n'
    if report is not None:
        report.setdefault('signalMigrations', []).append({
            'resource':resource, 'signalType':signal['type'], 'modelReference':model_reference,
            'constructionReference':construction_reference, 'cost':price,'maintenanceCost':running,
            'soundevent':soundevent,
            'policy':'preserve_rail_signal_type_geometry_animation_and_price_as_edge_construction',
            'schemaSource':'https://wiki.transportfever3.com/script-doc/api/type.html#SignalType', 'nativeTest':'not_run'})
    return result, construction, script

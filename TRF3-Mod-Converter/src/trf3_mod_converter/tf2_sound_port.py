"""Translate recognized TF2 sound expressions to installed TF3 sound functions.

Only literal tables, constants and the helper patterns below are accepted.
Source Lua and its imports are never executed. This module contains no game code.
"""
from __future__ import annotations

import math
from luaparser import ast
from luaparser import astnodes as lua

from .lua_metadata import _value, UnsupportedValue, TranslatedString
from .resource_audit import parse_lua
from .legacy_sound_helpers import verified_sound_helper_profiles, authored_brake_script, authored_squeal_script


def fields(node, allowed):
    if not isinstance(node, lua.Table):
        raise ValueError("Sound data must be a direct table")
    result = {}
    for field in node.fields:
        key = field.key.id if isinstance(field.key, lua.Name) and not field.between_brackets else _value(field.key)
        if not isinstance(key, str) or key not in allowed or key in result:
            raise ValueError(f"Unsupported or duplicate sound field: {key}")
        result[key] = field.value
    return result


def literal(node):
    result = _value(node, constant_numbers=True)
    def check(value):
        if isinstance(value, UnsupportedValue):
            raise ValueError(f"Computed sound data needs manual port: {value.reason}")
        if isinstance(value, dict):
            for v in value.values(): check(v)
        elif isinstance(value, list):
            for v in value: check(v)
    check(result)
    return result


def port_sound_set(text, resolve, native, *, report=None, resource='', script_writer=None, verified_helpers=None):
    tree = parse_lua(text)
    helper_profiles = verified_sound_helper_profiles(verified_helpers)
    if any(isinstance(statement, lua.LocalAssign) and len(statement.values) == 1
           and isinstance(statement.values[0], lua.Call)
           and isinstance(statement.values[0].func, lua.Name) and statement.values[0].func.id == 'require'
           and len(statement.values[0].args) == 1 and _value(statement.values[0].args[0]) == 'soundsetutil'
           for statement in tree.body.body):
        return _port_sound_builder(tree, resolve, native, report=report, resource=resource, script_writer=script_writer)
    helpers = {}
    definition = None
    for statement in tree.body.body:
        if isinstance(statement, lua.LocalAssign) and definition is None and len(statement.targets) == len(statement.values) == 1:
            target, value = statement.targets[0], statement.values[0]
            if not (isinstance(target, lua.Name) and target.id not in helpers and target.id not in ('data', 'math', 'require', '_', 'ug_require')
                    and isinstance(value, lua.Call) and isinstance(value.func, lua.Name) and value.func.id == 'require'
                    and len(value.args) == 1 and ((_value(value.args[0]) in ('audioutil', 'soundeffectsutil')
                                                 and _value(value.args[0]) not in (verified_helpers or {}))
                                                or _value(value.args[0]) in helper_profiles)):
                raise ValueError("Unsupported sound helper import")
            helpers[target.id] = _value(value.args[0])
        elif isinstance(statement, lua.Function) and isinstance(statement.name, lua.Name) and statement.name.id == 'data' and definition is None:
            definition = statement
        else:
            raise ValueError("Sound resource uses executable or ambiguous top-level statements")
    if definition is None or len(definition.body.body) != 1 or not isinstance(definition.body.body[0], lua.Return) or len(definition.body.body[0].values) != 1:
        raise ValueError("Sound data() must directly return a table")
    data = fields(definition.body.body[0].values[0], {'tracks', 'events', 'updateFn'})
    callback = data.get('updateFn')
    if not isinstance(callback, lua.AnonymousFunction) or len(callback.args) != 1 or not isinstance(callback.args[0], lua.Name):
        raise ValueError("Expected sound updateFn(input) callback")
    input_name = callback.args[0].id
    if input_name in helpers: raise ValueError("Sound input shadows helper import")
    constants = {}
    input_aliases = {}
    expressions = {}
    chuff_bindings = {}

    def audit(policy, **values):
        if report is not None:
            report.setdefault('soundMigrations', []).append({
                'resource': resource, 'policy': policy, 'nativeTest': 'not_run', **values})

    def input_field(node, name):
        return isinstance(node, lua.Index) and node.notation == lua.IndexNotation.DOT and isinstance(node.value, lua.Name) and node.value.id == input_name and isinstance(node.idx, lua.Name) and node.idx.id == name

    def input_parameter(node):
        if isinstance(node, lua.Name):
            return input_aliases.get(node.id)
        for parameter in ('speed01', 'power01'):
            if input_field(node, parameter):
                return parameter
        # TF2's normalized speed is also commonly written explicitly. Do not
        # accept arbitrary ratios, multipliers, or mutable callback bindings.
        if isinstance(node, lua.FloatDivOp) and input_field(node.left, 'speed') and input_field(node.right, 'topSpeed'):
            return 'speed01'
        return None

    def call(node, helper, function):
        module = (helpers.get(node.func.value.id)
                  if isinstance(node, lua.Call) and isinstance(node.func, lua.Index)
                  and isinstance(node.func.value, lua.Name) else None)
        if module in helper_profiles:
            profile = helper_profiles[module][1]
            equivalent = function in ('sampleCurve', 'squeal', 'clacks')
            allowed = equivalent or function in profile
            module_matches = allowed and (module == helper or
                                          (helper == 'soundeffectsutil' and equivalent))
        else:
            module_matches = module == helper
        return (isinstance(node, lua.Call) and isinstance(node.func, lua.Index) and node.func.notation == lua.IndexNotation.DOT
                and isinstance(node.func.value, lua.Name)
                and module_matches
                and isinstance(node.func.idx, lua.Name) and node.func.idx.id == function)

    for module in sorted(set(helpers.values()) & set(helper_profiles)):
        audit('verified_legacy_sound_helper', module=module, sha256=helper_profiles[module][0],
              supportedFunctions=['sampleCurve', 'squeal', 'clacks', *helper_profiles[module][1]],
              evidence='Exact audited helper profile; source Lua is not executed or copied.')

    def number(node):
        value = constants.get(node.id) if isinstance(node, lua.Name) else literal(node)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Expected finite numeric sound constant")
        return value

    def numeral(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Expected finite numeric sound expression')
        return repr(value)

    def bounded(expression):
        if len(expression) > 65536:
            raise ValueError('Sound expression exceeds safe export limit')
        return expression

    def scalar(node, depth=0, budget=None):
        """Compile approved pure arithmetic; never execute or emit source Lua."""
        budget = [0] if budget is None else budget
        budget[0] += 1
        if depth > 32 or budget[0] > 4096:
            raise ValueError('Sound expression exceeds safe export limit')
        parameter = input_parameter(node)
        if parameter is not None:
            return 'currentInfo.vehicle.' + parameter
        if isinstance(node, lua.Name):
            if node.id in expressions:
                return bounded('(' + expressions[node.id] + ')')
            return numeral(constants.get(node.id))
        if isinstance(node, (lua.Number, lua.UMinusOp)):
            if isinstance(node, lua.UMinusOp):
                return bounded('(-' + scalar(node.operand, depth+1, budget) + ')')
            return numeral(node.n)
        operators = {lua.AddOp: '+', lua.SubOp: '-', lua.MultOp: '*', lua.FloatDivOp: '/'}
        operator = operators.get(type(node))
        if operator:
            folded = _value(node, constant_numbers=True)
            if type(folded) in (int, float):
                return numeral(folded)
            if operator == '/':
                divisor = number(node.right)
                if divisor == 0:
                    raise ValueError('Sound expressions cannot divide by zero or a runtime value')
            return bounded('(' + scalar(node.left, depth+1, budget) + operator + scalar(node.right, depth+1, budget) + ')')
        if (any(call(node, helper, 'sampleCurve') for helper in ('soundeffectsutil', 'audioutil'))
                and len(node.args) == 2 and input_parameter(node.args[1]) is not None):
            rows = _sound_array(node.args[0])
            if not 1 <= len(rows) <= 4096:
                raise ValueError('Expected bounded sound expression curve')
            points, curve_bytes = [], 0
            for row in rows:
                coordinates = _sound_array(row)
                if len(coordinates) != 2:
                    raise ValueError('Expected sound expression coordinate pair')
                # Keep repeated and nonmonotonic abscissae in their authored
                # order. The verified native helper has the same first-match
                # segment selection as the shipped TF2 sampleCurve helpers.
                x = numeral(number(coordinates[0]))
                y = scalar(coordinates[1], depth+1, budget)
                point = '{' + x + ',' + y + '}'
                curve_bytes += len(point) + 1
                if curve_bytes > 65536:
                    raise ValueError('Sound expression curve exceeds safe export limit')
                points.append(point)
            return bounded('audio.sampleCurve({' + ','.join(points) + '},' + scalar(node.args[1], depth+1, budget) + ')')
        raise ValueError('Unsupported dynamic sound expression; manual script port required')

    def name_used(name):
        excluded = set()
        for node in ast.walk(callback):
            if isinstance(node, lua.Field) and isinstance(node.key, lua.Name) and not node.between_brackets:
                excluded.add(id(node.key))
            if isinstance(node, lua.Index) and node.notation == lua.IndexNotation.DOT and isinstance(node.idx, lua.Name):
                excluded.add(id(node.idx))
            if isinstance(node, lua.LocalAssign):
                excluded.update(id(target) for target in node.targets)
        return any(isinstance(node, lua.Name) and node.id == name and id(node) not in excluded
                   for node in ast.walk(callback))

    returned = None
    if len(callback.body.body) > 4096:
        raise ValueError('Sound callback exceeds safe export limit')
    for statement in callback.body.body:
        if isinstance(statement, lua.LocalAssign) and returned is None and len(statement.targets) == len(statement.values) == 1 and isinstance(statement.targets[0], lua.Name):
            key = statement.targets[0].id
            if key in helpers or key in (input_name, 'math', 'require', '_', 'data', 'ug_require') or key in constants or key in input_aliases or key in expressions or key in chuff_bindings:
                raise ValueError("Sound constants shadow bindings")
            expression = statement.values[0]
            parameter = input_parameter(expression)
            if parameter is not None:
                input_aliases[key] = parameter
            elif call(expression, 'soundeffectsutil', 'chuffs') and len(expression.args) == 5:
                arguments = expression.args
                if not input_field(arguments[0], 'speed') or not input_field(arguments[1], 'chuffStep'):
                    raise ValueError('Unsupported steam chuff input fields')
                frequency, weight = number(arguments[2]), number(arguments[4])
                if frequency <= 0 or weight <= 0:
                    raise ValueError('Steam chuff frequency and reference weight must be positive')
                if not name_used(key):
                    if not (input_field(arguments[3], 'weight') or input_field(arguments[3], 'gameSpeedUp')):
                        raise ValueError('Unsupported unused steam chuff expression')
                    # The shipped helper is pure. Its unused result has no
                    # influence on any track/event; all authored controls stay.
                    constants[key] = None
                    audit('omit_unreferenced_pure_chuffs_result', binding=key,
                          evidence='Installed TF2 soundeffectsutil.chuffs reads scalar arguments and returns a fresh table only.')
                else:
                    if not input_field(arguments[3], 'weight'):
                        raise ValueError('Used steam chuffs require the source weight input')
                    if not math.isfinite(weight*1000):
                        raise ValueError('Steam chuff reference weight exceeds the finite kilogram range')
                    chuff_bindings[key] = {'chuffsFastFreq': frequency, 'refWeight': weight*1000}
            else:
                try:
                    constants[key] = literal(expression)
                except ValueError:
                    expressions[key] = scalar(expression)
        elif isinstance(statement, lua.Return) and returned is None and len(statement.values) == 1:
            returned = fields(statement.values[0], {'tracks', 'events'})
        else:
            raise ValueError("Sound updateFn uses unsupported control flow or assignments")
    if returned is None: raise ValueError("Sound updateFn must return track/event controls")

    def curve(node):
        if call(node, 'audioutil', 'plotSqrt') and len(node.args) == 5:
            x0, y0, x1, y1, count = [number(a) for a in node.args]
            if type(count) is not int or not 1 <= count <= 4096 or x0 >= x1:
                raise ValueError("Unsupported plotSqrt range")
            return [[x0 + (x1-x0)*(i/count)**2, y0+(y1-y0)*(i/count)] for i in range(count+1)]
        points = literal(node)
        if not isinstance(points, list) or not points or any(not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in points):
            raise ValueError("Expected finite sound curve points")
        if any(a[0] >= b[0] for a,b in zip(points,points[1:])):
            raise ValueError("Sound curve points must increase")
        return points

    def control(node, *, event=False):
        if (isinstance(node, lua.Index) and node.notation == lua.IndexNotation.DOT
                and isinstance(node.value, lua.Name) and node.value.id in chuff_bindings
                and isinstance(node.idx, lua.Name) and node.idx.id in ('idleTrack', 'fastTrack', 'event')):
            return {'_chuffBinding': node.value.id, '_chuffPart': node.idx.id}
        if call(node, 'soundeffectsutil', 'squeal') and len(node.args) == 3 and all(input_field(a,k) for a,k in zip(node.args,('speed','sideForce','maxSideForce'))):
            return {'type':'Squeal', 'params':{}}
        if (call(node, 'soundeffectsutil', 'squeal') and len(node.args) == 3
                and input_field(node.args[0], 'speed') and input_field(node.args[1], 'sideForce')
                and helpers[node.func.value.id] in helper_profiles):
            module = helpers[node.func.value.id]
            digest = helper_profiles[module][0]
            limit = number(node.args[2])
            if event:
                raise ValueError('Authored squeal event needs a verified TF3 event-trigger adapter')
            if script_writer is None:
                raise ValueError('Authored squeal helper requires a generated TF3 script writer')
            target = script_writer('authored_squeal', authored_squeal_script())
            if not isinstance(target, str) or not target.endswith('@update') or '::/' not in target:
                raise ValueError('Sound script writer returned no qualified @update resource')
            params = {'maxSideForce': limit}
            audit('compile_verified_authored_squeal', module=module, sha256=digest,
                  sourceInput='sideForce', targetInput='railVehicle.sideForce',
                  authoredParameters=params, targetReference=target)
            return {'type': 'Custom', 'params': {'customUpdateScript': target, 'customParams': params}}
        for module, (digest, profile) in helper_profiles.items():
            for function in ('brake', 'slow'):
                if function not in profile:
                    continue
                if not call(node, module, function):
                    continue
                if (len(node.args) != (3 if function == 'brake' else 4)
                        or not input_field(node.args[0], 'speed') or not input_field(node.args[1], 'brakeDecel')
                        or (function == 'slow' and input_parameter(node.args[3]) != 'speed01')):
                    raise ValueError('Unsupported authored brake helper inputs')
                if event:
                    raise ValueError('Authored brake event needs a verified TF3 event-trigger adapter')
                if script_writer is None:
                    raise ValueError('Authored brake helper requires a generated TF3 script writer')
                gain = number(node.args[2])
                if gain < 0:
                    raise ValueError('Authored brake gain must be non-negative')
                target = script_writer('authored_brake', authored_brake_script())
                if not isinstance(target, str) or not target.endswith('@update') or '::/' not in target:
                    raise ValueError('Sound script writer returned no qualified @update resource')
                params = dict(profile[function], maxGain=gain)
                audit('compile_verified_authored_brake', module=module, sha256=digest, helperFunction=function,
                      sourceInput='brakeDecel', targetInput='vehicle.brakeDecel',
                      authoredParameters=params, targetReference=target)
                return {'type': 'Custom', 'params': {'customUpdateScript': target, 'customParams': params}}
        if call(node, 'soundeffectsutil', 'brake') and len(node.args) == 3 and input_field(node.args[0],'speed') and input_field(node.args[1],'brakeDecel'):
            return {'type':'Brake', 'params':{'maxGain':number(node.args[2])}}
        if call(node, 'soundeffectsutil', 'clacks') and len(node.args) == 5 and all(input_field(node.args[i],k) for i,k in ((0,'speed'),(1,'weight'),(2,'numAxles'),(4,'gameSpeedUp'))):
            weight = number(node.args[3])
            if weight <= 0: raise ValueError("Clack reference weight must be positive")
            if not math.isfinite(weight*1000): raise ValueError('Clack reference weight exceeds the finite kilogram range')
            return {'type':'Clacks', 'params':{'axleRefWeight':weight*1000}}
        values = fields(node, {'gain','pitch'})
        if set(values) != {'gain','pitch'}: raise ValueError("Sound control requires gain and pitch")
        params = {}
        for key, expression in values.items():
            parameter = 'speed01'
            if any(call(expression, helper, 'sampleCurve') for helper in ('soundeffectsutil','audioutil')) and len(expression.args) == 2 and input_parameter(expression.args[1]) is not None:
                params[key+'Curve'] = curve(expression.args[0])
                parameter = input_parameter(expression.args[1])
            else:
                value = number(expression)
                params[key+'Curve'] = [[0,value],[1,value]]
            params[key+'ScriptingInfoKey'] = 'vehicle'
            params[key+'ParamName'] = parameter
        return {'type':'SampleCurve', 'params':params}

    def mapped_control(node, *, event=False):
        try:
            return control(node, event=event)
        except ValueError as unsupported:
            if script_writer is None:
                raise
            if not isinstance(node, lua.Table):
                raise
            values = fields(node, {'gain', 'pitch'})
            if set(values) != {'gain', 'pitch'}:
                raise unsupported
            # Native Custom event scripts own the trigger decision. A legacy
            # gain/pitch callback provides no such decision, so substituting
            # a Custom event would suppress the event or invent new triggers.
            if event:
                raise ValueError('Dynamic sound event gain/pitch needs a verified TF3 event-trigger adapter') from unsupported
            gain, pitch = scalar(values['gain']), scalar(values['pitch'])
            audio_reference = native.reference('scripts/audioutil.lua')
            script = ('function data()\n return { update = function(result, captureParams, currentInfo)\n'
                      '  local audio = ug_require "' + audio_reference + '"\n'
                      '  result.gain = ' + gain + '\n'
                      '  result.pitch = ' + pitch + '\n end }\nend\n')
            reference = script_writer('sound_curve', script)
            if not isinstance(reference, str) or not reference.endswith('@update') or '::/' not in reference:
                raise ValueError('Sound script writer returned no qualified @update resource')
            audit('compile_bounded_sound_expressions', targetReference=reference,
                  evidence='Only finite literals, speed01/power01, immutable aliases, arithmetic and the installed native sampleCurve helper.',
                  curveOrder='preserved')
            return {'type': 'Custom', 'params': {'customUpdateScript': reference, 'customParams': {}}}

    def array(node):
        if not isinstance(node,lua.Table) or any(f.key is not None for f in node.fields):
            raise ValueError("Expected ordered sound tracks")
        return [f.value for f in node.fields]

    tracks = literal(data['tracks']) if 'tracks' in data else []
    events = literal(data['events']) if 'events' in data else {}
    if events == []: events = {}
    if not isinstance(tracks,list) or not isinstance(events,dict): raise ValueError("Invalid sound tracks/events")
    track_controls = array(returned['tracks']) if 'tracks' in returned else []
    event_controls = fields(returned['events'], set(events)) if 'events' in returned else {}
    if len(track_controls) != len(tracks) or set(event_controls) != set(events):
        raise ValueError(f"Sound definitions and update controls do not match: {len(tracks)} tracks but {len(track_controls)} controls; "
                         f"event definitions {sorted(events)} versus controls {sorted(event_controls)}")
    track_updates = [mapped_control(n) for n in track_controls]
    event_updates = {key: mapped_control(node, event=True) for key, node in event_controls.items()}
    update_functions, index = [], 0
    while index < len(track_updates):
        update = track_updates[index]
        binding = update.get('_chuffBinding')
        if binding is not None:
            if (update['_chuffPart'] != 'idleTrack' or index+1 >= len(track_updates)
                    or track_updates[index+1] != {'_chuffBinding': binding, '_chuffPart': 'fastTrack'}
                    or event_updates.get('chuffs') != {'_chuffBinding': binding, '_chuffPart': 'event'}):
                raise ValueError('Steam chuffs require adjacent idle/fast tracks and the matching chuffs event')
            update_functions.append({'type': 'Chuffs', 'params': chuff_bindings[binding], 'eventKey': 'chuffs'})
            del event_updates['chuffs']
            index += 2
            audit('native_steam_chuffs', binding=binding, refWeightUnit='kilograms')
        else:
            update_functions.append(update)
            index += 1
    for key, update in event_updates.items():
        if '_chuffBinding' in update:
            raise ValueError('Steam chuff event has no corresponding adjacent idle/fast tracks')
        update_functions.append(dict(update, eventKey=key))
    return _finalize_sound(tracks, events, update_functions, resolve, native)


def _finalize_sound(tracks, events, update_functions, resolve, native):
    attribute_keys = {'refDist', 'gain', 'rolloffFact', 'hasVelocity'}
    def attributes(entry, base_fields):
        if not isinstance(entry, dict) or not base_fields <= set(entry) or set(entry) - base_fields - attribute_keys:
            raise ValueError('Unsupported sound clip attributes')
        attrs = {key: entry.pop(key) for key in attribute_keys if key in entry}
        if 'refDist' not in attrs:
            raise ValueError('Sound reference distance is required')
        for key in ('gain', 'rolloffFact'):
            if key in attrs and (type(attrs[key]) not in (int, float) or not math.isfinite(attrs[key]) or attrs[key] < 0):
                raise ValueError(f'Sound {key} must be nonnegative and finite')
        if 'hasVelocity' in attrs and type(attrs['hasVelocity']) is not bool:
            raise ValueError('Sound hasVelocity must be a literal boolean')
        entry['attrs'] = attrs
    for entry in tracks:
        attributes(entry, {'name'})
        if not isinstance(entry['name'], str) or isinstance(entry['name'], TranslatedString):
            raise ValueError('Sound track needs a literal audio resource reference')
        entry['name'] = resolve(entry['name'], 'audio')
    for entry in events.values():
        attributes(entry, {'names'})
        if not isinstance(entry['names'],list): raise ValueError("Unsupported event attributes")
        if not entry['names'] or any(not isinstance(n, str) or isinstance(n, TranslatedString) for n in entry['names']):
            raise ValueError('Sound event needs literal audio resource references')
        entry['names'] = [resolve(n,'audio') for n in entry['names']]
    for entry in [*tracks,*events.values()]:
        distance = entry['attrs']['refDist']
        if type(distance) not in (int,float) or not math.isfinite(distance) or distance <= 0:
            raise ValueError("Sound reference distance must be positive and finite")
    return {'tracks':tracks, 'events':events,
            'updateScript':{'fileName':native.reference('scripts/soundset_default.script@updateSoundSet'),
                            'params':{'updateFunctions':update_functions}}}


def _sound_array(node):
    if not isinstance(node, lua.Table) or any(field.key is not None for field in node.fields):
        raise ValueError('Expected ordered literal sound table')
    return [field.value for field in node.fields]


def _port_sound_builder(tree, resolve, native, *, report=None, resource='', script_writer=None):
    """Fold only recognized TF2 soundsetutil construction calls.

    The installed TF2 soundsetutil and TF3 scripts/soundsetutil.lua define the
    same curve, squeal, brake and clack operations. TF3 uses the vehicle info
    namespace for speed01/power01 and kilograms for clack reference weight.
    Source helper code and arbitrary callbacks are never executed or emitted.
    """
    helpers, constants, local_track_helpers, definition = {}, {}, {}, None

    def value(node):
        if isinstance(node, lua.Name):
            if node.id not in constants:
                raise ValueError(f'Unbound sound builder constant: {node.id}')
            return constants[node.id]
        result = _value(node, constant_numbers=True)
        def check(item):
            if isinstance(item, UnsupportedValue):
                raise ValueError(f'Computed sound builder data needs manual port: {item.reason}')
            if isinstance(item, dict):
                for nested in item.values(): check(nested)
            elif isinstance(item, list):
                for nested in item: check(nested)
        check(result)
        return result

    def number(item, *, positive=False):
        if type(item) not in (int, float) or not math.isfinite(item) or (positive and item <= 0):
            raise ValueError('Sound builder requires finite numeric constants')
        return item

    def points(item):
        if (not isinstance(item, list) or not 1 <= len(item) <= 4096
                or any(not isinstance(p, list) or len(p) != 2 for p in item)):
            raise ValueError('Expected bounded sound curve points')
        for point in item:
            for coordinate in point: number(coordinate)
        if any(a[0] >= b[0] for a, b in zip(item, item[1:])):
            raise ValueError('Sound curve points must increase')
        return item

    def sample(gain, pitch, parameter):
        if parameter not in ('speed01', 'power01') or isinstance(parameter, TranslatedString):
            raise ValueError('Unsupported sound builder vehicle input parameter')
        params = {'gainCurve': points(gain), 'gainScriptingInfoKey': 'vehicle', 'gainParamName': parameter}
        if pitch is not None:
            params.update(pitchCurve=points(pitch), pitchScriptingInfoKey='vehicle', pitchParamName=parameter)
        return {'type': 'SampleCurve', 'params': params}

    def local_constant(statement):
        if (len(statement.targets) != len(statement.values) or len(statement.targets) != 1
                or not isinstance(statement.targets[0], lua.Name)):
            raise ValueError('Unsupported sound builder local binding')
        key, expression = statement.targets[0].id, statement.values[0]
        if key in constants or key in helpers or key in local_track_helpers or key in ('require', '_', 'data', 'math'):
            raise ValueError('Shadowed sound builder binding')
        constants[key] = value(expression)

    for statement in tree.body.body:
        if isinstance(statement, lua.LocalAssign) and definition is None:
            if (len(statement.targets) == len(statement.values) == 1
                    and isinstance(statement.targets[0], lua.Name)
                    and isinstance(statement.values[0], lua.Call)
                    and isinstance(statement.values[0].func, lua.Name) and statement.values[0].func.id == 'require'):
                key, expression = statement.targets[0].id, statement.values[0]
                module = _value(expression.args[0]) if len(expression.args) == 1 else None
                if key in helpers or key in constants or key in ('require', '_', 'data', 'math') or module not in ('soundsetutil', 'audioutil'):
                    raise ValueError('Unsupported or shadowed sound builder import')
                helpers[key] = module
            else:
                local_constant(statement)
        elif (isinstance(statement, lua.Function) and isinstance(statement.name, lua.Name)
              and statement.name.id == 'data' and not statement.args and definition is None):
            definition = statement
        else:
            raise ValueError('Sound builder uses executable or ambiguous top-level statements')
    if definition is None:
        raise ValueError('Sound builder needs a data() function')

    tracks, events, updates, builder_name = [], {}, [], None

    def builder_call(node):
        if isinstance(node, lua.Call) and isinstance(node.func, lua.Name) and node.func.id in local_track_helpers:
            return node.func.id
        if (not isinstance(node, lua.Call) or not isinstance(node.func, lua.Index)
                or node.func.notation != lua.IndexNotation.DOT or not isinstance(node.func.value, lua.Name)
                or helpers.get(node.func.value.id) != 'soundsetutil' or not isinstance(node.func.idx, lua.Name)):
            raise ValueError('Unsupported sound builder call; manual script port required')
        return node.func.idx.id

    def gated_track_helper(function):
        """Recognize a six-argument wrapper with one brake-gated gain only."""
        if (not isinstance(function.name, lua.Name) or len(function.args) != 6
                or any(not isinstance(arg, lua.Name) for arg in function.args)
                or len(set(arg.id for arg in function.args)) != 6
                or any(arg.id in helpers or arg.id in ('math','require','_','ug_require') for arg in function.args)
                or len(function.body.body) != 1):
            raise ValueError('Unsupported local sound builder helper')
        outer_names = [arg.id for arg in function.args]
        call_node = function.body.body[0]
        if (not isinstance(call_node, lua.Call) or builder_call(call_node) != 'addTrack'
                or len(call_node.args) != 4 or any(not isinstance(arg, lua.Name) or arg.id != expected
                    for arg, expected in zip(call_node.args[:3], outer_names[:3]))):
            raise ValueError('Unsupported local sound track wrapper')
        callback_node = call_node.args[3]
        if (not isinstance(callback_node, lua.AnonymousFunction) or len(callback_node.args) != 2
                or any(not isinstance(arg, lua.Name) for arg in callback_node.args)
                or len(set(arg.id for arg in callback_node.args)) != 2
                or any(arg.id in helpers or arg.id in outer_names[3:] or arg.id in ('math','require','_','ug_require') for arg in callback_node.args)
                or len(callback_node.body.body) != 2):
            raise ValueError('Unsupported local sound track callback')
        track_name, input_name = [arg.id for arg in callback_node.args]
        branch, pitch_assignment = callback_node.body.body
        comparison = {lua.LessThanOp: '<', lua.GreaterThanOp: '>'}.get(type(branch.test)) if isinstance(branch,lua.If) else None
        if (comparison is None or not isinstance(branch.orelse, lua.Block)
                or len(branch.body.body) != 1 or len(branch.orelse.body) != 1
                or not isinstance(branch.test.left, lua.Index)
                or not isinstance(branch.test.left.value,lua.Name) or branch.test.left.value.id != input_name
                or (branch.test.left.idx.id if isinstance(branch.test.left.idx,lua.Name)
                    and branch.test.left.notation==lua.IndexNotation.DOT else _value(branch.test.left.idx)) != 'brakeDecel'):
            raise ValueError('Sound track gate must compare the source brakeDecel with a literal threshold')
        threshold = number(value(branch.test.right))

        def assigned(statement, component):
            if (not isinstance(statement,lua.Assign) or len(statement.targets)!=len(statement.values)
                    or len(statement.targets)!=1 or not isinstance(statement.targets[0],lua.Index)
                    or statement.targets[0].notation!=lua.IndexNotation.DOT
                    or not isinstance(statement.targets[0].value,lua.Name) or statement.targets[0].value.id!=track_name
                    or not isinstance(statement.targets[0].idx,lua.Name) or statement.targets[0].idx.id!=component):
                raise ValueError('Local sound helper may only assign its track gain and pitch')
            return statement.values[0]

        def sample_expression(expression, curve_name):
            if (not isinstance(expression,lua.Call) or not isinstance(expression.func,lua.Index)
                    or expression.func.notation!=lua.IndexNotation.DOT
                    or not isinstance(expression.func.value,lua.Name) or helpers.get(expression.func.value.id)!='audioutil'
                    or not isinstance(expression.func.idx,lua.Name) or expression.func.idx.id!='sampleCurve'
                    or len(expression.args)!=2 or not isinstance(expression.args[0],lua.Name)
                    or expression.args[0].id!=curve_name or not isinstance(expression.args[1],lua.Index)
                    or expression.args[1].notation!=lua.IndexNotation.SQUARE
                    or not isinstance(expression.args[1].value,lua.Name) or expression.args[1].value.id!=input_name
                    or not isinstance(expression.args[1].idx,lua.Name) or expression.args[1].idx.id!=outer_names[5]):
                raise ValueError('Local sound helper must sample its literal gain/pitch curves and declared input parameter')

        sample_expression(assigned(branch.body.body[0],'gain'),outer_names[3])
        fallback = number(value(assigned(branch.orelse.body[0],'gain')))
        sample_expression(assigned(pitch_assignment,'pitch'),outer_names[4])
        return {'comparison':comparison,'threshold':threshold,'fallbackGain':fallback}

    def track(name, distance, update):
        tracks.append({'name': name, 'refDist': number(distance, positive=True)})
        updates.append(update)

    def event(key, names, distance, update):
        if not isinstance(key, str) or isinstance(key, TranslatedString) or key in events:
            raise ValueError('Invalid or duplicate sound builder event key')
        events[key] = {'names': names, 'refDist': number(distance, positive=True)}
        updates.append(dict(update, eventKey=key))

    def sqrt_pitch(speed, low, high):
        number(speed, positive=True)
        start, end = low * low * speed, high * high * speed
        step = .025 if start < .1 else .05 if start < .2 else .1
        count = max(math.floor((end - start) / step + .5), 1)
        if count > 4096: raise ValueError('Sound builder curve exceeds safe export limit')
        return [[start + (end-start)*i/count, math.sqrt((start+(end-start)*i/count)/speed)] for i in range(count+1)]

    statements = definition.body.body
    if len(statements) > 4096:
        raise ValueError('Sound builder exceeds safe export limit')
    returned = False
    for index, statement in enumerate(statements):
        if isinstance(statement, lua.LocalFunction):
            key = statement.name.id if isinstance(statement.name,lua.Name) else None
            if not key or key in helpers or key in constants or key in local_track_helpers or key in (builder_name,'math','require','_','ug_require','data'):
                raise ValueError('Shadowed local sound builder helper')
            local_track_helpers[key] = gated_track_helper(statement)
        elif isinstance(statement, lua.LocalAssign):
            if (len(statement.targets) == len(statement.values) == 1 and isinstance(statement.targets[0], lua.Name)
                    and isinstance(statement.values[0], lua.Call) and builder_call(statement.values[0]) == 'makeSoundSet'):
                if builder_name is not None or statement.values[0].args:
                    raise ValueError('Sound builder must create exactly one empty sound set')
                builder_name = statement.targets[0].id
                if builder_name in helpers or builder_name in constants or builder_name in ('require', '_', 'math'):
                    raise ValueError('Shadowed sound builder binding')
            else:
                local_constant(statement)
        elif isinstance(statement, lua.Call):
            method = builder_call(statement)
            if (builder_name is None or not statement.args or not isinstance(statement.args[0], lua.Name)
                    or statement.args[0].id != builder_name):
                raise ValueError('Sound builder calls must target its local sound set')
            args = [value(node) for node in statement.args[1:]]
            if method in local_track_helpers and len(args) == 5:
                if script_writer is None:
                    raise ValueError('Brake-gated sound track requires a generated TF3 script writer')
                name, distance, gain_curve, pitch_curve, parameter = args
                if parameter not in ('speed01','power01') or isinstance(parameter,TranslatedString):
                    raise ValueError('Unsupported brake-gated sound input parameter')
                gain_curve, pitch_curve = points(gain_curve), points(pitch_curve)
                gate = local_track_helpers[method]
                audio = native.reference('scripts/audioutil.lua')
                script = ('function data()\n return { update = function(result, captureParams, currentInfo)\n'
                          '  local audio = ug_require "' + audio + '"\n'
                          '  if currentInfo.vehicle.brakeDecel ' + gate['comparison'] + ' ' + repr(gate['threshold']) + ' then\n'
                          '   result.gain = audio.sampleCurve(captureParams.gainCurve, currentInfo.vehicle.' + parameter + ')\n'
                          '  else\n   result.gain = ' + repr(gate['fallbackGain']) + '\n  end\n'
                          '  result.pitch = audio.sampleCurve(captureParams.pitchCurve, currentInfo.vehicle.' + parameter + ')\n'
                          ' end }\nend\n')
                target = script_writer('brake_gated_sound',script)
                if not isinstance(target,str) or not target.endswith('@update') or '::/' not in target:
                    raise ValueError('Sound script writer returned no qualified @update resource')
                track(name,distance,{'type':'Custom','params':{'customUpdateScript':target,
                                                            'customParams':{'gainCurve':gain_curve,'pitchCurve':pitch_curve}}})
                if report is not None:
                    report.setdefault('soundMigrations',[]).append({'resource':resource,'policy':'compile_verified_brake_gated_track',
                        'helper':method,'sourceInput':'brakeDecel','targetInput':'vehicle.brakeDecel',
                        'comparison':gate['comparison'],'threshold':gate['threshold'],'targetReference':target,'nativeTest':'not_run'})
            elif method == 'addTrackParam01' and len(args) == 5:
                track(args[0], args[1], sample(args[2], args[3], args[4]))
            elif method == 'addSimpleTrackParam01' and len(args) == 3:
                track(args[0], args[1], sample([[0, 0], [1, 1]], None, args[2]))
            elif method == 'addEventParam01' and len(args) == 6:
                event(args[0], args[1], args[2], sample(args[3], args[4], args[5]))
            elif method == 'addTrackSqueal' and len(args) == 2:
                track(args[0], args[1], {'type': 'Squeal', 'params': {}})
            elif method == 'addTrackBrake' and len(args) == 3:
                gain = number(args[2])
                if gain < 0: raise ValueError('Brake gain must be non-negative')
                track(args[0], args[1], {'type': 'Brake', 'params': {'maxGain': gain}})
            elif method == 'addEventClacks' and len(args) == 3:
                event('clacks', args[0], args[1], {'type': 'Clacks', 'params': {'axleRefWeight': number(number(args[2], positive=True)*1000, positive=True)}})
            elif method == 'addEvent' and len(args) == 3:
                event(args[0], args[1], args[2], {'type': 'None', 'params': {}})
            elif method == 'makeRoadVehicle2' and len(args) == 8:
                speeds, idle, idle_speed, idle_gain, drive, drive_speed, distance, parameter = args
                if not isinstance(speeds, list) or len(speeds) != 3:
                    raise ValueError('Road sound builder requires three speed thresholds')
                for speed in speeds: number(speed, positive=True)
                if not speeds[0] < speeds[1] < speeds[2]:
                    raise ValueError('Road sound speed thresholds must increase')
                number(idle_gain)
                track(idle, distance, sample([[0, idle_gain], [speeds[0], 1], [speeds[1], 1], [speeds[2], 0]], sqrt_pitch(idle_speed, .8, 1.25), parameter))
                track(drive, distance, sample([[speeds[1], 0], [speeds[2], 1]], sqrt_pitch(drive_speed, .8, 1.5), parameter))
            elif method == 'makeSteamTrain' and len(args) == 7:
                idle, fast, distance, names, event_distance, frequency, weight = args
                if 'chuffs' in events:
                    raise ValueError('Duplicate steam chuff event')
                tracks.extend([{'name': idle, 'refDist': number(distance, positive=True)},
                               {'name': fast, 'refDist': number(distance, positive=True)}])
                event('chuffs', names, event_distance,
                      {'type': 'Chuffs', 'params': {'chuffsFastFreq': number(frequency, positive=True),
                                                  'refWeight': number(number(weight, positive=True)*1000, positive=True)}})
            else:
                raise ValueError(f'Unsupported sound builder operation: {method}; manual script port required')
        elif (isinstance(statement, lua.Return) and index == len(statements)-1 and len(statement.values) == 1
              and isinstance(statement.values[0], lua.Name) and statement.values[0].id == builder_name):
            returned = True
        else:
            raise ValueError('Sound builder uses dynamic callbacks or control flow; manual script port required')
    if not returned or builder_name is None:
        raise ValueError('Sound builder must return its local sound set')
    return _finalize_sound(tracks, events, updates, resolve, native)

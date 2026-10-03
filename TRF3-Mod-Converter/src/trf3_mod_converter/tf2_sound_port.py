"""Translate recognized TF2 sound expressions to installed TF3 sound functions.

Only literal tables, constants and the helper patterns below are accepted.
Source Lua and its imports are never executed. This module contains no game code.
"""
from __future__ import annotations

import math
from luaparser import astnodes as lua

from .lua_metadata import _value, UnsupportedValue
from .resource_audit import parse_lua


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
    result = _value(node)
    def check(value):
        if isinstance(value, UnsupportedValue):
            raise ValueError(f"Computed sound data needs manual port: {value.reason}")
        if isinstance(value, dict):
            for v in value.values(): check(v)
        elif isinstance(value, list):
            for v in value: check(v)
    check(result)
    return result


def port_sound_set(text, resolve, native):
    tree = parse_lua(text)
    helpers = {}
    definition = None
    for statement in tree.body.body:
        if isinstance(statement, lua.LocalAssign) and definition is None and len(statement.targets) == len(statement.values) == 1:
            target, value = statement.targets[0], statement.values[0]
            if not (isinstance(target, lua.Name) and target.id not in helpers and target.id != 'data'
                    and isinstance(value, lua.Call) and isinstance(value.func, lua.Name) and value.func.id == 'require'
                    and len(value.args) == 1 and _value(value.args[0]) in ('audioutil', 'soundeffectsutil')):
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
    returned = None
    for statement in callback.body.body:
        if isinstance(statement, lua.LocalAssign) and returned is None and len(statement.targets) == len(statement.values) == 1 and isinstance(statement.targets[0], lua.Name):
            key = statement.targets[0].id
            if key in helpers or key == input_name or key in constants:
                raise ValueError("Sound constants shadow bindings")
            constants[key] = literal(statement.values[0])
        elif isinstance(statement, lua.Return) and returned is None and len(statement.values) == 1:
            returned = fields(statement.values[0], {'tracks', 'events'})
        else:
            raise ValueError("Sound updateFn uses unsupported control flow or assignments")
    if returned is None: raise ValueError("Sound updateFn must return track/event controls")

    def number(node):
        value = constants.get(node.id) if isinstance(node, lua.Name) else literal(node)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Expected finite numeric sound constant")
        return value

    def input_field(node, name):
        return isinstance(node, lua.Index) and node.notation == lua.IndexNotation.DOT and isinstance(node.value, lua.Name) and node.value.id == input_name and isinstance(node.idx, lua.Name) and node.idx.id == name

    def call(node, helper, function):
        return (isinstance(node, lua.Call) and isinstance(node.func, lua.Index) and node.func.notation == lua.IndexNotation.DOT
                and isinstance(node.func.value, lua.Name) and helpers.get(node.func.value.id) == helper
                and isinstance(node.func.idx, lua.Name) and node.func.idx.id == function)

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

    def control(node):
        if call(node, 'soundeffectsutil', 'squeal') and len(node.args) == 3 and all(input_field(a,k) for a,k in zip(node.args,('speed','sideForce','maxSideForce'))):
            return {'type':'Squeal', 'params':{}}
        if call(node, 'soundeffectsutil', 'brake') and len(node.args) == 3 and input_field(node.args[0],'speed') and input_field(node.args[1],'brakeDecel'):
            return {'type':'Brake', 'params':{'maxGain':number(node.args[2])}}
        if call(node, 'soundeffectsutil', 'clacks') and len(node.args) == 5 and all(input_field(node.args[i],k) for i,k in ((0,'speed'),(1,'weight'),(2,'numAxles'),(4,'gameSpeedUp'))):
            weight = number(node.args[3])
            if weight <= 0: raise ValueError("Clack reference weight must be positive")
            return {'type':'Clacks', 'params':{'axleRefWeight':weight*1000}}
        values = fields(node, {'gain','pitch'})
        if set(values) != {'gain','pitch'}: raise ValueError("Sound control requires gain and pitch")
        params = {}
        for key, expression in values.items():
            if any(call(expression, helper, 'sampleCurve') for helper in ('soundeffectsutil','audioutil')) and len(expression.args) == 2 and input_field(expression.args[1], 'speed01'):
                params[key+'Curve'] = curve(expression.args[0])
            else:
                value = number(expression)
                params[key+'Curve'] = [[0,value],[1,value]]
            params[key+'ScriptingInfoKey'] = 'vehicle'
            params[key+'ParamName'] = 'speed01'
        return {'type':'SampleCurve', 'params':params}

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
        raise ValueError("Sound definitions and update controls do not match")
    update_functions = [control(n) for n in track_controls]
    update_functions.extend(dict(control(n), eventKey=k) for k,n in event_controls.items())
    for entry in tracks:
        if not isinstance(entry,dict) or set(entry) != {'name','refDist'}: raise ValueError("Unsupported track attributes")
        entry['name'] = resolve(entry['name'], 'audio')
        entry['attrs'] = {'refDist':entry.pop('refDist')}
    for entry in events.values():
        if not isinstance(entry,dict) or set(entry) != {'names','refDist'} or not isinstance(entry['names'],list): raise ValueError("Unsupported event attributes")
        entry['names'] = [resolve(n,'audio') for n in entry['names']]
        entry['attrs'] = {'refDist':entry.pop('refDist')}
    for entry in [*tracks,*events.values()]:
        distance = entry['attrs']['refDist']
        if type(distance) not in (int,float) or not math.isfinite(distance) or distance <= 0:
            raise ValueError("Sound reference distance must be positive and finite")
    return {'tracks':tracks, 'events':events,
            'updateScript':{'fileName':native.reference('scripts/soundset_default.script@updateSoundSet'),
                            'params':{'updateFunctions':update_functions}}}

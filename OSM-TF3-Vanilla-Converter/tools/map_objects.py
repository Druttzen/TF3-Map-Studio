"""Retain mapped objects for matching against resources loaded by TF3. GPL-3.0."""
import math
import re


def tagged_height(tags):
    """Only explicit building height with understood units; never estimate levels."""
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(m|metres?|meters?|ft|feet)?\s*', tags.get('height', ''), re.IGNORECASE)
    if not match: return None
    height = float(match[1]) * (0.3048 if (match[2] or '').lower() in {'ft', 'feet'} else 1)
    return height if math.isfinite(height) and 0 < height <= 1000 else None


def object_kind(tags):
    if tags.get('building') not in (None, 'no'):
        value = tags['building']
        if value in {'industrial', 'warehouse', 'manufacture', 'factory'}: return 'industrial'
        if value in {'commercial', 'retail', 'supermarket', 'office'}: return 'commercial'
        if value in {'house', 'detached', 'residential', 'apartments', 'terrace', 'bungalow', 'semidetached_house'}: return 'residential'
        return 'building'
    for key, values in {
        'amenity': {'bench': 'bench', 'waste_basket': 'waste_basket', 'drinking_water': 'drinking_water',
                    'post_box': 'post_box', 'bicycle_parking': 'bicycle_parking'},
        'highway': {'street_lamp': 'street_lamp'},
        'natural': {'stone': 'rock', 'rock': 'rock'},
        'historic': {'memorial': 'memorial', 'monument': 'monument'},
        'man_made': {'water_tower': 'water_tower', 'lighthouse': 'lighthouse', 'storage_tank': 'storage_tank'},
        'power': {'tower': 'power_tower'},
    }.items():
        if tags.get(key) in values: return values[tags[key]]
    return None


def footprint(points):
    """Aligned rectangle from the longest boundary edge; no invented OSM height."""
    if len(points) < 3: return None
    a, b = max(zip(points, points[1:] + points[:1]), key=lambda pair: math.dist(*pair))
    angle = math.atan2(b[1]-a[1], b[0]-a[0])
    c, s = math.cos(angle), math.sin(angle)
    local = [(x*c+y*s, -x*s+y*c) for x, y in points]
    x0, x1 = min(x for x, _ in local), max(x for x, _ in local)
    y0, y1 = min(y for _, y in local), max(y for _, y in local)
    if x1-x0 < 1 or y1-y0 < 1: return None
    x, y = (x0+x1)/2, (y0+y1)/2
    return {'pos': [x*c-y*s, x*s+y*c], 'rotation': angle,
            'footprint': [list(p) for p in points], 'dimensions': [x1-x0, y1-y0]}


def prepare(data, nodes, ways, relations, positions, members_for, join_rings, on_map, job, warn):
    items = data['scenery']
    unavailable = {}
    consumed = set()
    labels = data['labels']

    def note_unavailable(tags):
        for key in ('amenity', 'tourism', 'railway', 'aeroway', 'power', 'man_made', 'historic'):
            if key in tags and tags[key] not in {'rail', 'tram', 'light_rail', 'subway', 'narrow_gauge', 'preserved', 'disused', 'fountain'}:
                name = key+'='+tags[key]
                unavailable[name] = unavailable.get(name, 0)+1

    def place(osm_type, osm_id, tags, pos):
        if tags.get('place') not in {'city', 'town', 'village', 'hamlet', 'suburb', 'quarter', 'neighbourhood'} or not tags.get('name'):
            return
        if not on_map(pos): return
        # A relation/area and its place node often describe the same settlement.
        if any(p['name'] == tags['name'] and math.dist(p['pos'], pos) < 300 for p in labels): return
        labels.append({'name': tags['name'], 'place': tags['place'], 'pos': list(pos),
                       'osm': {'type': osm_type, 'id': str(osm_id), 'tags': dict(tags)}})

    def add(osm_type, osm_id, tags, pos, geometry=None):
        kind = object_kind(tags)
        if kind and on_map(pos):
            item = {'pos': list(pos), 'rotation': 0, 'category': 'buildings' if tags.get('building') not in (None, 'no') else 'mappedObjects',
                    'match': {'kind': kind}, 'osm': {'type': osm_type, 'id': str(osm_id), 'tags': dict(tags)}}
            if geometry: item.update(geometry)
            if item['category'] == 'buildings':
                height = tagged_height(tags)
                if height is not None: item['match']['height'] = height
            items.append(item)
        elif not kind:
            note_unavailable(tags)

    for index, (osm_id, (_lat, _lon, tags)) in enumerate(nodes.items()):
        if index % 256 == 0: job.check()
        pos = positions[osm_id]
        # Existing explicitly configured tree/fountain/bollard/column entries stay intact.
        add('node', osm_id, tags, pos)
        place('node', osm_id, tags, pos)
    for index, (osm_id, relation) in enumerate(relations.items()):
        if index % 256 == 0: job.check()
        members, tags = relation
        if not (object_kind(tags) or tags.get('place')):
            note_unavailable(tags)
            continue
        if tags.get('type') != 'multipolygon':
            unavailable['unsupported_object_relation'] = unavailable.get('unsupported_object_relation', 0)+1
            continue
        try:
            outer_used = set()
            parts = members_for(osm_id, outer_used=outer_used)
            outer = join_rings(parts['outer'])
            inner = parts['inner']
            consumed.update(outer_used)
            if len(outer) != 1 or inner:
                warn('Mapped buildings/objects with courtyards or separate outer rings are recorded as unsupported geometry, not filled with a substitute.')
                unavailable['complex_object_geometry'] = unavailable.get('complex_object_geometry', 0)+1
                continue
            points = [positions[n] for n in outer[0]]
            geometry = footprint(points)
        except (ValueError, KeyError):
            unavailable['incomplete_object_geometry'] = unavailable.get('incomplete_object_geometry', 0)+1
            continue
        if not geometry or not all(on_map(p) for p in points): continue
        add('relation', osm_id, tags, geometry['pos'], geometry)
        place('relation', osm_id, tags, geometry['pos'])
    for index, (osm_id, (refs, tags)) in enumerate(ways.items()):
        if index % 256 == 0: job.check()
        if osm_id in consumed: continue
        if not (object_kind(tags) or tags.get('place')):
            note_unavailable(tags)
            continue
        if len(refs) < 4 or refs[0] != refs[-1] or any(n not in positions for n in refs):
            unavailable['incomplete_object_geometry'] = unavailable.get('incomplete_object_geometry', 0)+1
            continue
        points = [positions[n] for n in refs[:-1]]
        geometry = footprint(points)
        if not geometry or not all(on_map(p) for p in points): continue
        add('way', osm_id, tags, geometry['pos'], geometry)
        place('way', osm_id, tags, geometry['pos'])
    data['unavailableObjects'] = [{'tag': key, 'count': value} for key, value in sorted(unavailable.items())]
    data['objectMetadata'] = {'schema': 1, 'matching': 'vanilla first, then loaded active mods',
                              'buildingMode': 'decorative substitute; source footprint and all tags retained'}

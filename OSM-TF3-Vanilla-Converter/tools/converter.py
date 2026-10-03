"""OSM XML to a TF3 vanilla import dataset. Python standard library only.

GPL-3.0. Rebuild inspired by VacuumTube's OSM-TPF2-Importer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from settings import normalize_options, SPECIES, MODELS, MATERIALS
from job import Job, Cancelled
from hydrology import prepare as prepare_water

MOD_ID = 'druttzen_osm_vanilla'
ROADS = {'motorway','motorway_link','trunk','trunk_link','primary','primary_link',
         'secondary','secondary_link','tertiary','tertiary_link','residential',
         'unclassified','service','living_street','pedestrian','footway','path',
         'cycleway','track','steps'}
RAILS = {'rail','light_rail','subway','tram','narrow_gauge','preserved','disused'}
FOOTWAYS = {'pedestrian','footway','path','cycleway','track','steps'}
V = '::/'
TREES = [V+'assets/vegetation/trees/shgl_oak_01/shgl_oak_01.mdl',
         V+'assets/vegetation/trees/eu_lnd_01/eu_lnd_01.mdl',
         V+'assets/vegetation/trees/sgr_mpl_01/sgr_mpl_01.mdl']
CONIFERS = [V+'assets/vegetation/trees/confr_01/confr_01.mdl',
            V+'assets/vegetation/trees/sct_pn_01/sct_pn_01.mdl']
SHRUBS = [V+'assets/vegetation/trees/hzl_01/hzl_01.mdl',
          V+'assets/vegetation/trees/azalea_01/azalea_01.mdl']
OBJECTS = {'tree':TREES[0],
           'fountain':V+'assets/landmarks/msc/fountain.mdl',
           'bollard':V+'assets/stations/water/mooring_bollard_passengers.mdl',
           'advertising_column':V+'assets/buildings/com/advertisements/column_c_01.mdl'}
GROUND = {'asphalt':V+'terrain/materials/asphalt_01/asphalt_01.gtex',
          'dirt':V+'terrain/materials/dirt/dirt.gtex',
          'grass':V+'terrain/materials/grass_cutted_01/grass_cutted_01.gtex'}


def read_osm(path, job=None):
    path = Path(path)
    job=job or Job()
    job.update(0,'Reading OSM',path.name)
    if path.suffix.lower() not in {'.osm','.xml'}:
        raise ValueError('Use an OSM XML file ending in .osm or .xml. Convert PBF to XML first.')
    file_size=path.stat().st_size
    count=0
    nodes, ways, relations, bounds = {}, {}, {}, None
    # Clearing top-level entities releases parsed XML while preserving their data.
    with path.open('rb') as source:
        digest=hashlib.sha256()
        class HashedReader:
            def read(self,n=-1):
                chunk=source.read(n); digest.update(chunk); return chunk
        events = ET.iterparse(HashedReader(), events=('start','end'))
        _, root = next(events)
        if root.tag != 'osm': raise ValueError('The input is not an OSM XML document.')
        for event, elem in events:
            if event != 'end': continue
            if elem.tag == 'bounds':
                bounds = tuple(float(elem.attrib[k]) for k in ('minlat','minlon','maxlat','maxlon'))
            elif elem.tag in {'node','way','relation'}:
                count+=1
                if count%256==0: job.portion(0,20,source.tell(),file_size,'Reading OSM',f'{count:,} entities')
                id = elem.attrib['id']
                tags = {child.attrib['k']:child.attrib['v'] for child in elem if child.tag=='tag'}
                if elem.tag == 'node':
                    lat,lon=float(elem.attrib['lat']),float(elem.attrib['lon'])
                    if not (math.isfinite(lat) and math.isfinite(lon) and -85<lat<85 and -180<=lon<=180):
                        raise ValueError('Invalid or unsupported coordinates at OSM node '+id)
                    nodes[id] = (lat,lon,tags)
                elif elem.tag == 'way':
                    ways[id] = ([child.attrib['ref'] for child in elem if child.tag=='nd'],tags)
                else:
                    relations[id] = ([dict(child.attrib) for child in elem if child.tag=='member'],tags)
                root.clear()
    if not nodes: raise ValueError('The OSM file contains no nodes.')
    job.source_sha256=digest.hexdigest()
    job.update(20,'Reading OSM',f'{len(nodes):,} nodes; {len(ways):,} ways')
    return nodes, ways, relations, bounds


def validate_bounds(bounds, size):
    if len(bounds)!=4 or not all(math.isfinite(x) for x in bounds):
        raise ValueError('Bounds must contain four finite numbers: minlat,minlon,maxlat,maxlon.')
    a,b,c,d = bounds
    if not (-85 < a < c < 85 and -180 <= b < d <= 180):
        raise ValueError('Bounds must have increasing latitude/longitude; latitude must be between -85 and 85.')
    if len(size)!=2 or any(not math.isfinite(x) or x<=0 for x in size):
        raise ValueError('Map width and height must be positive finite numbers in metres.')


def project(lat, lon, bounds, size):
    def mercator(y): return math.log(math.tan(math.pi/4+math.radians(y)/2))
    a,b,c,d = bounds
    return ((lon-b)/(d-b)-0.5)*size[0], ((mercator(lat)-mercator(a))/(mercator(c)-mercator(a))-0.5)*size[1]


def inside(p, ring):
    x,y = p
    hit = False
    for a,b in zip(ring,ring[1:]+ring[:1]):
        if (a[1]>y)!=(b[1]>y) and x < a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]):
            hit = not hit
    return hit


def signed_area(ring):
    return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:]+ring[:1]))/2


def join_rings(parts):
    """Join OSM member ways, independently of member order/direction."""
    pending = [list(p) for p in parts if len(p)>1]
    result = []
    while pending:
        ring = pending.pop(0)
        while ring[0]!=ring[-1]:
            matches = [(i,False) for i,p in enumerate(pending) if p[0]==ring[-1]]
            matches += [(i,True) for i,p in enumerate(pending) if p[-1]==ring[-1]]
            if len(matches)!=1:
                raise ValueError('Incomplete or ambiguous multipolygon ring at node '+str(ring[-1]))
            i, reverse = matches[0]
            extension = pending.pop(i)
            if reverse: extension.reverse()
            ring.extend(extension[1:])
        if len(ring)<4 or len(set(ring[:-1]))<3:
            raise ValueError('Polygon ring has fewer than three distinct nodes.')
        result.append(ring[:-1])
    return result


def clip_segment(p0,p1,width,height):
    x,y = p0
    dx,dy = p1[0]-x,p1[1]-y
    low,high = 0.0,1.0
    for p,q in [(-dx,x+width/2),(dx,width/2-x),(-dy,y+height/2),(dy,height/2-y)]:
        if abs(p)<1e-12:
            if q<0: return None
        else:
            t=q/p
            if p<0: low=max(low,t)
            else: high=min(high,t)
            if low>high: return None
    return (x+low*dx,y+low*dy),(x+high*dx,y+high*dy),low,high


def clip_polygon(points,width,height):
    for axis,limit,positive in [(0,-width/2,True),(0,width/2,False),(1,-height/2,True),(1,height/2,False)]:
        output = []
        if not points: break
        for a,b in zip(points[-1:]+points[:-1],points):
            ain = a[axis]>=limit if positive else a[axis]<=limit
            bin = b[axis]>=limit if positive else b[axis]<=limit
            if ain!=bin:
                t=(limit-a[axis])/(b[axis]-a[axis])
                output.append((a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])))
            if bin: output.append(b)
        points=output
    return points


def triangulate(rings):
    """Scanline trapezoids preserve concave boundaries and holes (even/odd fill)."""
    levels=sorted(set(p[1] for ring in rings for p in ring))
    sides=[(a,b) for ring in rings for a,b in zip(ring,ring[1:]+ring[:1]) if a[1]!=b[1]]
    for y0,y1 in zip(levels,levels[1:]):
        mid=(y0+y1)/2
        active=[(a,b) for a,b in sides if min(a[1],b[1])<mid<max(a[1],b[1])]
        def x_at(edge,y):
            a,b=edge
            return a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
        active.sort(key=lambda edge:x_at(edge,mid))
        if len(active)%2: raise ValueError('Polygon cannot be filled: odd number of boundary crossings.')
        for left,right in zip(active[::2],active[1::2]):
            quad=[(x_at(left,y0),y0),(x_at(right,y0),y0),(x_at(right,y1),y1),(x_at(left,y1),y1)]
            for triangle in [[quad[0],quad[1],quad[2]],[quad[0],quad[2],quad[3]]]:
                if abs(signed_area(triangle))>1e-6: yield triangle


def direction(tags):
    value=tags.get('oneway','').lower()
    if value in {'-1','reverse'}: return -1
    if value in {'yes','true','1'}: return 1
    if value in {'no','false','0'}: return 0
    return 1 if tags.get('junction') in {'roundabout','circular'} or tags.get('highway')=='motorway' else 0


def speed(tags):
    raw=tags.get('maxspeed','').lower().strip()
    try:
        n=float(raw[:-3]) * 1.609344 if raw.endswith('mph') else float(raw.removesuffix('km/h').strip())
        return n if math.isfinite(n) and n>0 else None
    except ValueError: return None


def choose_template(tags, options=None):
    options=options or normalize_options()
    if tags.get('railway') in RAILS and tags.get('highway') not in ROADS:
        limit=speed(tags) or 120
        kind='simple' if tags['railway']=='disused' else 'high_speed' if limit>options['high_speed_threshold'] else 'standard'
        if options['rail_profile']!='Automatic': kind={'Simple':'simple','Standard':'standard','High speed':'high_speed'}[options['rail_profile']]
        electric=tags.get('electrified') not in {None,'no','none'}
        if options['electrification']!='Automatic': electric=options['electrification']=='Always overhead'
        suffix='_catenary' if electric else ''
        return V+f'infrastructure/track/{kind}/{kind}{suffix}.street_template', 'TRACK'
    kind=tags['highway']
    try: lanes=max(1,int(tags.get('lanes','2')))
    except ValueError: lanes=2
    if kind in FOOTWAYS:
        if tags.get('railway')=='tram':
            return V+'infrastructure/street/town/town_new_small_tram_electrified.street_template','STREET'
        return V+'infrastructure/street/town/town_new_xsmall.street_template','STREET'
    if direction(tags):
        size='xsmall' if lanes<=1 else 'small' if lanes==2 else 'medium'
        name=f'town_new_one_way_{size}'
        if tags.get('railway')=='tram':
            name=f'town_new_one_way_{"small" if size=="xsmall" else size}_tram_electrified'
        return V+f'infrastructure/street/town/{name}.street_template','STREET'
    country=kind in {'motorway','trunk','primary','secondary','tertiary','unclassified'} and tags.get('lit')!='yes' and tags.get('railway')!='tram'
    if options['road_style']!='Automatic' and tags.get('railway')!='tram': country=options['road_style']=='Country'
    size='small' if lanes<=2 else 'medium' if lanes<=4 else 'large'
    if country: return V+f'infrastructure/street/country/country_new_{size}.street_template','STREET'
    suffix='_tram_electrified' if tags.get('railway')=='tram' else ''
    return V+f'infrastructure/street/town/town_new_{size}{suffix}.street_template','STREET'


def area_kind(tags):
    if tags.get('landuse')=='forest' or tags.get('natural')=='wood': return 'forest'
    if tags.get('natural') in {'scrub','heath'}: return 'shrubs'
    surface=tags.get('surface') or tags.get('landuse') or tags.get('natural')
    if surface in {'asphalt','paved','concrete','concrete:plates','paving_stones','sett','cobblestone'}: return 'asphalt'
    if surface in {'grass','grassland','meadow','recreation_ground','village_green','orchard'}: return 'grass'
    if surface in {'dirt','earth','ground','mud','gravel','fine_gravel','sand','beach','farmland','farmyard','construction','quarry','brownfield'}: return 'dirt'
    return None


def convert(path,bounds,size,spacing=18,max_trees=100000,*,options=None,progress=None,cancel=None,_job=None):
    job=_job or Job(progress,cancel)
    options=normalize_options(options if options is not None else {'forest_spacing':spacing,'shrub_spacing':spacing*.8,'max_generated_trees':max_trees})
    features=options['features']
    max_trees=options['max_generated_trees']
    nodes,ways,relations,file_bounds=read_osm(path,job)
    warnings=[]
    if bounds is None:
        bounds=file_bounds
        if bounds is None:
            bounds=(min(n[0] for n in nodes.values()),min(n[1] for n in nodes.values()),max(n[0] for n in nodes.values()),max(n[1] for n in nodes.values()))
            warnings.append('Bounds were inferred from nodes; check against the heightmap bounds.')
    bounds=tuple(bounds); size=tuple(size)
    validate_bounds(bounds,size)
    if not math.isfinite(spacing) or spacing<2: raise ValueError('Tree spacing must be at least 2 metres.')
    if not isinstance(max_trees,int) or max_trees<0: raise ValueError('Maximum tree count must be a non-negative integer.')
    positions={}
    for i,(id,n) in enumerate(nodes.items()):
        if i%256==0: job.portion(20,25,i,len(nodes),'Projecting coordinates')
        positions[id]=project(n[0],n[1],bounds,size)
    data={'schema':1,'id':'','bounds':list(bounds),'size':list(size),'nodes':{},'edges':[],
          'scenery':[],'labels':[],'warnings':warnings,'conversionSettings':options,
          'importOptions':{'batchSize':options['import_batch_size'],'interval':options['import_delay']}}
    def warn(text):
        if text not in warnings: warnings.append(text)
    def keep_node(id,p):
        data['nodes'][str(id)]={'pos':[round(p[0],6),round(p[1],6)]}
        return str(id)
    def on_map(p): return abs(p[0])<=size[0]/2 and abs(p[1])<=size[1]/2

    # Every segment keeps its way's tags; no property-blind node merging.
    for i,(id,(refs,tags)) in enumerate(ways.items()):
        job.portion(25,50,i,len(ways),'Building networks',f'Way {id}')
        highway=tags.get('highway')
        road=highway in ROADS and tags.get('area')!='yes'
        rail=tags.get('railway') in RAILS and not road
        if not (road or rail): continue
        if road and (not features['roads'] or highway in FOOTWAYS and not features['footpaths']): continue
        if rail and (not features['railways'] or tags.get('railway')=='disused' and not features['disused_tracks']): continue
        template,kind=choose_template(tags,options)
        one=direction(tags) if road else 0
        if one==-1: refs=list(reversed(refs))
        bridge=tags.get('bridge') not in {None,'no','false','0'}
        tunnel=tags.get('tunnel') not in {None,'no','false','0'}
        if bridge and not features['bridges'] or tunnel and not features['tunnels']: continue
        refs_valid=[r for r in refs if r in positions]
        first,last=(positions[refs_valid[0]],positions[refs_valid[-1]]) if refs_valid else ((0,0),(0,0))
        total=sum(math.dist(positions[a],positions[b]) for a,b in zip(refs,refs[1:]) if a in positions and b in positions)
        traversed=0
        for j,(a,b) in enumerate(zip(refs,refs[1:])):
            job.check()
            if a not in positions or b not in positions:
                warn(f'Way {id}: missing referenced node; incomplete segment skipped.')
                continue
            p0,p1=positions[a],positions[b]
            length=math.dist(p0,p1)
            clipped=clip_segment(p0,p1,*size)
            if clipped is None or length<1e-5:
                traversed+=length
                continue
            q0,q1,low,high=clipped
            n=max(1,math.ceil(math.dist(q0,q1)/options['rail_segment_length' if rail else 'road_segment_length']))
            for k in range(n):
                def point(t): return (q0[0]+t*(q1[0]-q0[0]),q0[1]+t*(q1[1]-q0[1]))
                x0,x1=point(k/n),point((k+1)/n)
                start=a if k==0 and low==0 else f'{id}:{j}:{k}'
                end=b if k==n-1 and high==1 else f'{id}:{j}:{k+1}'
                edge={'node0':keep_node(start,x0),'node1':keep_node(end,x1),
                      'template':template,'kind':kind,'osmWay':id,'speed':speed(tags),
                      'oneway':one!=0,'lanes':tags.get('lanes'),'gauge':tags.get('gauge'),
                      'bridge':bridge,'tunnel':tunnel}
                if bridge or tunnel:
                    if not on_map(first) or not on_map(last):
                        warn(f'Way {id}: structure endpoints outside map; height estimated from clipped segment.')
                        first,last=q0,q1
                    edge['heightGuide']={'start':list(first),'finish':list(last),
                        't0':(traversed+length*(low+(high-low)*k/n))/(total or 1),
                        't1':(traversed+length*(low+(high-low)*(k+1)/n))/(total or 1),
                        'depth':options['tunnel_depth']}
                signal_node=nodes.get(b)
                if rail and k==n-1 and high==1 and signal_node and signal_node[2].get('railway')=='signal':
                    signal_tags=signal_node[2]
                    edge['signal']={'backward':signal_tags.get('railway:signal:direction')=='backward','name':signal_tags.get('ref','OSM signal')}
                    warn('Railway signals require placement with the vanilla signal tool after import. Automatic TF3 signal placement is not enabled.')
                data['edges'].append(edge)
            traversed+=length
        if highway in FOOTWAYS:
            warn('Footpaths/cycleways/steps use the smallest vanilla road; exact dedicated paths are not available in this profile.')
        if rail and tags.get('gauge') not in {None,'1435'}:
            warn('Non-standard rail gauges are represented by vanilla standard-gauge track.')
        if rail and tags.get('electrified') in {'rail','4th_rail'}:
            warn('Third/fourth-rail electrification is represented by vanilla overhead electrified track.')

    areas=[]; covered=set()
    def members_for(id,role='outer',active=None,used=None):
        active=set() if active is None else set(active)
        used=set() if used is None else used
        if id in active: raise ValueError('Cyclic multipolygon relation '+id)
        if id not in relations: raise ValueError('Missing multipolygon relation '+id)
        active.add(id)
        result={'outer':[],'inner':[]}
        for member in relations[id][0]:
            job.check()
            member_role=member.get('role') or 'outer'
            if member_role not in result: continue
            effective=member_role if role=='outer' else ('inner' if member_role=='outer' else 'outer')
            if member['type']=='way':
                if member['ref'] not in ways: raise ValueError('Missing multipolygon way '+member['ref'])
                result[effective].append(ways[member['ref']][0]); used.add(member['ref'])
            elif member['type']=='relation':
                nested=members_for(member['ref'],effective,active,used)
                for key in result: result[key].extend(nested[key])
        return result
    for i,(id,(members,tags)) in enumerate(relations.items()):
        job.portion(50,56,i,len(relations),'Joining multipolygons')
        category=area_kind(tags)
        if tags.get('type')!='multipolygon' or not category: continue
        try:
            used=set()
            parts=members_for(id,used=used)
            outer=join_rings(parts['outer']); inner=join_rings(parts['inner'])
            if not outer: raise ValueError('No outer ring')
            areas.append((category,tags,outer,inner,id))
            covered.update(used)
        except ValueError as exc: warn(f'Relation {id}: {exc}; area skipped.')
    for i,(id,(refs,tags)) in enumerate(ways.items()):
        job.portion(56,60,i,len(ways),'Finding scenery areas')
        category=area_kind(tags)
        if category and id not in covered and len(refs)>3 and refs[0]==refs[-1]:
            areas.append((category,tags,[refs[:-1]],[],id))
    seed=hashlib.sha256((options['seed'] or json.dumps([bounds,size],sort_keys=True)).encode()).hexdigest()
    rng=random.Random(seed); trees=0
    for area_index,(category,tags,outer_ids,inner_ids,id) in enumerate(areas):
        job.portion(60,85,area_index,len(areas),'Generating scenery',f'Area {id}; {trees:,} trees')
        if not features['forests' if category=='forest' else 'shrubs' if category=='shrubs' else 'surfaces']: continue
        try:
            outers=[[positions[r] for r in ring] for ring in outer_ids]
            inners=[[positions[r] for r in ring] for ring in inner_ids]
        except KeyError:
            warn(f'Area {id}: missing polygon nodes; skipped.'); continue
        if category in {'forest','shrubs'}:
            models=[SPECIES[name] for name in options['shrub_species' if category=='shrubs' else 'conifer_species' if tags.get('leaf_type')=='needleleaved' else 'broadleaf_species']]
            step=options['shrub_spacing' if category=='shrubs' else 'forest_spacing']
            for ring in outers:
                minx,maxx=max(-size[0]/2,min(p[0] for p in ring)),min(size[0]/2,max(p[0] for p in ring))
                miny,maxy=max(-size[1]/2,min(p[1] for p in ring)),min(size[1]/2,max(p[1] for p in ring))
                y=miny+step/2
                while y<maxy and trees<max_trees:
                    job.update(60+25*(area_index+(y-miny)/max(step,maxy-miny))/max(1,len(areas)),'Generating scenery',f'{trees:,} trees')
                    x=minx+step/2
                    while x<maxx and trees<max_trees:
                        job.check()
                        jitter=step*options['tree_jitter']
                        p=(x+rng.uniform(-jitter,jitter),y+rng.uniform(-jitter,jitter))
                        if on_map(p) and inside(p,ring) and not any(inside(p,hole) for hole in inners):
                            data['scenery'].append({'model':rng.choice(models),'pos':list(p),'rotation':rng.random()*math.tau,'category':'vegetation'})
                            trees+=1
                        x+=step
                    y+=step
            if trees>=max_trees: warn('Tree limit reached; increase the limit to import additional forest trees.')
        else:
            try:
                for triangle in triangulate(outers+inners):
                    job.check()
                    face=clip_polygon(triangle,*size)
                    if len(face)>2 and abs(signed_area(face))>1e-5:
                        if signed_area(face)<0: face.reverse()
                        data['scenery'].append({'texture':MATERIALS[options['surface_materials'][category]],'face':[list(p) for p in face],'category':'surfaces'})
            except ValueError as exc: warn(f'Area {id}: {exc}; inspect surface boundaries.')
    for i,(id,(lat,lon,tags)) in enumerate(nodes.items()):
        if i%256==0: job.portion(85,90,i,len(nodes),'Placing objects and names')
        p=positions[id]
        if not on_map(p): continue
        category='tree' if tags.get('natural')=='tree' else 'fountain' if tags.get('amenity')=='fountain' else 'bollard' if tags.get('barrier')=='bollard' else 'advertising_column' if tags.get('advertising')=='column' else None
        if category and features[{'tree':'tree_nodes','fountain':'fountains','bollard':'bollards','advertising_column':'advertising_columns'}[category]]:
            data['scenery'].append({'model':MODELS[options['object_models'][category]],'pos':list(p),'rotation':math.radians(options['object_rotation']),'category':'vegetation' if category=='tree' else 'objects'})
        if features['place_markers'] and tags.get('place') in {'city','town','village','suburb','quarter','neighbourhood'} and tags.get('name'):
            data['labels'].append({'pos':list(p),'name':tags['name']})
    if data['labels']:
        warn('Place markers are decorative models, not simulated towns. Read their recorded names and coordinates with Show place names.')
    if any(tags.get('building') not in {None,'no'} for _,tags in ways.values()):
        warn('OSM building footprints are not imported. Add vanilla buildings and functioning towns with the game tools.')
    if any(e['bridge'] or e['tunnel'] for e in data['edges']):
        warn('Bridge/tunnel heights are estimated from terrain at endpoints; inspect grades and clearances after import.')
    prepare_water(data,nodes,ways,relations,positions,members_for,join_rings,triangulate,
                  clip_polygon,signed_area,job,warn,options['waterway_width'],inside,
                  build_geometry=features['waterways'])
    if any(tags.get('railway')=='signal' for _,_,tags in nodes.values()):
        warn('Railway signals require placement with the vanilla signal tool after import. Automatic TF3 signal placement is not enabled.')
    if data['edges']:
        warn('Vanilla road/track profiles approximate OSM lane counts, widths and speed limits; original tag values are retained in the dataset.')
    job.update(90,'Finalizing map',f"{len(data['edges']):,} segments; {len(data['scenery']):,} scenery items")
    payload=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    data['id']=hashlib.sha256(payload.encode()).hexdigest()[:24]
    return data


def lua(value):
    if value is None: return 'nil'
    if value is True: return 'true'
    if value is False: return 'false'
    if isinstance(value,str):
        # Decimal escapes avoid JSON-only unicode escapes and injection through newlines.
        return '"'+''.join('\\'+str(ord(c)).zfill(3) if ord(c)<32 else '\\\\' if c=='\\' else '\\"' if c=='"' else c for c in value)+'"'
    if isinstance(value,(int,float)):
        if not math.isfinite(value): raise ValueError('Non-finite output number')
        return repr(value)
    if isinstance(value,list): return '{'+','.join(lua(v) for v in value)+'}'
    if isinstance(value,dict): return '{'+','.join('['+lua(str(k))+']='+lua(v) for k,v in value.items())+'}'
    raise TypeError(type(value))


def atomic_write(path,text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f: f.write(text)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def preview_data(data):
    edges=data['edges'][:2000]
    node_ids={edge[key] for edge in edges for key in ('node0','node1')}
    return {'size':data['size'],'nodes':{id:data['nodes'][id] for id in node_ids}, 'edges':edges,
            'scenery':data['scenery'][:1200], 'labels':data['labels'][:100],
            'limited':len(data['edges'])>2000 or len(data['scenery'])>1200 or len(data['labels'])>100}


def write_outputs(source,data_path,report_path,bounds,size,spacing,max_trees,options,progress,cancel):
    source=Path(source).resolve(); data_path=Path(data_path).resolve(); report_path=Path(report_path).resolve()
    if source in {data_path,report_path}: raise ValueError('Input and output paths must differ.')
    job=Job(progress,cancel)
    data=convert(source,bounds,size,spacing,max_trees,options=options,_job=job)
    report={'dataset':data['id'],'input':source.name,'bounds':data['bounds'],'mapSize':data['size'],
            'edges':len(data['edges']),'sceneryItems':len(data['scenery']),'placeLabels':len(data['labels']),
            'waterFeatures':len(data.get('waterFeatures',[])),
            'waterMetadata':{**data['waterMetadata'],'features':data['waterFeatures']},
            'warnings':data['warnings'],'settings':data['conversionSettings'],'output':str(data_path),
            'report':str(report_path),'sourceSha256':job.source_sha256,
            'alignment':{'projection':'EPSG:3857 scaled to map size','origin':'centre',
                         'north':'positiveY','pngRows':'north to south'}}
    staged=[]
    try:
        # Prepare both outputs before replacing either existing file.
        data_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=data_path.name+'.',dir=data_path.parent)
        staged.append(Path(tmp))
        total=sum(len(v) if isinstance(v,(list,dict)) else 1 for v in data.values())
        count=0
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write('-- Generated OSM import data. GPL-3.0.\nreturn {\n')
            for key,value in data.items():
                f.write('['+lua(key)+']=')
                if isinstance(value,(list,dict)):
                    f.write('{\n')
                    values=value.items() if isinstance(value,dict) else enumerate(value,1)
                    for subkey,item in values:
                        job.portion(90,97,count,total,'Writing Lua map')
                        f.write(('['+lua(str(subkey))+']=' if isinstance(value,dict) else '')+lua(item)+',\n')
                        count+=1
                    f.write('},\n')
                else:
                    job.check(); f.write(lua(value)+',\n'); count+=1
            f.write('}\n'); f.flush(); os.fsync(f.fileno())
        digest=hashlib.sha256()
        with staged[0].open('rb') as lua_file:
            while chunk:=lua_file.read(1024*1024):
                job.check(); digest.update(chunk)
        report['luaSha256']=digest.hexdigest()
        fd,tmp=tempfile.mkstemp(prefix=report_path.name+'.',dir=report_path.parent)
        staged.append(Path(tmp))
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            json.dump(report,f,indent=2,ensure_ascii=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
        job.update(98,'Saving output files',force=True)
        job.check()
        # Cancellation stops before commit; a completed commit is always reported as success.
        job.cancel=None
        backup=None
        if data_path.exists():
            fd,tmp=tempfile.mkstemp(prefix=data_path.name+'.backup.',dir=data_path.parent); os.close(fd)
            backup=Path(tmp); staged.append(backup); shutil.copyfile(data_path,backup)
        os.replace(staged[0],data_path)
        try: os.replace(staged[1],report_path)
        except OSError:
            if backup: os.replace(backup,data_path)
            else: data_path.unlink()
            raise
        job.update(100,'Conversion complete',force=True)
    finally:
        for temporary in staged:
            if temporary.exists(): temporary.unlink()
    report['_preview']=preview_data(data)
    return report


def export(path,mod_folder,bounds,size,spacing=18,max_trees=100000,*,options=None,progress=None,cancel=None):
    target=Path(mod_folder).resolve()
    if not (target/'mod.json').exists(): raise ValueError('Select the druttzen_osm_vanilla mod folder containing mod.json.')
    definition=json.loads((target/'mod.json').read_text(encoding='utf-8-sig'))
    if definition.get('modId')!=MOD_ID: raise ValueError('The selected folder is not the OSM TF3 Vanilla mod.')
    data_path=target/'content/osm/dataset.lua'
    report_path=target/'import-report.json'
    return write_outputs(path,data_path,report_path,bounds,size,spacing,max_trees,options,progress,cancel)


def export_file(path,output,bounds,size,spacing=18,max_trees=100000,*,options=None,progress=None,cancel=None):
    output=Path(output)
    if output.suffix.lower()!='.lua': raise ValueError('The output filename must end in .lua.')
    return write_outputs(path,output,output.with_suffix('.report.json'),bounds,size,spacing,max_trees,options,progress,cancel)


def template_folder():
    return Path(sys._MEIPASS)/'mod_template' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]/'mod'/MOD_ID


def export_new_mod(path,mod_folder,bounds,size,spacing=18,max_trees=100000,*,options=None,progress=None,cancel=None):
    target=Path(mod_folder).resolve()
    if target.name!=MOD_ID: raise ValueError('The new mod folder must be named '+MOD_ID+'.')
    if target.exists(): raise ValueError('That mod folder already exists. Choose Update installed mod to replace its dataset.')
    target.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.osm-tf3-create-',dir=target.parent)).resolve()
    try:
        shutil.copytree(template_folder(),staging,dirs_exist_ok=True,ignore=shutil.ignore_patterns('import-report.json','__pycache__'))
        # Suppress 100% until the complete mod folder is in its final location.
        relay=(lambda pct,stage,detail: progress(min(99,pct),stage,detail)) if progress else None
        result=export(path,staging,bounds,size,spacing,max_trees,options=options,progress=relay,cancel=cancel)
        result['output']=str(target/'content/osm/dataset.lua'); result['report']=str(target/'import-report.json')
        atomic_write(staging/'import-report.json',json.dumps({k:v for k,v in result.items() if k!='_preview'},indent=2,ensure_ascii=False)+'\n')
        Job(cancel=cancel).check()
        if target.exists(): raise ValueError('The mod folder was created by another process; nothing was replaced.')
        staging.rename(target)
        if progress: progress(100,'Conversion complete','Standalone mod created')
        return result
    finally:
        # Only remove the freshly-created staging directory, never an existing mod.
        if staging.exists() and staging.parent==target.parent and staging.name.startswith('.osm-tf3-create-'):
            shutil.rmtree(staging)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Convert OSM XML for the standalone TF3 vanilla importer.')
    parser.add_argument('input',type=Path)
    destination=parser.add_mutually_exclusive_group(required=True)
    destination.add_argument('--mod',type=Path,help='Installed druttzen_osm_vanilla folder')
    destination.add_argument('--output',type=Path,help='Standalone Lua dataset file')
    destination.add_argument('--new-mod',type=Path,help='Create a complete standalone mod folder')
    parser.add_argument('--settings',type=Path,help='JSON conversion settings or app profile')
    parser.add_argument('--size',type=float,nargs=2,required=True,metavar=('WIDTH','HEIGHT'))
    parser.add_argument('--bounds',type=float,nargs=4,metavar=('MINLAT','MINLON','MAXLAT','MAXLON'))
    parser.add_argument('--tree-spacing',type=float,default=18)
    parser.add_argument('--max-trees',type=int,default=100000)
    args=parser.parse_args(argv)
    try:
        options=json.loads(args.settings.read_text(encoding='utf-8-sig')) if args.settings else None
        if options and 'options' in options: options=options['options']
        action=export if args.mod else export_file if args.output else export_new_mod
        report=action(args.input,args.mod or args.output or args.new_mod,args.bounds,args.size,args.tree_spacing,args.max_trees,options=options)
    except (OSError,ValueError,KeyError,ET.ParseError) as exc: parser.exit(2,'Conversion failed: '+str(exc)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='_preview'},indent=2,ensure_ascii=False))


if __name__=='__main__': main()

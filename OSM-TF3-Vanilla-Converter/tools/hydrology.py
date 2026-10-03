"""OSM water geometry preparation. Terrain is changed only by the game mod."""
import math

DIRTY_GROUND = 'druttzen_osm_vanilla::/osm/dirty_water.gtex'


def validate_rings(rings,outer_count,inside):
    """Reject malformed topology instead of filling an uncharted area."""
    if sum(map(len,rings))>2000: raise ValueError('Water boundary is too complex for the shallow-water topology budget')
    def intersects(a,b,c,d):
        def cross(p,q,r): return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
        def on(p,q,r): return min(p[0],q[0])-1e-8<=r[0]<=max(p[0],q[0])+1e-8 and min(p[1],q[1])-1e-8<=r[1]<=max(p[1],q[1])+1e-8
        x,y,z,w=cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
        return (x*y<0 and z*w<0) or any(abs(v)<1e-8 and on(p,q,r) for v,p,q,r in ((x,a,b,c),(y,a,b,d),(z,c,d,a),(w,c,d,b)))
    edges=[]
    for ring in rings:
        if len(ring)<3 or len(set(ring))!=len(ring): raise ValueError('Degenerate or repeated water boundary vertices')
        edges.append(list(zip(ring,ring[1:]+ring[:1])))
    for ri,segments in enumerate(edges):
        for i,(a,b) in enumerate(segments):
            for j in range(i+1,len(segments)):
                if j==i+1 or (i==0 and j==len(segments)-1): continue
                if intersects(a,b,*segments[j]): raise ValueError('Self-intersecting water boundary')
        for rj in range(ri+1,len(edges)):
            if any(intersects(a,b,c,d) for a,b in segments for c,d in edges[rj]):
                raise ValueError('Crossing or touching water rings need review')
    for i,ring in enumerate(rings):
        if i<outer_count:
            if any(inside(ring[0],other) or inside(other[0],ring) for other in rings[:i]):
                raise ValueError('Overlapping outer water rings')
        else:
            if sum(inside(ring[0],outer) for outer in rings[:outer_count])!=1:
                raise ValueError('Water island is outside its mapped outer boundary')
            if any(inside(ring[0],other) or inside(other[0],ring) for other in rings[outer_count:i]):
                raise ValueError('Nested or overlapping water islands need review')


def kind(tags):
    if tags.get('water') in {'pond', 'basin'} or tags.get('landuse') == 'basin':
        return 'shallow'
    if tags.get('waterway') in {'stream', 'river', 'ditch', 'drain', 'canal', 'riverbank'} or tags.get('water') in {'stream', 'river', 'ditch', 'drain', 'canal'}:
        return 'shallow'
    if tags.get('water') in {'lake', 'reservoir'} or tags.get('landuse') == 'reservoir':
        return 'lake'
    if tags.get('natural') == 'water':
        return 'water-area'
    if tags.get('natural') == 'spring' or tags.get('type') == 'waterway' or any(tags.get(k) not in {None, '', 'no'} for k in ('water', 'waterway')):
        return 'metadata-only'
    return None


def water_relations(nodes,ways,relations,job):
    """Also retain water containers whose tags exist only on their members."""
    categories={id:kind(tags) for id,(_,tags) in relations.items() if kind(tags)}
    parents={}
    for id,(members,tags) in relations.items():
        job.check()
        if tags.get('type') not in {'multipolygon','waterway'}: continue
        for member in members:
            parents.setdefault((member['type'],member['ref']),[]).append(id)
    pending=[('relation',id) for id in categories]
    pending.extend(('way',id) for id,(_,tags) in ways.items() if kind(tags))
    pending.extend(('node',id) for id,(_,_,tags) in nodes.items() if kind(tags))
    while pending:
        job.check()
        for parent in parents.get(pending.pop(),[]):
            if parent not in categories:
                categories[parent]='metadata-only'
                pending.append(('relation',parent))
    return categories


def source_metadata(nodes, ways, relations, positions, job, relation_categories):
    """Retain referenced OSM entities once, including broken/cyclic relations.

    This graph preserves source topology, not an inferred water surface. Missing
    references never get invented coordinates; XML editor account data is unused.
    """
    metadata={'schema':1,
              'coordinates':{'geographic':'EPSG:4326', 'geographicFields':['lat','lon'],
                             'map':'EPSG:3857 scaled to dataset bounds and size',
                             'mapFields':['x','y'], 'mapUnits':'metres',
                             'origin':'centre', 'north':'positiveY'},
              'nodes':{},'ways':{},'relations':{},'missingRefs':[]}
    tables={'node':nodes,'way':ways,'relation':relations}
    output={'node':metadata['nodes'],'way':metadata['ways'],'relation':metadata['relations']}
    pending=[]
    for entity_type,table in tables.items():
        for id,entity in table.items():
            job.check()
            if kind(entity[-1]) or entity_type=='relation' and id in relation_categories:
                pending.append((entity_type,id))
    visited=set()
    while pending:
        job.check()
        entity_type,id=pending.pop()
        if (entity_type,id) in visited: continue
        visited.add((entity_type,id))
        if entity_type not in tables or id not in tables[entity_type]:
            metadata['missingRefs'].append({'type':entity_type,'ref':id})
            continue
        entity=tables[entity_type][id]
        record={'tags':dict(entity[-1])}
        if entity_type=='node':
            record.update(lat=entity[0],lon=entity[1],mapPos=list(positions[id]))
        elif entity_type=='way':
            record['nodeRefs']=list(entity[0])
            pending.extend(('node',ref) for ref in entity[0])
        else:
            record['members']=[dict(member) for member in entity[0]]
            pending.extend((member['type'],member['ref']) for member in entity[0])
        output[entity_type][id]=record
    metadata['missingRefs'].sort(key=lambda item:(item['type'],item['ref']))
    return metadata


def split_triangle(face, job, limit=8):
    pending = [face]
    while pending:
        job.check()
        tri = pending.pop()
        lengths = [math.dist(tri[i], tri[(i+1)%3]) for i in range(3)]
        i = max(range(3), key=lengths.__getitem__)
        if lengths[i] <= limit:
            yield tri
        else:
            a,b,c = tri[i],tri[(i+1)%3],tri[(i+2)%3]
            m = ((a[0]+b[0])/2, (a[1]+b[1])/2)
            pending.extend([[a,m,c], [m,b,c]])


def prepare(data, nodes, ways, relations, positions, members_for, join_rings,
            triangulate, clip_polygon, signed_area, job, warn, fallback_width,inside,
            build_geometry=True):
    """Keep raw height tags separate from game heights; never change sea level."""
    features=[]; candidates=[]; covered=set()
    relation_categories=water_relations(nodes,ways,relations,job)
    data['waterMetadata']=source_metadata(nodes,ways,relations,positions,job,relation_categories)
    nested_relations=set()
    # Member boundaries belong to the whole multipolygon, even when its rings
    # are broken. Importing an outer alone could fill an island or missing area.
    for id in relation_categories:
        members,tags=relations[id]
        if tags.get('type')!='multipolygon': continue
        for member in members:
            job.check()
            if member.get('role','') not in {'','outer','inner'}: continue
            if member['type']=='way': covered.add(member['ref'])
            elif member['type']=='relation': nested_relations.add(member['ref'])
    def new_feature(entity_type,id,tags,category):
        feature={'osmId':entity_type+':'+id,'source':{'type':entity_type,'ref':id},
                 'kind':category,'name':tags.get('name',''),'tags':dict(tags),
                 'rings':[],'centreline':[],'outerRingCount':0,
                 'height':{'raw':tags.get('ele'),'datum':'OSM-untransformed'},
                 'status':'pending'}
        features.append(feature)
        return feature
    def invalid(feature,exc):
        feature.update(status='needs-review',reason=str(exc))
        warn(f"Water {feature['osmId']}: {exc}; metadata retained without partial water geometry.")
    for id,(_,tags) in relations.items():
        job.check()
        category=relation_categories.get(id)
        if not category: continue
        feature=new_feature('relation',id,tags,category)
        if id in nested_relations:
            feature.update(status='metadata-only',reason='Member of a water multipolygon; parent controls the complete geometry.')
            continue
        if tags.get('type')!='multipolygon':
            feature.update(status='metadata-only',reason='Relation is not a water multipolygon; original members retained.')
            continue
        try:
            used=set(); parts=members_for(id,used=used)
            outers=join_rings(parts['outer']); inners=join_rings(parts['inner'])
            if not outers: raise ValueError('No outer water ring')
            rings=[[positions[n] for n in ring] for ring in outers+inners]
            feature.update(rings=[[list(p) for p in ring] for ring in rings],outerRingCount=len(outers))
            candidates.append((feature,rings,None))
            covered.update(used)
        except (ValueError,KeyError,RecursionError) as exc:
            invalid(feature,exc)
    for id,(refs,tags) in ways.items():
        job.check()
        category=kind(tags)
        if not category or id in covered: continue
        feature=new_feature('way',id,tags,category)
        if category=='metadata-only':
            feature.update(status='metadata-only',reason='Water tag has no supported geometry treatment; original nodes retained.')
            continue
        try:
            # Missing nodes break the feature; they never create a shortcut.
            line=[positions[n] for n in refs]
            if len(line)<2: raise ValueError('Too few water nodes')
            closed=len(refs)>3 and refs[0]==refs[-1]
            area=category in {'lake','water-area'} or tags.get('natural')=='water' or tags.get('water') in {'pond','basin'} or tags.get('landuse')=='basin' or tags.get('waterway')=='riverbank' or tags.get('area')=='yes'
            if area and not closed: raise ValueError('Water area boundary is not closed')
            rings=[line[:-1]] if closed else None
            centreline=None if closed else line
            feature.update(rings=[[list(p) for p in ring] for ring in (rings or [])],
                           centreline=[list(p) for p in (centreline or [])],outerRingCount=1 if closed else 0)
            candidates.append((feature,rings,centreline))
        except (ValueError,KeyError) as exc:
            invalid(feature,exc)
    for id,(_,_,tags) in nodes.items():
        job.check()
        category=kind(tags)
        if category:
            feature=new_feature('node',id,tags,category)
            feature.update(status='metadata-only',reason='Point feature has no mapped water boundary or centreline.')

    # Reserve planned network corridors without moving any terrain or nodes.
    # Conservative rectangle tests may omit extra water near a crossing.
    buckets={}; cell=64; margin=20
    for edge in data['edges'] if build_geometry else []:
        job.check()
        a=data['nodes'][edge['node0']]['pos']; b=data['nodes'][edge['node1']]['pos']
        bounds=(min(a[0],b[0])-margin,min(a[1],b[1])-margin,max(a[0],b[0])+margin,max(a[1],b[1])+margin)
        for x in range(math.floor(bounds[0]/cell),math.floor(bounds[2]/cell)+1):
            for y in range(math.floor(bounds[1]/cell),math.floor(bounds[3]/cell)+1):
                buckets.setdefault((x,y),[]).append(bounds)
    def reserved(face):
        x0=min(p[0] for p in face); x1=max(p[0] for p in face)
        y0=min(p[1] for p in face); y1=max(p[1] for p in face)
        for x in range(math.floor(x0/cell),math.floor(x1/cell)+1):
            for y in range(math.floor(y0/cell),math.floor(y1/cell)+1):
                if any(x0<=b[2] and x1>=b[0] and y0<=b[3] and y1>=b[1] for b in buckets.get((x,y),())): return True
        return False

    remaining=30000
    for feature,rings,line in candidates:
        job.check()
        id=feature['osmId']; category=feature['kind']; tags=feature['tags']; outer_count=feature['outerRingCount']
        if not build_geometry:
            feature.update(status='metadata-only',reason='Water geometry export is disabled; source metadata retained.')
            continue
        if category not in {'shallow','lake'}:
            feature.update(status='metadata-only',reason='Water type is unspecified or unsupported; no lake or stream treatment inferred.')
            continue
        if category=='lake':
            feature['status']='local-sea-level-unsupported'
            warn('Mapped lakes retained: TF3 exposes a global sea level; no supported per-lake sea-level command was found. Lakes are not flooded automatically.')
            continue
        try:
            width=None
            if line:
                raw=tags.get('width',tags.get('est_width'))
                if raw is None:
                    width=fallback_width; feature['widthSource']='configured fallback'
                    warn(f'Water {id}: width missing; configured {fallback_width:g} m fallback is an approximation.')
                else:
                    width=float(raw.removesuffix(' m').strip())
                    feature['widthSource']='OSM width' if 'width' in tags else 'OSM est_width'
                if not math.isfinite(width) or not 0.1<=width<=20:
                    raise ValueError('Small-water width must be 0.1–20 m; broad or ambiguous waterways need a separate treatment')
                feature['width']=width
                def stream_faces():
                    for a,b in zip(line,line[1:]):
                        job.check()
                        length=math.dist(a,b)
                        if length<1e-6: continue
                        nx=-(b[1]-a[1])/length*width/2; ny=(b[0]-a[0])/length*width/2
                        quad=[(a[0]-nx,a[1]-ny),(b[0]-nx,b[1]-ny),(b[0]+nx,b[1]+ny),(a[0]+nx,a[1]+ny)]
                        yield from triangulate([quad])
                    # Round joins fill corners without a disconnected gap.
                    for p in line[1:-1]:
                        job.check()
                        ring=[(p[0]+width/2*math.cos(i*math.tau/8),p[1]+width/2*math.sin(i*math.tau/8)) for i in range(8)]
                        yield from triangulate([ring])
                raw_faces=stream_faces()
            else:
                validate_rings(rings,outer_count,inside)
                raw_faces=triangulate(rings)
            prepared=[]; omitted=0
            for tri in raw_faces:
                clipped=clip_polygon(tri,data['size'][0]-.02,data['size'][1]-.02)
                if len(clipped)<3: continue
                for clipped_tri in triangulate([clipped]):
                    for face in split_triangle(clipped_tri,job):
                        if reserved(face): omitted+=1; continue
                        if len(prepared)>=remaining: raise ValueError('30,000 shallow-water face budget reached; use a smaller OSM area')
                        if signed_area(face)<0: face.reverse()
                        prepared.append({'texture':DIRTY_GROUND,'face':[list(p) for p in face],
                                         'category':'waterways','depth':0.5,'osmWater':id})
            data['scenery'].extend(prepared); remaining-=len(prepared)
            feature.update(status='prepared',preparedFaces=len(prepared),reservedFaces=omitted,depth=0.5)
            if omitted: warn('Shallow water near planned roads/rails is omitted within a conservative 20 m corridor. Network heights are unchanged until construction.')
        except (ValueError,OverflowError) as exc:
            feature['status']='needs-review'; feature['reason']=str(exc)
            warn(f'Water {id}: {exc}; no partial feature imported.')
    data['waterFeatures']=features

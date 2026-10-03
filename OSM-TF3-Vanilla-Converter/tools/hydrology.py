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
    if tags.get('waterway') in {'stream', 'river', 'ditch', 'drain', 'canal', 'riverbank'}:
        return 'shallow'
    if tags.get('natural') == 'water' or tags.get('water') in {'lake', 'reservoir'} or tags.get('landuse') == 'reservoir':
        return 'lake'
    return None


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


def prepare(data, ways, relations, positions, members_for, join_rings,
            triangulate, clip_polygon, signed_area, job, warn, fallback_width,inside):
    """Keep raw height tags separate from game heights; never change sea level."""
    features=[]; candidates=[]; covered=set()
    for id,(_,tags) in relations.items():
        category=kind(tags)
        if tags.get('type')!='multipolygon' or not category: continue
        try:
            used=set(); parts=members_for(id,used=used)
            outers=join_rings(parts['outer']); inners=join_rings(parts['inner'])
            if not outers: raise ValueError('No outer water ring')
            rings=[[positions[n] for n in ring] for ring in outers+inners]
            candidates.append(('relation:'+id,category,tags,rings,None,len(outers)))
            covered.update(used)
        except (ValueError,KeyError) as exc:
            warn(f'Water relation {id}: {exc}; no partial water geometry imported.')
    for id,(refs,tags) in ways.items():
        category=kind(tags)
        if not category or id in covered: continue
        try:
            # Missing nodes break the feature; they never create a shortcut.
            line=[positions[n] for n in refs]
            if len(line)<2: raise ValueError('Too few water nodes')
            closed=len(refs)>3 and refs[0]==refs[-1]
            area=category=='lake' or tags.get('natural')=='water' or tags.get('water') in {'pond','basin'} or tags.get('waterway')=='riverbank'
            if area and not closed: raise ValueError('Water area boundary is not closed')
            candidates.append(('way:'+id,category,tags,[line[:-1]] if closed else None,None if closed else line,1 if closed else 0))
        except (ValueError,KeyError) as exc:
            warn(f'Water way {id}: {exc}; feature skipped.')

    # Reserve planned network corridors without moving any terrain or nodes.
    # Conservative rectangle tests may omit extra water near a crossing.
    buckets={}; cell=64; margin=20
    for edge in data['edges']:
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
    for id,category,tags,rings,line,outer_count in candidates:
        job.check()
        feature={'osmId':id,'kind':category,'name':tags.get('name',''),
                 'tags':dict(tags),'rings':[[list(p) for p in ring] for ring in (rings or [])],
                 'centreline':[list(p) for p in (line or [])],
                 'outerRingCount':outer_count,
                 'height':{'raw':tags.get('ele'),'datum':'OSM-untransformed'},'status':'pending'}
        features.append(feature)
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

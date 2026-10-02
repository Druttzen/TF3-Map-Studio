"""Exact alignment with OSM converter bounds; no Lua is executed. GPL-3.0."""
import json, math, re, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
import osm_converter as osm
from job import Job

R=6378137.0

def mercator_bounds(bounds):
 a,b,c,d=bounds
 return R*math.radians(b),R*math.log(math.tan(math.pi/4+math.radians(a)/2)),R*math.radians(d),R*math.log(math.tan(math.pi/4+math.radians(c)/2))


def geographic(x,y,bounds,size):
 minx,miny,maxx,maxy=mercator_bounds(bounds)
 mx=minx+(x/size[0]+.5)*(maxx-minx); my=miny+(y/size[1]+.5)*(maxy-miny)
 return math.degrees(2*math.atan(math.exp(my/R))-math.pi/2),math.degrees(mx/R)


def read_report(path):
 p=Path(path)
 if p.stat().st_size>64*1024*1024:raise ValueError('Converter report is too large (maximum 64 MB).')
 value=json.loads(p.read_text(encoding='utf-8-sig'))
 if not isinstance(value,dict) or not isinstance(value.get('dataset'),str):raise ValueError('Select an OSM converter .report.json or import-report.json file.')
 bounds=value.get('bounds'); size=value.get('mapSize')
 if not isinstance(bounds,list) or not isinstance(size,list) or any(type(v) not in {float,int} for v in bounds+size):raise ValueError('Converter bounds and map size must be numbers.')
 osm.validate_bounds(bounds,size)
 if 'sourceSha256' in value and (not isinstance(value['sourceSha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['sourceSha256'])):raise ValueError('Invalid OSM checksum in converter report.')
 if 'luaSha256' in value and (not isinstance(value['luaSha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['luaSha256'])):raise ValueError('Invalid Lua checksum in converter report.')
 if value.get('alignment') and value['alignment']!={'projection':'EPSG:3857 scaled to map size','origin':'centre','north':'positiveY','pngRows':'north to south'}:
  raise ValueError('Unsupported converter alignment. Use a compatible report.')
 options=osm.normalize_options(value.get('settings'))
 return {**value,'settings':options,'reportPath':str(p.resolve())}


def load_context(report_path,osm_path,job=None,lua_path=None,lua_sha=None):
 job=job or Job(); report=read_report(report_path)
 nodes,ways,relations,file_bounds=osm.read_osm(osm_path,job)
 warnings=[]
 if report.get('sourceSha256'):
  if report['sourceSha256']!=job.source_sha256:raise ValueError('The OSM file does not match the converter report checksum. Select the original file or run the converter again.')
 else:
  warnings.append('This older converter report has no OSM checksum; bounds match, but file identity cannot be proved. The updated converter includes checksums.')
 if report.get('input') and report['input']!=Path(osm_path).name and not report.get('sourceSha256'):
  raise ValueError('The OSM filename differs from the converter report. Choose the original OSM or regenerate its report.')
 bounds=report['bounds'];size=report['mapSize'];features=report['settings']['features']
 positions={}
 for i,(id,node) in enumerate(nodes.items()):
  if i%256==0:job.check()
  positions[id]=osm.project(node[0],node[1],bounds,size)
 lines=[]; lakes=[]; covered=set()
 for i,(id,(refs,tags)) in enumerate(ways.items()):
  if i%128==0:job.check()
  road=tags.get('highway') in osm.ROADS and tags.get('area')!='yes'
  rail=tags.get('railway') in osm.RAILS and not road
  river=tags.get('waterway') in {'river','stream','canal','ditch','drain'}
  if road and (not features['roads'] or tags.get('highway') in osm.FOOTWAYS and not features['footpaths']):road=False
  if rail and (not features['railways'] or tags.get('railway')=='disused' and not features['disused_tracks']):rail=False
  bridge=tags.get('bridge') not in {None,'no','false','0'};tunnel=tags.get('tunnel') not in {None,'no','false','0'}
  if (bridge and not features['bridges']) or (tunnel and not features['tunnels']):road=rail=False
  if road or rail or river:
   chains=[];chain=[]
   for a,b in zip(refs,refs[1:]):
    if a not in positions or b not in positions:
     if chain:chains.append(chain);chain=[]
     continue
    segment=osm.clip_segment(positions[a],positions[b],*size)
    if not segment or math.dist(segment[0],segment[1])<1e-8:
     if chain:chains.append(chain);chain=[]
     continue
    p,q=segment[:2]
    if chain and math.dist(chain[-1],p)>1e-5:chains.append(chain);chain=[]
    if not chain:chain=[p]
    chain.append(q)
   if chain:chains.append(chain)
   for chain in chains:lines.append({'way':id,'kind':'river' if river else 'road' if road else 'rail','points':chain,'bridge':bridge,'tunnel':tunnel})
 def is_water(tags):return tags.get('natural')=='water' or tags.get('landuse') in {'reservoir','basin'} or tags.get('waterway')=='riverbank'
 def relation_parts(id,active=None,invert=False,used=None):
  active=set(active or ());used=used if used is not None else set()
  if id in active:raise ValueError('Cyclic water multipolygon.')
  if id not in relations:raise ValueError('Missing water relation.')
  active.add(id);result={'outer':[],'inner':[]}
  for m in relations[id][0]:
   job.check();role=m.get('role') or 'outer'
   if role not in result:continue
   role=('inner' if role=='outer' else 'outer') if invert else role
   if m['type']=='way':
    if m['ref'] not in ways:raise ValueError('Missing water boundary way.')
    result[role].append(ways[m['ref']][0]);used.add(m['ref'])
   elif m['type']=='relation':
    nested=relation_parts(m['ref'],active,role=='inner',used)
    for k in result:result[k].extend(nested[k])
  return result
 for id,(members,tags) in relations.items():
  if tags.get('type')!='multipolygon' or not is_water(tags):continue
  try:
   used=set();parts=relation_parts(id,used=used)
   outer=osm.join_rings(parts['outer']);inner=osm.join_rings(parts['inner'])
   if not outer:raise ValueError('No outer water boundary.')
   lake={'outer':[[positions[r] for r in ring] for ring in outer],'inner':[[positions[r] for r in ring] for ring in inner]}
   lakes.append(lake);covered.update(used)
  except (ValueError,KeyError) as exc:warnings.append(f'Water relation {id} skipped: {exc}')
 for id,(refs,tags) in ways.items():
  job.check()
  if id not in covered and is_water(tags) and len(refs)>=4 and refs[0]==refs[-1]:
   try:lakes.append({'outer':[[positions[r] for r in refs[:-1]]],'inner':[]})
   except KeyError:warnings.append(f'Water way {id} has missing nodes; skipped.')
 from lua_map import read_map,find_map
 from biomes import land_areas
 biome_areas=land_areas(ways,relations,positions,osm,job,warnings)
 lua_path=lua_path or find_map(report_path,report);converted=None
 if lua_path:
  converted_lines,converted=read_map(lua_path,report,job,lua_sha)
  lines=[line for line in lines if line['kind']=='river']+converted_lines
  if not converted['reportChecksumVerified']:warnings.append('Older converter report: Lua dataset, bounds, size, settings and feature counts match, but the report has no Lua checksum. Converter 0.5 adds a byte-for-byte checksum.')
 elif lua_sha:raise ValueError('The saved converted Lua file is missing.')
 else:warnings.append('No converted Lua dataset selected. Road/rail guides fall back to original OSM; select the converted .lua to follow the exported map exactly.')
 return {'report':report,'bounds':bounds,'size':size,'lines':lines,'lakes':lakes,'biomeAreas':biome_areas,'warnings':warnings,'osmPath':str(Path(osm_path).resolve()),'osmSha256':job.source_sha256,'convertedLua':converted}


def alignment_summary(report,options):
 from height_settings import dimensions
 bounds=report['bounds'];size=report['mapSize'];nx,ny=dimensions(size,options);minx,miny,maxx,maxy=mercator_bounds(bounds)
 centre_lat,centre_lon=geographic(0,0,bounds,size);factor=math.cos(math.radians(centre_lat))
 return {'geographicCrs':'EPSG:4326','projection':'EPSG:3857 scaled to converter map size',
         'south':bounds[0],'west':bounds[1],'north':bounds[2],'east':bounds[3],
         'gameWidthMetres':size[0],'gameHeightMetres':size[1],'pixels':[nx,ny],
         'gridSpacingGameMetres':[size[0]/(nx-1),size[1]/(ny-1)],
         'centreLatitude':centre_lat,'centreLongitude':centre_lon,
         'approximateGroundExtentMetresAtCentre':[(maxx-minx)*factor,(maxy-miny)*factor],
         'gameMetresPerMercatorMetre':[size[0]/(maxx-minx),size[1]/(maxy-miny)],
         'cornerVertices':{'northWest':[-size[0]/2,size[1]/2],'northEast':[size[0]/2,size[1]/2],
                           'southWest':[-size[0]/2,-size[1]/2],'southEast':[size[0]/2,-size[1]/2]},
         'northUp':True,'mapSizeAuthority':'OSM converter report'}

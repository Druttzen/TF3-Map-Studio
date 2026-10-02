"""Aligned vanilla TF3 biome maps. GPL-3.0.

Vanilla climate dataMaps define biome IDs 0..4. Native TF3 biome PNGs inspected
on this computer use 8-bit grayscale codes 0, 63, 127, 191, 255, not RGB colors.
Palette colors below are the editor colors from the four vanilla .clima files.
"""
import hashlib
import math
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from rasterio import Affine
from rasterio.features import rasterize
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from job import Job

CLIMATES={'Temperate':'temperate','Dry':'dry','Tropical':'tropical','Subarctic':'subarctic'}
BIOME_CHOICES=('Biome 0 · blue','Biome 1 · dark green','Biome 2 · light green','Biome 3 · olive','Biome 4 · white')
CODES=np.array([0,63,127,191,255],dtype=np.uint8)
COLORS=np.array([[0,161,230],[54,128,33],[161,255,140],[128,128,71],[255,255,255]],dtype=np.uint8)
MODES=('Height, slope and OSM','Height and slope','Single biome','Import biome PNG')

def biome_id(label):
 if label not in BIOME_CHOICES:raise ValueError('Choose a vanilla biome from the list.')
 return BIOME_CHOICES.index(label)

def land_kind(tags):
 natural=tags.get('natural');land=tags.get('landuse')
 if natural in {'wood'} or land=='forest':return 'forest'
 if natural in {'scrub','heath'}:return 'shrubs'
 if natural in {'grassland'} or land in {'grass','meadow','farmland','orchard','vineyard','recreation_ground'}:return 'grass'
 if natural=='wetland':return 'wetland'
 if natural in {'sand','beach'}:return 'sand'
 if natural in {'bare_rock','scree','shingle','glacier'}:return 'rock'
 return None

def land_areas(ways,relations,positions,osm,job,warnings):
 areas=[];covered=set()
 def members(id,active=None,invert=False,used=None):
  active=set(active or ());used=used if used is not None else set()
  if id in active:raise ValueError('Cyclic land-cover multipolygon.')
  if id not in relations:raise ValueError('Missing land-cover relation.')
  active.add(id);parts={'outer':[],'inner':[]}
  for member in relations[id][0]:
   job.check();role=member.get('role') or 'outer'
   if role not in parts:continue
   role=('inner' if role=='outer' else 'outer') if invert else role
   if member['type']=='way':
    if member['ref'] not in ways:raise ValueError('Missing land-cover boundary.')
    parts[role].append(ways[member['ref']][0]);used.add(member['ref'])
   elif member['type']=='relation':
    nested=members(member['ref'],active,role=='inner',used)
    for key in parts:parts[key].extend(nested[key])
  return parts
 for id,(_,tags) in relations.items():
  kind=land_kind(tags)
  if tags.get('type')!='multipolygon' or not kind:continue
  try:
   used=set();parts=members(id,used=used);outer=osm.join_rings(parts['outer']);inner=osm.join_rings(parts['inner'])
   if not outer:raise ValueError('No outer land-cover ring.')
   areas.append({'kind':kind,'outer':[[positions[r] for r in ring] for ring in outer],
                 'inner':[[positions[r] for r in ring] for ring in inner],'osmId':id});covered.update(used)
  except (ValueError,KeyError) as exc:warnings.append(f'Biome relation {id} skipped: {exc}')
 for id,(refs,tags) in ways.items():
  job.check();kind=land_kind(tags)
  if kind and id not in covered and len(refs)>=4 and refs[0]==refs[-1]:
   try:areas.append({'kind':kind,'outer':[[positions[r] for r in refs[:-1]]],'inner':[],'osmId':id})
   except KeyError:warnings.append(f'Biome way {id} has missing nodes; skipped.')
 return areas

def validate_paint(stroke,size):
 if not isinstance(stroke,dict) or set(stroke)!={'x','y','radius','biome'}:raise ValueError('Invalid biome brush record.')
 for key,(lo,hi) in {'x':(-size[0]/2,size[0]/2),'y':(-size[1]/2,size[1]/2),'radius':(.1,5000)}.items():
  v=stroke[key]
  if type(v) not in {int,float} or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid biome brush '+key+'.')
 if type(stroke['biome']) is not int or not 0<=stroke['biome']<=4:raise ValueError('Biome brush ID must be 0–4.')
 return dict(stroke)

def paint(grid,size,stroke):
 s=validate_paint(stroke,size);ny,nx=grid.shape;dx=size[0]/(nx-1);dy=size[1]/(ny-1);x,y,r=s['x'],s['y'],s['radius']
 c0=max(0,math.floor((x-r)/dx+(nx-1)/2));c1=min(nx,math.ceil((x+r)/dx+(nx-1)/2)+1)
 r0=max(0,math.floor((size[1]/2-y-r)/dy));r1=min(ny,math.ceil((size[1]/2-y+r)/dy)+1)
 if r0>=r1 or c0>=c1:return None
 xx=np.arange(c0,c1)*dx-size[0]/2;yy=size[1]/2-np.arange(r0,r1)*dy
 mask=(yy[:,None]-y)**2+(xx[None,:]-x)**2<=r*r
 patch=grid[r0:r1,c0:c1];old=patch.copy();patch[mask]=s['biome']
 return r0,r1,c0,c1,old

def generate(terrain,context,options,strokes=None,job=None):
 job=job or Job();size=context['size'];ny,nx=terrain.shape
 if not isinstance(strokes or [],list) or len(strokes or [])>10000:raise ValueError('At most 10,000 biome brush stamps are supported.')
 strokes=[validate_paint(s,size) for s in (strokes or [])]
 mode=options['biome_mode'];source=None
 if mode=='Import biome PNG':
  path=Path(options['biome_source'])
  if not path.is_file() or path.suffix.lower()!='.png':raise ValueError('Choose an existing biome PNG in the Biomes tab.')
  job.check()
  with Image.open(path) as image:
   if image.mode!='L':raise ValueError('Biome input must be an 8-bit grayscale PNG with TF3 codes 0, 63, 127, 191, 255.')
   if image.size!=(nx,ny):raise ValueError(f'Biome PNG must be {nx} × {ny} pixels to match this heightmap. Select its original grid size.')
   encoded=np.asarray(image)
   if not np.isin(encoded,CODES).all():raise ValueError('Biome PNG contains values outside TF3 codes 0, 63, 127, 191, 255.')
   grid=np.searchsorted(CODES,encoded).astype(np.uint8)
  digest=hashlib.sha256()
  with path.open('rb') as file:
   while chunk:=file.read(1024*1024):job.check();digest.update(chunk)
  source={'file':str(path.resolve()),'sha256':digest.hexdigest()}
 else:
  grid=np.full(terrain.shape,biome_id(options['biome_base']),dtype=np.uint8)
  if mode!='Single biome':
   dx=size[0]/(nx-1);dy=size[1]/(ny-1)
   for row in range(0,ny,128):
    job.check();end=min(ny,row+128);lo=max(0,row-1);hi=min(ny,end+1)
    z=terrain[row:end];gy,gx=np.gradient(terrain[lo:hi],dy,dx)
    slope=np.degrees(np.arctan(np.hypot(gy[row-lo:end-lo],gx[row-lo:end-lo])))
    patch=grid[row:end];patch[z>=options['biome_highland_m']]=biome_id(options['biome_highland'])
    patch[(z>=options['biome_alpine_m'])|(slope>=options['biome_rock_slope'])]=biome_id(options['biome_rock'])
   if mode=='Height, slope and OSM':
    mapping={'forest':'biome_forest','shrubs':'biome_shrubs','grass':'biome_grass','wetland':'biome_wetland','sand':'biome_sand','rock':'biome_rock'}
    transform=Affine(dx,0,-size[0]/2-dx/2,0,-dy,size[1]/2+dy/2)
    # Burn all polygons into one temporary byte grid; holes retain the terrain
    # classification and later complete polygons take precedence over earlier ones.
    shapes=[]
    from alignment import osm
    for area in context.get('biomeAreas',[]):
     job.check()
     for outer in area['outer']:
      holes=[h for h in area['inner'] if osm.inside(h[0],outer)]
      shapes.append(({'type':'Polygon','coordinates':[outer+[outer[0]]]+[h+[h[0]] for h in holes]},biome_id(options[mapping[area['kind']]])+1))
    if shapes:
     cover=rasterize(shapes,out_shape=grid.shape,transform=transform,fill=0,dtype='uint8')
     for row in range(0,ny,128):
      job.check();patch=grid[row:row+128];c=cover[row:row+128];mask=c!=0;patch[mask]=c[mask]-1
     del cover
  if options['biome_water']:
   for row in range(0,ny,128):job.check();grid[row:row+128][terrain[row:row+128]<options['water_level']]=0
 # Paint is authoritative, including imported maps. TF3 may rederive underwater
 # biome 0 when applying its vanilla import generator.
 for s in strokes:job.check();paint(grid,size,s)
 job.check();return grid,source

def ensure(result,job=None):
 if not result['options']['biomes']:return None
 if result.get('biomes') is None:
  result['biomes'],result['biomeSource']=generate(result['terrain'],result['context'],result['options'],result.get('biomeStrokes'),job)
 return result['biomes']

def summary(result):
 grid=ensure(result)
 if grid is None:return None
 counts=np.bincount(grid.ravel(),minlength=5);n=grid.size
 climate=result['options']['biome_climate'];key=CLIMATES[climate]
 return {'climate':climate,'climateResource':f'::/climates/{key}/{key}.clima','importGenerator':f'{key}_import.gen',
         'mode':result['options']['biome_mode'],'encoding':'8-bit grayscale: biome ID 0–4 maps to 0,63,127,191,255',
         'palette':[{'id':i,'label':BIOME_CHOICES[i],'pngCode':int(CODES[i]),'previewRgb':COLORS[i].tolist(),'vertices':int(counts[i]),'percent':float(counts[i]*100/n)} for i in range(5)],
         'pixels':[grid.shape[1],grid.shape[0]],'northUp':True,'bounds':result['context']['bounds'],'mapSize':result['context']['size'],
         'paintStamps':len(result.get('biomeStrokes',[])),'source':result.get('biomeSource'),'nativeGameImportVerified':False}

def preview(result,max_size=(1000,800),overlay=True):
 grid=ensure(result)
 if grid is None:raise ValueError('Enable biome export and Build terrain before viewing biomes.')
 ny,nx=grid.shape;size=result['context']['size'];scale=min(max_size[0]/size[0],max_size[1]/size[1]);w=max(2,round(size[0]*scale));h=max(2,round(size[1]*scale))
 labels=grid[np.ix_(np.linspace(0,ny-1,h).astype(int),np.linspace(0,nx-1,w).astype(int))]
 image=Image.fromarray(COLORS[labels])
 if overlay:
  draw=ImageDraw.Draw(image)
  for line in result['context']['lines'][:5000]:
   points=[((p[0]/size[0]+.5)*(w-1),(.5-p[1]/size[1])*(h-1)) for p in line['points']]
   draw.line(points,fill={'road':'#0e5965','rail':'#f1af49','river':'#51b0dc'}[line['kind']],width=2)
 return image

"""Measured terrain preparation, optional OSM refinements and interactive brushes. GPL-3.0."""
from datetime import datetime, timezone
import hashlib, json, math, os, shutil, tempfile, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter, gaussian_filter1d, distance_transform_edt, map_coordinates
import rasterio
from rasterio import Affine
from rasterio.features import rasterize
from alignment import load_context, geographic, osm, alignment_summary
from elevation import download_tiles, sample_sources, PUBLIC_DOC, PUBLIC_LICENSE
from height_settings import normalize, dimensions, validate_stroke
from providers import acquire
from job import Job, Cancelled
import biomes


def game_transform(size,shape):
 ny,nx=shape;dx=size[0]/(nx-1);dy=size[1]/(ny-1)
 return Affine(dx,0,-size[0]/2-dx/2,0,-dy,size[1]/2+dy/2)


def fill_gaps(terrain,size,options,job):
 missing=~np.isfinite(terrain);count=int(missing.sum())
 if not count:return {'missingSamples':0,'filledSamples':0,'maximumFillDistanceMetres':0}
 if count==terrain.size:raise ValueError('No elevation data covers the converter bounds. Choose a DEM covering the whole area.')
 if options['missing_data']=='Stop at gaps':raise ValueError(f'Elevation coverage has {count:,} missing samples ({100*count/terrain.size:.2f}%). Add missing tiles or enable limited gap filling.')
 job.update(65,'Checking elevation gaps')
 ny,nx=terrain.shape;dy=size[1]/(ny-1);dx=size[0]/(nx-1)
 distances,indices=distance_transform_edt(missing,sampling=(dy,dx),return_indices=True)
 maximum=float(distances[missing].max());job.check()
 if maximum>options['max_gap_m']:raise ValueError(f'The largest elevation gap is {maximum:.1f} game metres from valid data; the allowed limit is {options["max_gap_m"]:.1f}. Add elevation coverage.')
 terrain[missing]=terrain[tuple(indices[:,missing])]
 return {'missingSamples':count,'filledSamples':count,'maximumFillDistanceMetres':maximum}


def water_mask(context,shape,job=None):
 job=job or Job();polygons=[]
 for lake in context['lakes']:
  for outer in lake['outer']:
   job.check();holes=[hole for hole in lake['inner'] if osm.inside(hole[0],outer)]
   polygons.append(({'type':'Polygon','coordinates':[outer+[outer[0]]]+[hole+[hole[0]] for hole in holes]},1))
 if not polygons:return np.zeros(shape,dtype=bool)
 return rasterize(polygons,out_shape=shape,transform=game_transform(context['size'],shape),fill=0,dtype='uint8').astype(bool)


def densify(points,step):
 coordinates=[points[0]]
 for a,b in zip(points,points[1:]):
  length=math.dist(a,b);n=max(1,math.ceil(length/step))
  coordinates.extend((a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n) for k in range(1,n+1))
 return np.asarray(coordinates,dtype=np.float64)


def sample_world(terrain,points,size):
 ny,nx=terrain.shape;p=np.asarray(points)
 cols=(p[:,0]/size[0]+.5)*(nx-1);rows=(.5-p[:,1]/size[1])*(ny-1)
 return map_coordinates(terrain,[rows,cols],order=1,mode='nearest',prefilter=False)


def limit_grade(heights,points,percent):
 result=heights.copy()
 if percent<=0:return result
 steps=np.linalg.norm(np.diff(points,axis=0),axis=1)*percent/100
 for i,limit in enumerate(steps,1):result[i]=np.clip(result[i],result[i-1]-limit,result[i-1]+limit)
 for i in range(len(result)-2,-1,-1):result[i]=np.clip(result[i],result[i+1]-steps[i],result[i+1]+steps[i])
 return result


def corridor(terrain,original,line,size,width,blend,smoothing,grade,job,river_depth=None):
 ny,nx=terrain.shape;dx=size[0]/(nx-1);dy=size[1]/(ny-1)
 step=max(.1,min(dx,dy,width/2,10));points=densify(line['points'],step)
 heights=sample_world(original,points,size)
 if smoothing>0:heights=gaussian_filter1d(heights,smoothing/step,mode='nearest')
 heights=limit_grade(heights,points,grade)
 if river_depth is not None:heights-=river_depth
 radius=width/2+blend
 for i,(a,b) in enumerate(zip(points,points[1:])):
  if i%32==0:job.check()
  c0=max(0,math.floor((min(a[0],b[0])-radius)/dx+(nx-1)/2));c1=min(nx,math.ceil((max(a[0],b[0])+radius)/dx+(nx-1)/2)+1)
  r0=max(0,math.floor((size[1]/2-max(a[1],b[1])-radius)/dy));r1=min(ny,math.ceil((size[1]/2-min(a[1],b[1])+radius)/dy)+1)
  if r1<=r0 or c1<=c0:continue
  x=np.arange(c0,c1)*dx-size[0]/2;y=size[1]/2-np.arange(r0,r1)*dy
  xx,yy=np.meshgrid(x,y);vx,vy=b-a;den=vx*vx+vy*vy
  if den<1e-12:continue
  t=np.clip(((xx-a[0])*vx+(yy-a[1])*vy)/den,0,1)
  distance=np.hypot(xx-a[0]-t*vx,yy-a[1]-t*vy)
  weight=np.clip((radius-distance)/blend,0,1) if blend else (distance<=width/2).astype(float)
  weight=weight*weight*(3-2*weight)
  target=heights[i]+t*(heights[i+1]-heights[i]);patch=terrain[r0:r1,c0:c1]
  if river_depth is not None:target=np.minimum(patch,target)
  patch+=weight*(target-patch)


def apply_stroke(terrain,size,stroke):
 stroke=validate_stroke(stroke,size);ny,nx=terrain.shape;dx=size[0]/(nx-1);dy=size[1]/(ny-1)
 x,y,radius=stroke['x'],stroke['y'],stroke['radius']
 c0=max(0,math.floor((x-radius)/dx+(nx-1)/2));c1=min(nx,math.ceil((x+radius)/dx+(nx-1)/2)+1)
 r0=max(0,math.floor((size[1]/2-y-radius)/dy));r1=min(ny,math.ceil((size[1]/2-y+radius)/dy)+1)
 if r0>=r1 or c0>=c1:return None
 xx,yy=np.meshgrid(np.arange(c0,c1)*dx-size[0]/2,size[1]/2-np.arange(r0,r1)*dy)
 weight=np.clip(1-np.hypot(xx-x,yy-y)/radius,0,1);weight=weight*weight*(3-2*weight)
 patch=terrain[r0:r1,c0:c1];previous=patch.copy();strength=stroke['strength']
 if stroke['tool'] in {'Raise','Lower'}:patch+=weight*strength*(1 if stroke['tool']=='Raise' else -1)
 elif stroke['tool']=='Flatten':patch+=weight*min(1,strength)*(stroke['target']-patch)
 else:
  # Include a halo, so smoothing does not create a rectangular patch boundary.
  sigma=max(.5,radius/min(dx,dy)/6);halo=math.ceil(sigma*4)
  hr0=max(0,r0-halo);hr1=min(ny,r1+halo);hc0=max(0,c0-halo);hc1=min(nx,c1+halo)
  smooth=gaussian_filter(terrain[hr0:hr1,hc0:hc1],sigma,mode='nearest')[r0-hr0:r1-hr0,c0-hc0:c1-hc0]
  patch+=weight*min(1,strength)*(smooth-patch)
 return (r0,r1,c0,c1,previous)


def prepare(report_path,osm_path,source_files,options=None,strokes=None,cache=None,progress=None,cancel=None,api_key=None,lua_path=None,lua_sha=None,biome_strokes=None):
 options=normalize(options);job=Job(progress,cancel)
 context=load_context(report_path,osm_path,job,lua_path,lua_sha);size=context['size'];nx,ny=dimensions(size,options)
 if strokes is not None and (not isinstance(strokes,list) or len(strokes)>10000):raise ValueError('At most 10,000 brush stamps are supported.')
 strokes=[validate_stroke(v,size) for v in (strokes or [])]
 paths=[Path(p) for p in source_files];public=options['source_mode'].startswith('Download');provider_plan=None;provider_credits=[]
 if public:
  cache=cache or Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'Druttzen/TF3-Heightmap/cache'
  paths,provider_plan,provider_credits=acquire(context['bounds'],options,cache,job,api_key)
 else:job.update(35,'Opening local elevation files')
 if any(p.suffix.lower() in {'.las','.laz'} for p in paths):
  from lidar import prepare_sources
  cache=cache or Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'Druttzen/TF3-Heightmap/cache'
  paths=prepare_sources(paths,context['bounds'],(ny,nx),options,Path(cache)/'lidar',job)
 terrain,geo_transform,source_meta=sample_sources(paths,context['bounds'],(ny,nx),options,job)
 coverage=fill_gaps(terrain,size,options,job);base_min=float(terrain.min());base_max=float(terrain.max())
 terrain*=options['vertical_scale'];terrain+=options['height_offset']
 dx=size[0]/(nx-1);dy=size[1]/(ny-1)
 if options['smoothing_m']:
  job.update(67,'Smoothing measured terrain');terrain=gaussian_filter(terrain,(options['smoothing_m']/dy,options['smoothing_m']/dx),mode='nearest');job.check()
 baseline=terrain.copy();job.update(70,'Refining water areas')
 if options['lakes']:
  mask=water_mask(context,terrain.shape,job)
  if mask.any():
   weight=np.minimum(1,distance_transform_edt(mask,sampling=(dy,dx))/options['lake_feather']) if options['lake_feather'] else mask.astype(float)
   terrain+=weight*(np.minimum(terrain,options['water_level']-options['lake_depth'])-terrain)
   job.check()
 chosen=[line for line in context['lines'] if (options['rivers'] if line['kind']=='river' else options['roads'] if line['kind']=='road' else options['railways']) and not line['bridge'] and not line['tunnel']]
 for i,line in enumerate(chosen):
  job.update(72+15*i/max(1,len(chosen)),'Refining OSM terrain',f'{line["kind"].capitalize()} way {line["way"]}; {i+1}/{len(chosen)}')
  key={'road':'road','rail':'rail','river':'river'}[line['kind']]
  corridor(terrain,baseline,line,size,options[key+'_width'],options.get(key+'_blend',options[key+'_width']/2),
           options[key+'_smoothing'],options.get(key+'_grade',0),job,options['river_depth'] if key=='river' else None)
 for i,stroke in enumerate(strokes or []):
  job.update(87+7*i/max(1,len(strokes)),'Applying saved terrain edits',f'{i+1}/{len(strokes)}');apply_stroke(terrain,size,stroke)
 warnings=list(context['warnings'])
 if public:warnings.append('Public terrain tiles have regional source-dependent resolution and accuracy. A finer grid does not add measured detail. Use a local surveyed/LiDAR DEM for finer source data.')
 if any(s['synthetic'] for s in source_meta):warnings.append('SYNTHETIC DEM: this source is a demonstration, not measured real-world terrain.')
 if nx%64!=1 or ny%64!=1:warnings.append('These pixel dimensions are not 64n+1. The converter map dimensions differ from the tiled TF3 native map grid; verify the target game map size before importing.')
 if options['grid'] in {'Fine grid (2 m)','Fine grid (1 m)','Custom pixels'}:warnings.append('TF3 map creation uses 4-metre terrain spacing. Finer exported grids can help editing, but the game may resample them.')
 if options['rivers']:warnings.append('River channels are terrain cuts following local elevation. TF3 has one water level; higher channels do not create flowing water.')
 if chosen:warnings.append('Road/rail terrain refinements alter the DEM for construction. Bridge and tunnel interiors are excluded; inspect junctions and grades in the game.')
 if options['roads'] or options['railways']:
  skipped=sum(1 for line in context['lines'] if line['kind'] in {'road','rail'} and (line['bridge'] or line['tunnel']))
  if skipped:warnings.append(f'{skipped} bridge/tunnel polylines were excluded from terrain corridor editing.')
 max_diff=float(np.max(np.abs(terrain-baseline)))
 job.check()
 if biome_strokes is not None and (not isinstance(biome_strokes,list) or len(biome_strokes)>10000):raise ValueError('At most 10,000 biome brush stamps are supported.')
 result={'terrain':terrain,'baseline':baseline,'context':context,'options':options,'strokes':[dict(s) for s in (strokes or [])],
         'biomeStrokes':[biomes.validate_paint(s,size) for s in (biome_strokes or [])],'biomes':None,'biomeSource':None,
         'alignment':alignment_summary(context['report'],options),'providerPlan':provider_plan,'providerCredits':provider_credits,
         'geoTransform':geo_transform,'sources':source_meta,'sourceFiles':[str(p.resolve()) for p in paths],
         'coverage':coverage,'sourceRange':[base_min,base_max],'maximumRefinementMetres':max_diff,'warnings':warnings,'public':public}
 if options['biomes']:
  job.update(94,'Building vanilla biome regions');biomes.ensure(result,job)
  result['warnings'].append('Biome regions are authored from height, slope, OSM land cover or a selected PNG. They are not measured ecological classifications. Choose the same vanilla climate in TF3; its import generator determines textures and vegetation.')
 job.update(95,'Terrain ready',f'{nx:,} × {ny:,} pixels',force=True);job.check()
 return result


def encoding_range(terrain,options):
 low=float(terrain.min());high=float(terrain.max())
 if options['range_mode'].startswith('Automatic'):
  lo=math.floor(low);hi=math.ceil(high)
  if lo==hi:hi=lo+1
 else:lo=options['range_min'];hi=options['range_max']
 clipped=int(np.count_nonzero((terrain<lo)|(terrain>hi)))
 if clipped and not options['clip_heights']:raise ValueError(f'{clipped:,} heights fall outside the manual range. Expand the range or explicitly enable clipping.')
 return float(lo),float(hi),clipped


def preview_image(result,max_size=(1000,800),overlay=True):
 terrain=result['terrain'];ny,nx=terrain.shape
 size=result['context']['size'];scale=min(max_size[0]/size[0],max_size[1]/size[1]);w=max(2,round(size[0]*scale));h=max(2,round(size[1]*scale))
 z=terrain[np.ix_(np.linspace(0,ny-1,h).astype(int),np.linspace(0,nx-1,w).astype(int))]
 low=float(terrain.min());high=float(terrain.max());t=np.clip((z-low)/max(1,high-low),0,1)
 stops=np.array([0,.2,.45,.7,1]);colors=np.array([[90,143,92],[130,169,94],[175,164,111],[165,140,123],[241,239,229]],dtype=float)
 rgb=np.stack([np.interp(t,stops,colors[:,i]) for i in range(3)],axis=-1)
 dy=result['context']['size'][1]/max(1,h-1);dx=result['context']['size'][0]/max(1,w-1)
 gy,gx=np.gradient(z,dy,dx);shade=np.clip((.6-.4*gx+.3*gy)/np.sqrt(1+gx*gx+gy*gy),.25,1)
 rgb*=shade[:,:,None]/.8;rgb[z<result['options']['water_level']]=[68,131,171]
 image=Image.fromarray(np.clip(rgb,0,255).astype(np.uint8),'RGB')
 if overlay:
  draw=ImageDraw.Draw(image);size=result['context']['size']
  for line in result['context']['lines'][:5000]:
   points=[((p[0]/size[0]+.5)*(w-1),(.5-p[1]/size[1])*(h-1)) for p in line['points']]
   draw.line(points,fill={'road':'#0e5965','rail':'#f1af49','river':'#51b0dc'}[line['kind']],width=2)
 return image


def project_dict(result,output=''):
 context=result['context']
 return {'format':'TF3-Heightmap-Studio','version':1,'converterReport':context['report']['reportPath'],'osmFile':context['osmPath'],
         'convertedLua':(context.get('convertedLua') or {}).get('file',''),'luaSha256':(context.get('convertedLua') or {}).get('sha256'),
         'converterDataset':context['report']['dataset'],'osmSha256':context['osmSha256'],'bounds':context['bounds'],'mapSize':context['size'],
         'elevationFiles':result['sourceFiles'] if not result['public'] else [],'options':result['options'],'brushStrokes':result['strokes'],
         'biomeStrokes':result.get('biomeStrokes',[]),'biomeSourceSha256':(result.get('biomeSource') or {}).get('sha256'),'output':output}


def load_project(path):
 path=Path(path)
 if path.stat().st_size>16*1024*1024:raise ValueError('Heightmap project is too large (maximum 16 MB).')
 data=json.loads(path.read_text(encoding='utf-8-sig'))
 if not isinstance(data,dict) or data.get('format')!='TF3-Heightmap-Studio' or data.get('version')!=1:raise ValueError('Choose a version 1 TF3 Heightmap Studio project.')
 data['options']=normalize(data.get('options'))
 for key in ['converterReport','osmFile','output','convertedLua']:
  if not isinstance(data.get(key,''),str):raise ValueError('Project paths must be text.')
 if not isinstance(data.get('elevationFiles'),list) or any(not isinstance(p,str) for p in data['elevationFiles']):raise ValueError('Project elevation files must be a list of paths.')
 bounds=data.get('bounds');size=data.get('mapSize')
 if not isinstance(bounds,list) or not isinstance(size,list) or any(type(v) not in {int,float} for v in bounds+size):raise ValueError('Project map dimensions and bounds must be numeric.')
 osm.validate_bounds(bounds,size);strokes=data.get('brushStrokes',[])
 if not isinstance(strokes,list) or len(strokes)>10000:raise ValueError('Project brush list must contain at most 10,000 strokes.')
 data['brushStrokes']=[validate_stroke(s,size) for s in strokes]
 strokes=data.get('biomeStrokes',[])
 if not isinstance(strokes,list) or len(strokes)>10000:raise ValueError('Project biome brush list must contain at most 10,000 strokes.')
 data['biomeStrokes']=[biomes.validate_paint(s,size) for s in strokes]
 if data['options']['biome_source']:
  data['options']['biome_source']=str((path.resolve().parent/Path(data['options']['biome_source'])).resolve())
 if data.get('biomeSourceSha256'):
  digest=data['biomeSourceSha256']
  if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('Invalid saved biome checksum.')
  biome_path=Path(data['options']['biome_source'])
  if not biome_path.is_file() or hashlib.sha256(biome_path.read_bytes()).hexdigest()!=digest:raise ValueError('Biome PNG checksum differs from the saved project.')
 for key in ['converterReport','osmFile','output','convertedLua']:
  if data.get(key):data[key]=str((path.resolve().parent/Path(data[key])).resolve())
 data['elevationFiles']=[str((path.resolve().parent/Path(p)).resolve()) for p in data['elevationFiles']]
 read_project_report(data)
 if data.get('luaSha256'):
  if not isinstance(data['luaSha256'],str) or len(data['luaSha256'])!=64 or any(c not in '0123456789abcdef' for c in data['luaSha256']):raise ValueError('Invalid saved Lua checksum.')
  if not data.get('convertedLua'):raise ValueError('The saved converted Lua path is missing.')
  digest=hashlib.sha256()
  with Path(data['convertedLua']).open('rb') as source:
   while chunk:=source.read(1024*1024):digest.update(chunk)
  if digest.hexdigest()!=data['luaSha256']:raise ValueError('Converted Lua checksum differs from the saved project.')
 return data


def read_project_report(data):
 from alignment import read_report
 report=read_report(data['converterReport'])
 if report['bounds']!=data['bounds'] or report['mapSize']!=data['mapSize'] or report['dataset']!=data.get('converterDataset'):
  raise ValueError('The converter report has changed since this project was saved. Restore its original report.')
 if data.get('osmSha256') and report.get('sourceSha256') and data['osmSha256']!=report['sourceSha256']:
  raise ValueError('Project and converter OSM checksums differ.')
 return report


def export(result,output,progress=None,cancel=None):
 output=Path(output).resolve();job=Job(progress,cancel)
 if output.suffix.lower()!='.png':raise ValueError('Heightmap output must end in .png.')
 context=result['context'];options=result['options'];terrain=result['terrain'];ny,nx=terrain.shape
 lo,hi,clipped=encoding_range(terrain,options);base=output.with_suffix('')
 targets={'png':output}
 suffixes={'dem':'.dem.tif','preview':'.preview.png','report':'.heightmap-report.json','project':'.heightmap-project.json','instructions':'.import.txt','attribution':'.attribution.txt'}
 targets.update({key:output.with_name(output.stem+suffix) for key,suffix in suffixes.items()})
 if options['biomes']:
  targets.update({key:output.with_name(output.stem+suffix) for key,suffix in {'biomes':'.biomes.png','biomePreview':'.biomes.preview.png','biomeGeoTiff':'.biomes.tif'}.items()})
 protected={Path(context['osmPath']).resolve(),Path(context['report']['reportPath']).resolve(),*[Path(p).resolve() for p in result['sourceFiles']]}
 if context.get('convertedLua'):protected.add(Path(context['convertedLua']['file']).resolve())
 if options['biome_source']:protected.add(Path(options['biome_source']).resolve())
 if any(target in protected for target in targets.values()):raise ValueError('Output files must not replace source elevation, OSM or converter-report files.')
 output.parent.mkdir(parents=True,exist_ok=True);staging=Path(tempfile.mkdtemp(prefix='.tf3-heightmap-export-',dir=output.parent)).resolve()
 replaced=[];backups={};retain_staging=False
 try:
  job.update(0,'Writing 16-bit heightmap')
  encoded=np.empty(terrain.shape,dtype=np.uint16)
  for row in range(0,ny,128):
   job.update(5+30*row/ny,'Encoding heights',f'Rows {row+1}/{ny}')
   encoded[row:row+128]=np.rint(np.clip((terrain[row:row+128]-lo)/(hi-lo),0,1)*65535).astype(np.uint16)
  Image.fromarray(encoded).save(staging/targets['png'].name,format='PNG');del encoded
  job.update(40,'Writing georeferenced elevation')
  with rasterio.open(staging/targets['dem'].name,'w',driver='GTiff',width=nx,height=ny,count=1,dtype='float64',crs='EPSG:3857',transform=result['geoTransform'],compress='deflate',predictor=3,tiled=True) as dst:
   for row in range(0,ny,128):
    job.update(40+25*row/ny,'Writing georeferenced elevation',f'Rows {row+1}/{ny}')
    dst.write(terrain[row:row+128],1,window=rasterio.windows.Window(0,row,nx,min(128,ny-row)))
   dst.set_band_unit(1,'m');dst.update_tags(VERTICAL_DATUM=options['vertical_datum'],OSM_SHA256=context['osmSha256'],CONVERTER_DATASET=context['report']['dataset'])
  job.update(68,'Writing preview and import settings');preview_image(result).save(staging/targets['preview'].name)
  biome_report=None
  if options['biomes']:
   job.update(70,'Writing vanilla biome maps');grid=biomes.ensure(result,job);biome_report=biomes.summary(result)
   Image.fromarray(biomes.CODES[grid]).save(staging/targets['biomes'].name,format='PNG');job.check()
   biomes.preview(result,overlay=False).save(staging/targets['biomePreview'].name)
   with rasterio.open(staging/targets['biomeGeoTiff'].name,'w',driver='GTiff',width=nx,height=ny,count=1,dtype='uint8',crs='EPSG:3857',transform=result['geoTransform'],compress='deflate',tiled=True) as dst:
    for row in range(0,ny,128):job.check();dst.write(grid[row:row+128],1,window=rasterio.windows.Window(0,row,nx,min(128,ny-row)))
    dst.update_tags(BIOME_IDS='0,1,2,3,4',TF3_CLIMATE=options['biome_climate'],CONVERTER_DATASET=context['report']['dataset'])
  report={'format':'TF3-Heightmap-Studio-report','version':1,'createdUtc':datetime.now(timezone.utc).isoformat(),
          'converterDataset':context['report']['dataset'],'osmSha256':context['osmSha256'],'bounds':context['bounds'],'mapSize':context['size'],
          'convertedLua':context.get('convertedLua'),'biomes':biome_report,'roadRailGeometrySource':'converted Lua' if context.get('convertedLua') else 'original OSM fallback',
          'coordinateMatch':result.get('alignment'),'downloadPlan':result.get('providerPlan'),'providerCredits':result.get('providerCredits',[]),
          'pixels':[nx,ny],'northUp':True,'alignment':'Same scaled Web Mercator rectangle as OSM converter; corner vertices at exact map bounds',
          'gridSpacingGameMetres':[context['size'][0]/(nx-1),context['size'][1]/(ny-1)],'sources':result['sources'],
          'sourceElevationRangeMetres':result['sourceRange'],'finalElevationRangeMetres':[float(terrain.min()),float(terrain.max())],
          'pngBitDepth':16,'pngColorType':'grayscale','importMinimumMetres':lo,'importMaximumMetres':hi,'waterLevelMetres':options['water_level'],
          'pngEncodingStepMetres':(hi-lo)/65535,'nativeMapCreationSpacingMetres':4,'nativeMapCreationHeightStepMetres':.05,
          'clippedPngSamples':clipped,'coverage':result['coverage'],'brushStrokes':len(result['strokes']),'settings':options,
          'maximumChangeFromScaledSmoothedDemMetres':float(np.max(np.abs(terrain-result['baseline']))),
          'files':{k:str(p) for k,p in targets.items()},'warnings':result['warnings'],'nativeTF3ImportVerified':False}
  for key,value in [('report',report),('project',project_dict(result,str(output)))]:
   (staging/targets[key].name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
  instructions=f'''TF3 HEIGHTMAP IMPORT\n\nPNG: {output.name}\nPixels: {nx} x {ny} (16-bit grayscale)\nGame map: {context['size'][0]:g} x {context['size'][1]:g} metres\nMinimum height: {lo:g} metres\nMaximum height: {hi:g} metres\nWater level: {options['water_level']:g} metres\n\n1. Copy the PNG into TF3 userdata/<Steam user>/3493540/local/heightmaps.\n2. In the map editor, use the same map dimensions as the OSM converter.\n3. Import Heightmap: select this PNG and enter the exact minimum, maximum\n   and water level above. Verify north/south orientation with the preview.\n4. Review terrain, then import the matching OSM Lua dataset on this map.\n\nThe float64 GeoTIFF preserves elevations before PNG range clipping.\nAn exported heightmap does not create a game save or automatically install.\nNative TF3 import still requires an in-game verification session.\n'''
  if clipped:instructions+=f'\nManual-range clipping affected {clipped:,} PNG pixels.\n'
  if biome_report:
   instructions+=f'''\nVANILLA BIOMES\nCreate the map with the {options['biome_climate']} climate.\nBiome PNG: {targets['biomes'].name} ({nx} x {ny}, 8-bit grayscale)\nCodes: Biome 0=0, Biome 1=63, Biome 2=127, Biome 3=191, Biome 4=255.\n1. Copy the biome PNG to TF3 userdata/<Steam user>/3493540/local/biomes.\n2. After importing the heightmap, open the map editor's Biomes tab.\n3. Choose the matching {options['biome_climate']} (Import) generator and biome PNG.\n4. Inspect the game preview, then Apply. The vanilla generator supplies\n   climate-specific terrain materials and vegetation; no extra mods needed.\nLeave additional layer selectors empty; no extra terrain-shape layers are exported.\nBiome IDs are regions within one climate; their colors in the preview are\neditor labels, not final terrain textures. Water is determined by game heights.\nThe .biomes.tif stores IDs 0-4 for GIS, not native PNG grayscale codes.\nNative biome import remains to be verified in the game.\n'''
  (staging/targets['instructions'].name).write_text(instructions,encoding='utf-8')
  attribution='OSM geometry: © OpenStreetMap contributors, ODbL. https://www.openstreetmap.org/copyright\n'
  if result['public']:
   credits_list=result.get('providerCredits') or [{'provider':'Mapzen Terrain Tiles / Skadi','site':PUBLIC_DOC,'attribution':PUBLIC_LICENSE}]
   for item in credits_list:attribution+=item['provider']+' accessed '+str(datetime.now(timezone.utc).date())+'\n'+item.get('site','')+'\n'+item.get('attribution','')+'\n'
   if options['source_mode']=='Download public terrain (Mapzen)' or not result.get('providerCredits'):
    credits=(Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1])/'third-party/Mapzen-provider-attribution.md'
    if not credits.is_file():raise ValueError('The bundled public terrain provider attribution is missing; export stopped.')
    attribution+='\nFull provider attribution supplied by the terrain provider:\n'+credits.read_text(encoding='utf-8')+'\n'
  else:attribution+='Local elevation provider: '+(options['source_credit'] or 'User-supplied DEM; retain its provider licence and attribution.')+'\n'
  attribution+='Vertical datum: '+options['vertical_datum']+' (no automatic vertical datum conversion).\n'
  (staging/targets['attribution'].name).write_text(attribution,encoding='utf-8')
  job.update(95,'Checking exported heightmap')
  with Image.open(staging/targets['png'].name) as check:
   if check.size!=(nx,ny):raise ValueError('Exported PNG dimensions are incorrect.')
  # PNG IHDR is authoritative: 16-bit (byte 24), grayscale color type 0 (byte 25).
  with (staging/targets['png'].name).open('rb') as image_file:header=image_file.read(26)
  if header[24]!=16 or header[25]!=0:raise ValueError('The exported PNG is not 16-bit grayscale.')
  if biome_report:
   with Image.open(staging/targets['biomes'].name) as check:
    if check.mode!='L' or check.size!=(nx,ny):raise ValueError('The exported biome PNG format or dimensions are incorrect.')
  for key,target in targets.items():
   if target.exists():
    backup=staging/('backup-'+target.name);shutil.copyfile(target,backup);backups[key]=backup
  job.update(98,'Saving heightmap files',force=True);job.check();job.cancel=None
  try:
   for key,target in targets.items():os.replace(staging/target.name,target);replaced.append(key)
  except OSError as commit_error:
   errors=[]
   for key in reversed(replaced):
    try:
     if key in backups:os.replace(backups[key],targets[key])
     else:targets[key].unlink()
    except OSError as recovery_error:errors.append(str(recovery_error))
   if errors:
    retain_staging=True
    raise OSError(f'Export failed and some files could not be restored. Original backup files are retained in {staging}. '+str(commit_error)) from commit_error
   raise
  job.update(100,'Heightmap exported',force=True)
  return report
 finally:
  if not retain_staging and staging.exists() and staging.parent==output.parent and staging.name.startswith('.tf3-heightmap-export-'):shutil.rmtree(staging)

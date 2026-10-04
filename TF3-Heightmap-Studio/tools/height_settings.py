"""Heightmap settings with explicit, validated precision and editing controls. GPL-3.0."""
from copy import deepcopy
import math
from biomes import BIOME_CHOICES, CLIMATES, MODES

DEFAULTS={
 'source_mode':'Local elevation files','grid':'Match TF3 (4 m)','pixels_x':1025,'pixels_y':1025,
 'resampling':'Bilinear','band':1,'source_units':'Auto / metres','crs_override':'',
 'missing_data':'Stop at gaps','max_gap_m':100.0,'vertical_scale':1.0,'height_offset':0.0,
 'smoothing_m':0.0,'water_level':0.0,
 'lakes':False,'lake_depth':5.0,'lake_feather':8.0,
 'rivers':False,'river_width':20.0,'river_depth':4.0,'river_smoothing':20.0,
 'roads':False,'road_width':14.0,'road_blend':20.0,'road_smoothing':30.0,'road_grade':8.0,
 'railways':False,'rail_width':10.0,'rail_blend':15.0,'rail_smoothing':50.0,'rail_grade':3.0,
 'range_mode':'Automatic (preserve all heights)','range_min':-100.0,'range_max':1000.0,'clip_heights':False,
 'opentopo_dataset':'COP30','dem_urls':'','download_max_mb':512,
 'public_max_tiles':16,'source_credit':'','vertical_datum':'Unknown / unchanged',
 'lidar_max_points':100000000,
 'biomes':False,'biome_climate':'Temperate','biome_mode':'Height, slope and OSM','biome_source':'',
 'biome_base':BIOME_CHOICES[2],'biome_highland':BIOME_CHOICES[3],'biome_rock':BIOME_CHOICES[4],
 'biome_forest':BIOME_CHOICES[1],'biome_shrubs':BIOME_CHOICES[3],'biome_grass':BIOME_CHOICES[2],
 'biome_wetland':BIOME_CHOICES[1],'biome_sand':BIOME_CHOICES[3],'biome_water':True,
 'biome_highland_m':500.0,'biome_alpine_m':1500.0,'biome_rock_slope':35.0,
}
CHOICES={
 'source_mode':['Local elevation files','Download public terrain (Mapzen)','Download Copernicus GLO-30','Download Copernicus GLO-90','Download OpenTopography','Download direct GeoTIFF links'],
 'opentopo_dataset':['COP30','COP90','SRTMGL1','SRTMGL3','AW3D30','NASADEM','EU_DTM','USGS10m','USGS30m'],
 'grid':['Match TF3 (4 m)','Fine grid (2 m)','Fine grid (1 m)','Custom pixels'],
 'resampling':['Bilinear','Cubic','Nearest'],
 'source_units':['Auto / metres','Metres','Feet'],
 'missing_data':['Stop at gaps','Fill small gaps (nearest)'],
 'range_mode':['Automatic (preserve all heights)','Manual range'],
 'biome_climate':list(CLIMATES),'biome_mode':list(MODES),
 **{key:list(BIOME_CHOICES) for key in ['biome_base','biome_highland','biome_rock','biome_forest','biome_shrubs','biome_grass','biome_wetland','biome_sand']},
}
RANGES={
 'pixels_x':(33,16385),'pixels_y':(33,16385),'band':(1,100),'max_gap_m':(0,5000),
 'vertical_scale':(.001,100),'height_offset':(-20000,20000),'smoothing_m':(0,1000),
 'water_level':(-20000,20000),'lake_depth':(0,1000),'lake_feather':(0,1000),
 'river_width':(1,2000),'river_depth':(0,1000),'river_smoothing':(0,1000),
 'road_width':(1,500),'road_blend':(0,1000),'road_smoothing':(0,1000),'road_grade':(0,100),
 'rail_width':(1,500),'rail_blend':(0,1000),'rail_smoothing':(0,1000),'rail_grade':(0,100),
 'download_max_mb':(1,4096),'range_min':(-20000,20000),'range_max':(-20000,20000),'public_max_tiles':(1,64),
 'lidar_max_points':(1,2000000000),
 'biome_highland_m':(-20000,20000),'biome_alpine_m':(-20000,20000),'biome_rock_slope':(0,90),
}
INTEGERS={'pixels_x','pixels_y','band','public_max_tiles','lidar_max_points'}
# Gigantomaniac 1:2 needs 5,121 x 10,241 vertices (52,444,161).
# Cover every native TF3 4 m grid while retaining a bounded working grid.
MAX_GRID_PIXELS=53_000_000

def normalize(patch=None):
 result=deepcopy(DEFAULTS)
 if patch is None:return result
 if not isinstance(patch,dict):raise ValueError('Heightmap settings must be a JSON object.')
 for key,value in patch.items():
  if key not in DEFAULTS:raise ValueError('Unknown heightmap setting: '+str(key))
  if key in RANGES:
   low,high=RANGES[key]
   if type(value) not in {float,int} or not math.isfinite(value) or not low<=value<=high:
    raise ValueError(f'{key.replace("_"," ").capitalize()} must be between {low} and {high}.')
   if key in INTEGERS and value!=int(value):raise ValueError(key+' must be a whole number.')
   result[key]=int(value) if key in INTEGERS else float(value)
  elif key in CHOICES:
   if value not in CHOICES[key]:raise ValueError('Invalid '+key.replace('_',' ')+'.')
   result[key]=value
  elif type(DEFAULTS[key]) is bool:
   if type(value) is not bool:raise ValueError(key+' must be true or false.')
   result[key]=value
  else:
   if not isinstance(value,str) or len(value)>4000:raise ValueError(key+' must be text, at most 4000 characters.')
   result[key]=value.strip()
 if result['range_max']<=result['range_min']:raise ValueError('Maximum height must be greater than minimum height.')
 if result['biome_alpine_m']<result['biome_highland_m']:raise ValueError('Alpine biome height must be at least the highland height.')
 return result


def dimensions(size,options):
 if options['grid']=='Custom pixels': nx,ny=options['pixels_x'],options['pixels_y']
 else:
  spacing={'Match TF3 (4 m)':4,'Fine grid (2 m)':2,'Fine grid (1 m)':1}[options['grid']]
  nx,ny=[round(float(v)/spacing)+1 for v in size]
 if min(nx,ny)<33 or max(nx,ny)>16385 or nx*ny>MAX_GRID_PIXELS:
  raise ValueError('Choose a grid with 33–16,385 pixels per side and at most 53 million total pixels.')
 return int(nx),int(ny)


def validate_stroke(stroke,size):
 if not isinstance(stroke,dict) or set(stroke)!={'tool','x','y','radius','strength','target'}:raise ValueError('Invalid terrain brush record.')
 if stroke['tool'] not in ['Raise','Lower','Smooth','Flatten']:raise ValueError('Unknown terrain brush.')
 limits={'x':(-size[0]/2,size[0]/2),'y':(-size[1]/2,size[1]/2),'radius':(.1,5000),'strength':(0,1000),'target':(-20000,20000)}
 for key,(lo,hi) in limits.items():
  val=stroke[key]
  if type(val) not in {float,int} or not math.isfinite(val) or not lo<=val<=hi:raise ValueError('Invalid brush '+key+'.')
 if stroke['tool'] in ['Smooth','Flatten'] and stroke['strength']>1:raise ValueError('Smooth / Flatten strength must be between 0 and 1.')
 return dict(stroke)

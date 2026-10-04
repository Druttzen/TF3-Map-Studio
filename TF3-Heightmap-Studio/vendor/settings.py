"""Validated, portable conversion settings. GPL-3.0; standard library only."""
from copy import deepcopy
import math

V='::/'
SPECIES={
    'Oak':V+'assets/vegetation/trees/shgl_oak_01/shgl_oak_01.mdl',
    'Linden':V+'assets/vegetation/trees/eu_lnd_01/eu_lnd_01.mdl',
    'Maple':V+'assets/vegetation/trees/sgr_mpl_01/sgr_mpl_01.mdl',
    'Fir':V+'assets/vegetation/trees/confr_01/confr_01.mdl',
    'Pine':V+'assets/vegetation/trees/sct_pn_01/sct_pn_01.mdl',
    'Hazel':V+'assets/vegetation/trees/hzl_01/hzl_01.mdl',
    'Azalea':V+'assets/vegetation/trees/azalea_01/azalea_01.mdl',
}
MODELS={**SPECIES,
    'Fountain':V+'assets/landmarks/msc/fountain.mdl',
    'Mooring bollard':V+'assets/stations/water/mooring_bollard_passengers.mdl',
    'Advertising column':V+'assets/buildings/com/advertisements/column_c_01.mdl',
}
MATERIALS={
    'Asphalt':V+'terrain/materials/asphalt_01/asphalt_01.gtex',
    'Dirt':V+'terrain/materials/dirt/dirt.gtex',
    'Cut grass':V+'terrain/materials/grass_cutted_01/grass_cutted_01.gtex',
}
FEATURES={
    'roads':'Roads and tram streets','railways':'Railways',
    'footpaths':'Footpaths, cycleways and steps (small vanilla roads)',
    'disused_tracks':'Disused railway tracks','bridges':'Bridges','tunnels':'Tunnels',
    'forests':'Forests','shrubs':'Shrub areas','tree_nodes':'Individually tagged trees',
    'surfaces':'Ground surfaces','waterways':'Small mapped waters (0.5 m bed, Water Dirty)','fountains':'Fountains','bollards':'Bollards',
    'advertising_columns':'Advertising columns','place_markers':'Named places (markers or optional in-game towns)',
}
DEFAULTS={
    'features':{key:True for key in FEATURES},
    'forest_spacing':18.0,'shrub_spacing':14.4,'max_generated_trees':100000,
    'tree_jitter':0.3,'seed':'',
    'broadleaf_species':['Oak','Linden','Maple'],'conifer_species':['Fir','Pine'],
    'shrub_species':['Hazel','Azalea'],
    'road_style':'Automatic','rail_profile':'Automatic','electrification':'Automatic',
    'high_speed_threshold':160.0,'road_segment_length':80.0,'rail_segment_length':120.0,
    'tunnel_depth':8.0,'object_rotation':0.0,
    'object_models':{'tree':'Oak','fountain':'Fountain','bollard':'Mooring bollard','advertising_column':'Advertising column'},
    'surface_materials':{'asphalt':'Asphalt','dirt':'Dirt','grass':'Cut grass'},
    'import_batch_size':100,'import_delay':0.0,'waterway_width':2.0,
}
RANGES={
    'forest_spacing':(2,1000),'shrub_spacing':(2,1000),'max_generated_trees':(0,1000000),
    'tree_jitter':(0,0.49),'high_speed_threshold':(1,500),
    'road_segment_length':(5,1000),'rail_segment_length':(5,1000),
    'tunnel_depth':(0,100),'object_rotation':(-360,360),
    'import_batch_size':(1,100),'import_delay':(0,2),'waterway_width':(0.1,20),
}
CHOICES={
    'road_style':['Automatic','Town','Country'],
    'rail_profile':['Automatic','Simple','Standard','High speed'],
    'electrification':['Automatic','Always overhead','Never overhead'],
}


def normalize_options(patch=None):
    result=deepcopy(DEFAULTS)
    if patch is None: return result
    if not isinstance(patch,dict): raise ValueError('Conversion settings must be an object.')
    for key,value in patch.items():
        if key not in DEFAULTS: raise ValueError('Unknown conversion setting: '+str(key))
        if key=='features':
            if not isinstance(value,dict) or any(k not in FEATURES or type(v) is not bool for k,v in value.items()):
                raise ValueError('Feature selections must use known feature names and true/false values.')
            result[key].update(value)
        elif key in RANGES:
            low,high=RANGES[key]
            if type(value) not in {int,float} or not math.isfinite(value) or not low<=value<=high:
                raise ValueError(f'{key.replace("_"," ").capitalize()} must be between {low} and {high}.')
            if key in {'max_generated_trees','import_batch_size'} and value!=int(value):
                raise ValueError(key.replace('_',' ').capitalize()+' must be a whole number.')
            result[key]=int(value) if key in {'max_generated_trees','import_batch_size'} else float(value)
        elif key in CHOICES:
            if value not in CHOICES[key]: raise ValueError('Invalid '+key.replace('_',' ')+'.')
            result[key]=value
        elif key in {'broadleaf_species','conifer_species','shrub_species'}:
            if not isinstance(value,list) or not value or any(not isinstance(v,str) or v not in SPECIES for v in value) or len(value)!=len(set(value)):
                raise ValueError(key.replace('_',' ').capitalize()+' must contain distinct vanilla species.')
            result[key]=list(value)
        elif key in {'object_models','surface_materials'}:
            choices=MODELS if key=='object_models' else MATERIALS
            if not isinstance(value,dict) or any(k not in DEFAULTS[key] or not isinstance(v,str) or v not in choices for k,v in value.items()):
                raise ValueError('Choose only listed vanilla '+key.replace('_',' ')+'.')
            result[key].update(value)
        elif key=='seed':
            if not isinstance(value,str) or len(value)>256: raise ValueError('Random seed must be text, at most 256 characters.')
            result[key]=value
    return result

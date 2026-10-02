"""Standalone desktop heightmap studio for the second OSM map-building step. GPL-3.0."""
from copy import deepcopy
import json, math, os, queue, threading, time, webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import ImageTk
import numpy as np
from alignment import read_report, geographic, alignment_summary
from providers import download_plan
from lua_map import find_map
from height_settings import DEFAULTS, CHOICES, RANGES, INTEGERS, normalize
from terrain import prepare, export, preview_image, apply_stroke, load_project
from job import Cancelled
import biomes
from osm_converter import atomic_write

LABELS={
 'biome_climate':'Vanilla TF3 climate','biome_mode':'Biome source','biome_source':'Existing biome PNG',
 'biome_base':'Default / lowland region','biome_highland':'Highland region','biome_rock':'Alpine / steep-rock region',
 'biome_forest':'OSM forest / woodland','biome_shrubs':'OSM scrub / heath','biome_grass':'OSM grass / fields',
 'biome_wetland':'OSM wetland','biome_sand':'OSM sand / beach','biome_highland_m':'Highlands start (metres)',
 'biome_alpine_m':'Alpine regions start (metres)','biome_rock_slope':'Steep-rock slope (degrees)',
 'source_mode':'Elevation source','grid':'Output grid','pixels_x':'Custom width (pixels)','pixels_y':'Custom height (pixels)',
 'resampling':'Elevation interpolation','band':'DEM band','source_units':'Elevation units','crs_override':'Missing CRS override (EPSG code)',
 'missing_data':'Missing elevation','max_gap_m':'Maximum fill distance (game metres)',
 'vertical_scale':'Vertical scale','height_offset':'Height offset (metres)','smoothing_m':'Terrain smoothing radius (metres)',
 'water_level':'Game water level (metres)','lake_depth':'Lake depth below water level (metres)','lake_feather':'Lake bank blend (metres)',
 'river_width':'River channel width (metres)','river_depth':'River channel depth (metres)','river_smoothing':'River profile smoothing (metres)',
 'road_width':'Road terrain width (metres)','road_blend':'Road shoulder blend (metres)','road_smoothing':'Road profile smoothing (metres)','road_grade':'Road grade limit (%; 0 = off)',
 'rail_width':'Rail terrain width (metres)','rail_blend':'Rail shoulder blend (metres)','rail_smoothing':'Rail profile smoothing (metres)','rail_grade':'Rail grade limit (%; 0 = off)',
 'range_mode':'PNG height range','range_min':'Minimum import height (metres)','range_max':'Maximum import height (metres)',
 'opentopo_dataset':'OpenTopography dataset','dem_urls':'Direct GeoTIFF URLs (space separated)','download_max_mb':'Maximum download MB per file',
 'public_max_tiles':'Maximum download tiles / files','source_credit':'Elevation provider / attribution','vertical_datum':'Vertical datum / reference',
}

class App(tk.Tk):
 def __init__(self):
  super().__init__();self.title('TF3 Heightmap Studio · Step 2');self.geometry('1100x670');self.minsize(980,620);self.configure(bg='#edf2f4')
  self.busy=False;self.loading=True;self.dirty=False;self.result=None;self.report=None;self.undo=[];self.strokes=[]
  self.biome_strokes=[];self.biome_undo=[]
  self.events=queue.Queue();self.cancel_event=threading.Event();self.started=0;self.close_when_done=False;self.sources=[];self.image_bounds=None;self.render_pending=False;self.last_stamp=None
  self.protocol('WM_DELETE_WINDOW',self.close)
  style=ttk.Style(self);style.theme_use('clam')
  for cls in ['TFrame','TLabel','TCheckbutton','TRadiobutton','TLabelframe','TLabelframe.Label']:style.configure(cls,background='#edf2f4',foreground='#18333c',font=('Segoe UI',10))
  style.configure('TButton',padding=(9,7),font=('Segoe UI',10));style.configure('Accent.TButton',background='#087c83',foreground='white')
  style.map('Accent.TButton',background=[('disabled','#bac9ce'),('active','#08696f')]);style.configure('TNotebook.Tab',padding=(9,6),font=('Segoe UI',10))
  style.configure('Horizontal.TProgressbar',background='#087c83')
  header=tk.Frame(self,bg='#163b46',padx=20,pady=12);header.pack(fill='x')
  tk.Label(header,text='HEIGHTMAP STUDIO',bg='#163b46',fg='white',font=('Segoe UI',21,'bold')).pack(side='left')
  tk.Label(header,text='STEP 2 · AFTER OSM CONVERSION\nElevation import · terrain editing · 16-bit export',bg='#163b46',fg='#bbdee3',font=('Segoe UI',10),justify='right').pack(side='right')
  body=ttk.Frame(self,padding=(16,10));body.pack(fill='both',expand=True);body.columnconfigure(0,weight=1);body.columnconfigure(1,weight=1);body.rowconfigure(0,weight=1)
  self.book=ttk.Notebook(body);self.book.grid(row=0,column=0,sticky='nsew',padx=(0,12));self.pages={name:self.page(name) for name in ['Project','Elevation','Terrain','OSM terrain','Biomes','Brush']}
  self.report_path=tk.StringVar();self.osm_path=tk.StringVar();self.output_path=tk.StringVar();self.lua_path=tk.StringVar();self.lua_sha=None
  self.lua_path.trace_add('write',lambda *args:setattr(self,'lua_sha',None))
  self.values={key:tk.BooleanVar(value=value) if type(value) is bool else tk.StringVar(value=str(value)) for key,value in DEFAULTS.items()}
  self.map_info=tk.StringVar(value='Choose the converter report to lock the map alignment.')
  self.brush_tool=tk.StringVar(value='Raise');self.brush_radius=tk.StringVar(value='80');self.brush_strength=tk.StringVar(value='3');self.brush_target=tk.StringVar(value='20')
  self.api_key=tk.StringVar();self.alignment_pending=False
  self.editing=tk.BooleanVar(value=False);self.overlay=tk.BooleanVar(value=True);self.before=tk.BooleanVar(value=False)
  self.biome_view=tk.BooleanVar(value=False);self.biome_editing=tk.BooleanVar(value=False)
  self.biome_brush=tk.StringVar(value=biomes.BIOME_CHOICES[1]);self.biome_radius=tk.StringVar(value='80')
  self.build_project();self.build_elevation();self.build_terrain();self.build_osm();self.build_biomes();self.build_brush()
  side=ttk.Frame(body);side.grid(row=0,column=1,sticky='nsew');side.columnconfigure(0,weight=1);side.rowconfigure(2,weight=1)
  ttk.Label(side,text='ALIGNED TERRAIN PREVIEW',font=('Segoe UI',11,'bold')).grid(row=0,column=0,sticky='w',pady=(0,6))
  toggles=ttk.Frame(side);toggles.grid(row=1,column=0,sticky='ew',pady=(0,5))
  ttk.Checkbutton(toggles,text='OSM overlay',variable=self.overlay,command=self.render).pack(side='left')
  ttk.Checkbutton(toggles,text='Before OSM / brush edits',variable=self.before,command=self.render).pack(side='left',padx=10)
  ttk.Checkbutton(toggles,text='Biomes',variable=self.biome_view,command=self.render).pack(side='left')
  self.view=ttk.Notebook(side);self.view.grid(row=2,column=0,sticky='nsew');preview=ttk.Frame(self.view);self.view.add(preview,text='Terrain')
  self.canvas=tk.Canvas(preview,bg='#f8fafb',highlightthickness=0);self.canvas.pack(fill='both',expand=True);self.canvas.bind('<Configure>',lambda e:self.render())
  self.canvas.bind('<Motion>',self.hover);self.canvas.bind('<Button-1>',self.stamp);self.canvas.bind('<B1-Motion>',self.drag_stamp);self.canvas.bind('<ButtonRelease-1>',lambda e:setattr(self,'last_stamp',None))
  self.coords=tk.StringVar(value='North is at the top. Build terrain to inspect measured heights.')
  ttk.Label(preview,textvariable=self.coords,font=('Segoe UI',9),wraplength=490).pack(anchor='w',pady=5)
  report_frame=ttk.Frame(self.view);self.view.add(report_frame,text='Report')
  self.text=tk.Text(report_frame,wrap='word',font=('Segoe UI',10),width=35,bg='white',relief='flat',padx=12,pady=12)
  bar=ttk.Scrollbar(report_frame,command=self.text.yview);self.text.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');self.text.pack(fill='both',expand=True)
  self.quality=tk.StringVar(value='Accuracy follows the elevation source; edits are authored changes.')
  ttk.Label(side,textvariable=self.quality,wraplength=490,font=('Segoe UI',9)).grid(row=3,column=0,sticky='w',pady=(6,0))
  footer=ttk.Frame(self,padding=(18,8,18,14));footer.pack(side='bottom',fill='x',before=body)
  line=ttk.Frame(footer);line.pack(fill='x',pady=(0,7));self.status=tk.StringVar(value='Ready · choose converter report, Lua, OSM and elevation data');self.percent=tk.StringVar(value='0%');self.elapsed=tk.StringVar()
  ttk.Label(line,textvariable=self.status).pack(side='left');ttk.Label(line,textvariable=self.elapsed).pack(side='right',padx=12);ttk.Label(line,textvariable=self.percent).pack(side='right')
  self.progress=ttk.Progressbar(footer,mode='determinate',maximum=100);self.progress.pack(fill='x',pady=(0,9))
  buttons=ttk.Frame(footer);buttons.pack(fill='x')
  self.build_button=ttk.Button(buttons,text='Build terrain',style='Accent.TButton',command=self.build);self.build_button.pack(side='left')
  self.export_button=ttk.Button(buttons,text='Export heightmap',command=self.export,state='disabled');self.export_button.pack(side='left',padx=8)
  self.cancel_button=ttk.Button(buttons,text='Cancel',command=self.cancel,state='disabled');self.cancel_button.pack(side='left')
  self.open_button=ttk.Button(buttons,text='Open output',command=self.open_output,state='disabled');self.open_button.pack(side='left',padx=8)
  self.project_buttons=[]
  for text,fn in [('Load project…',self.load),('Save project…',self.save)]:
   b=ttk.Button(buttons,text=text,command=fn);b.pack(side='right',padx=(8,0));self.project_buttons.append(b)
  self.show('1. Run the OSM converter and keep its JSON report.\n2. Choose that report, its converted .lua and the original .osm here.\n3. Add a measured elevation file, or choose Download public terrain.\n4. Build terrain, review the map, and fine-tune settings or brush edits.\n5. Export the 16-bit PNG and use the exact import heights in its instructions.\n\nOSM and converter logs align features; they do not measure terrain elevation. Local surveyed/LiDAR DEMs can supply finer detail than public tiles. No automatic vertical datum conversion is performed.\n\nOptional OSM refinements change terrain for water areas and road/rail corridors. Bridge/tunnel interiors are excluded. These are authored edits, not extra elevation measurements.\n\nNative TF3 heightmap import remains to be checked in a game session.')
  for var in [self.report_path,self.osm_path,self.lua_path,*self.values.values()]:var.trace_add('write',lambda *args:self.changed())
  self.loading=False;self.after(80,self.poll)

 def page(self,name):
  outer=ttk.Frame(self.book);self.book.add(outer,text=name);canvas=tk.Canvas(outer,bg='#edf2f4',highlightthickness=0);bar=ttk.Scrollbar(outer,command=canvas.yview)
  canvas.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
  frame=ttk.Frame(canvas,padding=13);frame.columnconfigure(1,weight=1);window=canvas.create_window(0,0,window=frame,anchor='nw')
  frame.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
  def wheel(e):
   if self.book.select()==str(outer) and str(e.widget).startswith(str(outer)+'.'):canvas.yview_scroll(int(-e.delta/120),'units')
  outer.bind_all('<MouseWheel>',wheel,add='+');return frame

 def note(self,f,row,text):
  label=ttk.Label(f,text=text,wraplength=480,font=('Segoe UI',9));label.grid(row=row,column=0,columnspan=3,sticky='w',pady=(5,12))
  f.bind('<Configure>',lambda e:label.configure(wraplength=max(230,e.width-28)),add='+')

 def field(self,f,row,key,var=None,choices=None):
  var=var or self.values[key];ttk.Label(f,text=LABELS.get(key,key)).grid(row=row,column=0,sticky='w',padx=(0,10),pady=6)
  control=ttk.Combobox(f,textvariable=var,values=choices or CHOICES.get(key),state='readonly',width=20) if choices or key in CHOICES else ttk.Entry(f,textvariable=var,width=15)
  control.grid(row=row,column=1,columnspan=2,sticky='ew',pady=6);return control

 def path(self,f,row,label,var,fn):
  ttk.Label(f,text=label).grid(row=row,column=0,columnspan=3,sticky='w',pady=(9,4))
  ttk.Entry(f,textvariable=var).grid(row=row+1,column=0,columnspan=2,sticky='ew');ttk.Button(f,text='Browse…',command=fn).grid(row=row+1,column=2,padx=(7,0));f.columnconfigure(0,weight=1)

 def build_project(self):
  f=self.pages['Project'];self.path(f,0,'Converter JSON report (.report.json / import-report.json)',self.report_path,self.choose_report)
  self.path(f,2,'Converted map Lua (.lua / content/osm/dataset.lua)',self.lua_path,self.choose_lua)
  self.path(f,4,'Original OSM XML file (.osm)',self.osm_path,self.choose_osm)
  ttk.Label(f,textvariable=self.map_info,wraplength=480,font=('Segoe UI',10,'bold')).grid(row=6,column=0,columnspan=3,sticky='w',pady=12)
  self.path(f,7,'Exported 16-bit heightmap PNG',self.output_path,self.choose_output)
  self.note(f,9,'Load the converted Lua and its JSON log together. Roads and tracks follow exported nodes and segments; water comes from original OSM. Dataset, coordinates, size, settings and counts must match. Converter 0.5 reports also verify both source checksums.')
  self.field(f,10,'grid');self.field(f,11,'pixels_x');self.field(f,12,'pixels_y')
  self.note(f,13,'Match TF3 samples at 4-metre game spacing. Fine/custom grids retain the same bounds; they do not create finer source measurements or change the game terrain grid.')

 def build_elevation(self):
  f=self.pages['Elevation'];self.field(f,0,'source_mode')
  self.note(f,1,'Every source is cropped and scaled to the converter bounds and chosen TF3 map size. Mapzen and Copernicus need no account. OpenTopography needs your API key. Direct links must point to GeoTIFF DEM files.')
  controls=ttk.Frame(f);controls.grid(row=2,column=0,columnspan=3,sticky='w',pady=5)
  ttk.Button(controls,text='Check download area',command=self.show_plan).pack(side='left',padx=(0,8))
  ttk.Button(controls,text='Open source website',command=self.open_provider).pack(side='left')
  self.field(f,3,'opentopo_dataset')
  ttk.Label(f,text='OpenTopography API key (this session only)').grid(row=4,column=0,columnspan=3,sticky='w',pady=(8,4))
  ttk.Entry(f,textvariable=self.api_key,show='•').grid(row=5,column=0,columnspan=3,sticky='ew')
  self.note(f,6,'The API key is never saved in project files or reports. For other websites, download a georeferenced DEM and Add files, or paste its public direct GeoTIFF URL below.')
  ttk.Label(f,text=LABELS['dem_urls']).grid(row=7,column=0,columnspan=3,sticky='w',pady=(4,4))
  ttk.Entry(f,textvariable=self.values['dem_urls']).grid(row=8,column=0,columnspan=3,sticky='ew')
  self.source_list=tk.Listbox(f,height=4,font=('Segoe UI',9),selectmode='extended',exportselection=False)
  self.source_list.grid(row=9,column=0,columnspan=3,sticky='ew',pady=(12,0))
  controls=ttk.Frame(f);controls.grid(row=10,column=0,columnspan=3,sticky='w',pady=7)
  for text,fn in [('Add files…',self.add_sources),('Remove',self.remove_sources),('Move up',lambda:self.move_source(-1)),('Move down',lambda:self.move_source(1))]:ttk.Button(controls,text=text,command=fn).pack(side='left',padx=(0,6))
  self.note(f,11,'Earlier files take priority where DEMs overlap; later files fill gaps. Elevation data needs a valid coordinate reference system. No files are uploaded. Public download plans can include a border margin for interpolation; the exported map bounds stay exact.')
  for row,key in enumerate(['resampling','band','source_units','crs_override','missing_data','max_gap_m','public_max_tiles','download_max_mb','source_credit','vertical_datum'],12):self.field(f,row,key)

 def show_plan(self):
  try:
   report=read_report(self.report_path.get());options=self.options();a=alignment_summary(report,options);p=download_plan(report['bounds'],options)
   message=f"COORDINATE MATCH\n\nWGS84 latitude / longitude\nSouth {a['south']:.7f} · West {a['west']:.7f}\nNorth {a['north']:.7f} · East {a['east']:.7f}\n\nTF3 map: {a['gameWidthMetres']:g} × {a['gameHeightMetres']:g} m\nHeightmap: {a['pixels'][0]:,} × {a['pixels'][1]:,} pixels\nNorth is at the top. Corner vertices match the OSM map.\n\nSource: {p['provider']}\nDownload requests: {len(p['requests'])}\nRequest bounds (S,W,N,E): "+', '.join(f'{v:.7f}' for v in p['requestBounds'])+'\n\nChange the TF3 map size in the OSM converter, then use its new report here so both outputs remain aligned.\n'
   message+='\n'.join(r.get('tile',r.get('dataset','Direct GeoTIFF file')) for r in p['requests'])
   self.show(message);self.view.select(1)
  except (ValueError,OSError) as exc:messagebox.showerror('Check download area',str(exc),parent=self)

 def open_provider(self):
  try:
   p=download_plan(read_report(self.report_path.get())['bounds'],self.options())
   if p['site']:webbrowser.open(p['site'])
   else:self.show_plan()
  except (ValueError,OSError) as exc:messagebox.showerror('Choose map and source',str(exc),parent=self)

 def refresh_alignment(self):
  self.alignment_pending=False
  try:
   r=read_report(self.report_path.get());a=alignment_summary(r,self.options());x,y=a['gridSpacingGameMetres']
   self.map_info.set(f"TF3 map: {a['gameWidthMetres']:g} × {a['gameHeightMetres']:g} m · locked to OSM\nWGS84: S {a['south']:.6f}, W {a['west']:.6f}\nN {a['north']:.6f}, E {a['east']:.6f}\nOutput: {a['pixels'][0]:,} × {a['pixels'][1]:,} pixels · {x:.2f} × {y:.2f} m")
  except (ValueError,OSError):self.map_info.set('Select a valid converter report and grid settings to inspect alignment.')

 def build_terrain(self):
  f=self.pages['Terrain'];self.note(f,0,'Measured heights remain unchanged by default. Use a vertical scale or offset to fit your game map, and smoothing to remove unwanted terrain noise.')
  for row,key in enumerate(['vertical_scale','height_offset','smoothing_m','water_level','range_mode','range_min','range_max'],1):self.field(f,row,key)
  ttk.Checkbutton(f,text='Allow PNG clipping outside the manual height range',variable=self.values['clip_heights']).grid(row=8,column=0,columnspan=3,sticky='w',pady=7)
  self.note(f,9,'Automatic range preserves all heights. The export includes exact minimum, maximum and water-level settings. Its float64 GeoTIFF preserves elevations before any PNG clipping. The native game checks its allowable height limits.')

 def build_osm(self):
  f=self.pages['OSM terrain'];self.note(f,0,'These optional refinements alter measured terrain. Roads/tracks use converted Lua geometry; water uses original OSM, and leave bridge/tunnel interiors unchanged.')
  row=1
  for flag,label,keys in [('lakes','Lower lake / reservoir beds',['lake_depth','lake_feather']),('rivers','Carve river / stream channels',['river_width','river_depth','river_smoothing']),('roads','Refine road terrain corridors',['road_width','road_blend','road_smoothing','road_grade']),('railways','Refine railway terrain corridors',['rail_width','rail_blend','rail_smoothing','rail_grade'])]:
   ttk.Checkbutton(f,text=label,variable=self.values[flag]).grid(row=row,column=0,columnspan=3,sticky='w',pady=(12,5));row+=1
   for key in keys:self.field(f,row,key);row+=1
  self.note(f,row,'Lake islands and holes are preserved. River channels follow local elevation; TF3 has one water level. Grade limits apply to prepared corridor profiles; inspect actual junctions and connections in the game.')

 def build_brush(self):
  f=self.pages['Brush'];self.note(f,0,'After building terrain, enable the brush and click or drag on the preview to stamp edits in game metres. Turn off Before OSM / brush edits to edit the final terrain.')
  ttk.Checkbutton(f,text='Enable terrain brush on preview',variable=self.editing,command=self.terrain_brush_enabled).grid(row=1,column=0,columnspan=3,sticky='w',pady=6)
  self.field(f,2,'Brush tool',self.brush_tool,['Raise','Lower','Smooth','Flatten']);self.field(f,3,'Brush radius (metres)',self.brush_radius)
  self.field(f,4,'Height delta (m) / blend strength (0–1)',self.brush_strength);self.field(f,5,'Flatten target height (metres)',self.brush_target)
  self.note(f,6,'Raise / Lower use a height delta in metres. Smooth / Flatten use a blend strength from 0 to 1. A soft edge keeps brush stamps smooth. Hover to read coordinates and heights.')
  b=ttk.Frame(f);b.grid(row=7,column=0,columnspan=3,sticky='w')
  self.undo_button=ttk.Button(b,text='Undo last stamp',command=self.undo_stamp,state='disabled');self.undo_button.pack(side='left',padx=(0,8))
  self.clear_button=ttk.Button(b,text='Clear brush edits + rebuild',command=self.clear_strokes);self.clear_button.pack(side='left')
  self.note(f,8,'Save project retains brush strokes and every setting. The latest eight stamps are available for undo, within a 128 MB undo budget. Load a project and Build terrain to reproduce its edits.')

 def build_biomes(self):
  f=self.pages['Biomes']
  ttk.Checkbutton(f,text='Generate and export vanilla TF3 biome map',variable=self.values['biomes']).grid(row=0,column=0,columnspan=3,sticky='w',pady=7)
  self.field(f,1,'biome_climate');self.field(f,2,'biome_mode')
  self.path(f,3,'Existing 8-bit TF3 biome PNG (Import biome PNG mode)',self.values['biome_source'],self.choose_biomes)
  self.note(f,5,'Choose the same climate when creating your TF3 map. Biome IDs 0–4 are regions within that climate; the game supplies their textures and vegetation. Existing PNGs must match this heightmap’s pixel dimensions and use codes 0, 63, 127, 191, 255.')
  for row,key in enumerate(['biome_base','biome_highland','biome_rock','biome_highland_m','biome_alpine_m','biome_rock_slope','biome_forest','biome_shrubs','biome_grass','biome_wetland','biome_sand'],6):self.field(f,row,key)
  ttk.Checkbutton(f,text='Set underwater terrain to Biome 0 in generated maps',variable=self.values['biome_water']).grid(row=17,column=0,columnspan=3,sticky='w',pady=7)
  self.note(f,18,'Automatic rules: lowland → highland → alpine / steep rock → OSM land cover → underwater. OSM polygons retain holes. Single biome uses Default; height rules ignore OSM; imported PNGs retain their own regions. Biomes do not change measured heights.')
  ttk.Checkbutton(f,text='Enable biome paint brush on preview',variable=self.biome_editing,command=self.biome_brush_enabled).grid(row=19,column=0,columnspan=3,sticky='w',pady=7)
  self.field(f,20,'Paint region',self.biome_brush,list(biomes.BIOME_CHOICES));self.field(f,21,'Biome brush radius (metres)',self.biome_radius)
  self.biome_undo_button=ttk.Button(f,text='Undo last biome stamp',command=self.undo_biome,state='disabled');self.biome_undo_button.grid(row=22,column=0,columnspan=3,sticky='w',pady=6)
  ttk.Button(f,text='Clear biome paint + rebuild',command=self.clear_biomes).grid(row=23,column=0,columnspan=3,sticky='w',pady=6)
  self.note(f,24,'After Build terrain, view Biomes and paint regions. Paint overrides automatic rules; save/load retains it. Exports include native grayscale PNG, colour preview, georeferenced ID GeoTIFF and import instructions. Native game biome import still requires verification.')

 def choose_biomes(self):
  path=filedialog.askopenfilename(parent=self,title='Choose TF3 biome PNG',filetypes=[('TF3 biome PNG','*.png')])
  if path:self.values['biome_source'].set(path);self.values['biome_mode'].set('Import biome PNG');self.values['biomes'].set(True)

 def terrain_brush_enabled(self):
  if self.editing.get():self.biome_editing.set(False);self.biome_view.set(False);self.render()

 def biome_brush_enabled(self):
  if self.biome_editing.get():self.editing.set(False);self.biome_view.set(True);self.before.set(False);self.render()

 def changed(self):
  if self.loading:return
  self.dirty=True
  if not self.alignment_pending:self.alignment_pending=True;self.after_idle(self.refresh_alignment)
  if hasattr(self,'export_button'):self.export_button.configure(state='disabled')
  if self.result and not self.busy:self.status.set('Settings changed · rebuild terrain to update the preview')

 def choose_report(self):
  path=filedialog.askopenfilename(parent=self,title='Choose OSM converter report',filetypes=[('Converter report','*.json')])
  if not path:return
  try:
   candidate_report=read_report(path);self.check_brush_alignment(candidate_report);self.report=candidate_report;self.report_path.set(path);r=self.report;a,b,c,d=r['bounds'];w,h=r['mapSize']
   self.lua_path.set(find_map(path,r))
   self.map_info.set(f'Map: {w:g} × {h:g} metres\nBounds: {a:.7f}, {b:.7f} → {c:.7f}, {d:.7f}')
   candidate=Path(path).parent/r.get('input','')
   if candidate.is_file() and candidate.suffix.lower()=='.osm':self.osm_path.set(str(candidate))
   if not self.output_path.get():self.output_path.set(str(Path(path).parent/'heightmap.png'))
  except (ValueError,OSError) as exc:messagebox.showerror('Invalid converter report',str(exc),parent=self)

 def choose_lua(self):
  path=filedialog.askopenfilename(parent=self,title='Choose converted map Lua',filetypes=[('Converted map','*.lua')])
  if path:self.lua_path.set(path)

 def choose_osm(self):
  path=filedialog.askopenfilename(parent=self,title='Choose original OSM XML',filetypes=[('OSM XML','*.osm')])
  if path:self.osm_path.set(path)

 def choose_output(self):
  path=filedialog.asksaveasfilename(parent=self,title='Export heightmap PNG',defaultextension='.png',filetypes=[('16-bit heightmap','*.png')])
  if path:self.output_path.set(path)

 def add_sources(self):
  paths=filedialog.askopenfilenames(parent=self,title='Add measured elevation files',filetypes=[('Elevation data','*.tif *.tiff *.asc *.hgt *.gz')])
  for path in paths:
   if path not in self.sources:self.sources.append(path)
  self.update_sources();self.changed()

 def update_sources(self):
  self.source_list.delete(0,'end')
  for path in self.sources:self.source_list.insert('end',path)

 def remove_sources(self):
  for i in reversed(self.source_list.curselection()):self.sources.pop(i)
  self.update_sources();self.changed()

 def move_source(self,direction):
  selection=self.source_list.curselection()
  if len(selection)!=1:return
  i=selection[0];j=i+direction
  if 0<=j<len(self.sources):self.sources[i],self.sources[j]=self.sources[j],self.sources[i];self.update_sources();self.source_list.selection_set(j);self.changed()

 def options(self):
  values={key:var.get() for key,var in self.values.items()}
  for key in RANGES:
   try:values[key]=float(values[key])
   except ValueError:raise ValueError(LABELS[key]+' must be a number.')
  return normalize(values)

 def form_project(self):
  r=read_report(self.report_path.get());self.check_brush_alignment(r);return {'format':'TF3-Heightmap-Studio','version':1,'converterReport':self.report_path.get(),'osmFile':self.osm_path.get(),
   'convertedLua':self.lua_path.get(),'luaSha256':self.lua_sha,
   'converterDataset':r['dataset'],'osmSha256':r.get('sourceSha256'),'bounds':r['bounds'],'mapSize':r['mapSize'],
   'elevationFiles':list(self.sources),'options':self.options(),'brushStrokes':list(self.strokes),
   'biomeStrokes':list(self.biome_strokes),'biomeSourceSha256':(self.result.get('biomeSource') or {}).get('sha256') if self.result and not self.dirty else None,'output':self.output_path.get()}

 def save(self):
  try:
   project=self.form_project();path=filedialog.asksaveasfilename(parent=self,title='Save heightmap project',defaultextension='.heightmap-project.json',filetypes=[('Heightmap project','*.json')])
   if path:atomic_write(path,json.dumps(project,indent=2,ensure_ascii=False)+'\n');self.status.set('Heightmap project saved')
  except (ValueError,OSError) as exc:messagebox.showerror('Could not save project',str(exc),parent=self)

 def load(self):
  path=filedialog.askopenfilename(parent=self,title='Load heightmap project',filetypes=[('Heightmap project','*.json')])
  if not path:return
  try:
   p=load_project(path);r=read_report(p['converterReport'])
   if r['bounds']!=p['bounds'] or r['mapSize']!=p['mapSize'] or r['dataset']!=p.get('converterDataset'):
    raise ValueError('The converter report has changed since this project was saved. Restore its original report.')
   self.loading=True
   for key,var in self.values.items():var.set(p['options'][key])
   self.report_path.set(p['converterReport']);self.osm_path.set(p['osmFile']);self.output_path.set(p.get('output',''));self.sources=p['elevationFiles'];self.update_sources();self.strokes=p['brushStrokes'];self.undo=[];self.report=r
   self.lua_path.set(p.get('convertedLua') or find_map(p['converterReport'],r));self.lua_sha=p.get('luaSha256')
   self.map_info.set(f"Map: {r['mapSize'][0]:g} × {r['mapSize'][1]:g} metres\nBounds: "+', '.join(f'{v:.7f}' for v in r['bounds']))
   self.biome_strokes=p['biomeStrokes'];self.biome_undo=[];self.biome_undo_button.configure(state='disabled')
   self.result=None;self.dirty=True;self.export_button.configure(state='disabled');self.undo_button.configure(state='disabled');self.status.set('Project loaded · Build terrain to recreate its preview');self.quality.set('Build terrain to inspect this project’s elevation sources.');self.show('Project loaded. Build terrain to recreate its preview and source report.');self.percent.set('0%');self.progress['value']=0;self.render()
  except (ValueError,OSError) as exc:messagebox.showerror('Could not load project',str(exc),parent=self)
  finally:self.loading=False;self.refresh_alignment()

 def freeze(self,busy):
  if busy:
   self.saved_states=[]
   def walk(widget):
    for child in widget.winfo_children():
     if isinstance(child,(ttk.Entry,ttk.Combobox,ttk.Checkbutton,ttk.Button,tk.Listbox)):
      self.saved_states.append((child,str(child.cget('state'))));child.configure(state='disabled')
     walk(child)
   walk(self.book)
  else:
   for widget,state in self.saved_states:widget.configure(state=state)
  for b in self.project_buttons:b.configure(state='disabled' if busy else 'normal')
  self.build_button.configure(state='disabled' if busy else 'normal');self.cancel_button.configure(state='normal' if busy else 'disabled')
  self.export_button.configure(state='normal' if not busy and self.result and not self.dirty else 'disabled')
  self.undo_button.configure(state='normal' if not busy and self.undo else 'disabled')
  self.biome_undo_button.configure(state='normal' if not busy and self.biome_undo else 'disabled')

 def start_worker(self,fn,mode):
  self.busy=True;self.close_when_done=False;self.cancel_event.clear();self.started=time.monotonic();self.freeze(True);self.progress['value']=0;self.percent.set('0%');self.status.set('Starting '+mode+'…')
  def progress(percent,stage,detail):self.events.put(('progress',(percent,stage,detail)))
  def worker():
   try:self.events.put((mode,fn(progress)))
   except Cancelled as exc:self.events.put(('cancelled',str(exc)))
   except Exception as exc:self.events.put(('error',str(exc)))
  threading.Thread(target=worker,daemon=True).start()

 def build(self):
  if self.busy:return
  try:
   options=self.options();report=self.report_path.get().strip();osm=self.osm_path.get().strip();paths=list(self.sources);lua=self.lua_path.get().strip();lua_sha=self.lua_sha
   if not report or not osm:raise ValueError('Choose the converter report and original OSM file first.')
   current=read_report(report);self.check_brush_alignment(current)
   if not Path(osm).is_file():raise ValueError('The original OSM file does not exist.')
   if not lua or not Path(lua).is_file():raise ValueError('Choose the matching converted .lua map file. The JSON log and Lua dataset are both used.')
   if options['source_mode'].startswith('Local') and not paths:raise ValueError('Add a local elevation file, or choose public-data download.')
   if options['source_mode'].startswith('Download'):download_plan(current['bounds'],options)
   api_key=self.api_key.get().strip();strokes=deepcopy(self.strokes);biome_strokes=deepcopy(self.biome_strokes)
  except (ValueError,OSError) as exc:messagebox.showerror('Check heightmap settings',str(exc),parent=self);return
  self.start_worker(lambda progress:prepare(report,osm,paths,options,strokes,progress=progress,cancel=self.cancel_event,api_key=api_key,lua_path=lua,lua_sha=lua_sha,biome_strokes=biome_strokes),'build')

 def check_brush_alignment(self,current):
  original=self.result['context']['report'] if self.result else self.report
  if (self.strokes or self.biome_strokes) and original and any(current[k]!=original[k] for k in ['dataset','bounds','mapSize']):
   raise ValueError('Brush edits belong to a different converter map. Clear brush edits or restore the original report.')

 def export(self):
  if self.busy or not self.result or self.dirty:return
  if not self.output_path.get():self.choose_output()
  if not self.output_path.get():return
  result=self.result;output=self.output_path.get()
  self.start_worker(lambda progress:export(result,output,progress=progress,cancel=self.cancel_event),'export')

 def cancel(self):
  self.cancel_event.set();self.cancel_button.configure(state='disabled');self.status.set('Cancelling… existing exports are kept')

 def poll(self):
  if self.busy:
   seconds=int(time.monotonic()-self.started);self.elapsed.set(f'{seconds//60:02d}:{seconds%60:02d}')
  while True:
   try:kind,value=self.events.get_nowait()
   except queue.Empty:break
   if kind=='progress':
    percent,stage,detail=value;self.progress['value']=percent;self.percent.set(f'{percent:.0f}%')
    if not self.cancel_event.is_set():self.status.set(stage+(' · '+detail if detail else ''))
    if percent>=98:self.cancel_button.configure(state='disabled')
    continue
   self.busy=False
   if kind=='build':
    self.lua_sha=value['context']['convertedLua']['sha256'] if value['context'].get('convertedLua') else None
    self.result=value;self.strokes=value['strokes'];self.undo=[];self.dirty=False;self.progress['value']=100;self.percent.set('100%');self.status.set('Terrain ready · inspect, edit or export')
    self.biome_strokes=value['biomeStrokes'];self.biome_undo=[]
    ny,nx=value['terrain'].shape;res=value['sources'][0]['sourceResolutionMetres'];size=value['context']['size']
    self.quality.set(f'Source cell (approx.): {res[0]:.1f} × {res[1]:.1f} m\nGame grid: {size[0]/(nx-1):.2f} × {size[1]/(ny-1):.2f} m · {nx:,} × {ny:,} pixels')
    self.refresh_alignment();self.show(f"Coordinate match: converter bounds and TF3 size verified.\nTF3 map: {size[0]:g} × {size[1]:g} m\nTerrain: {nx:,} × {ny:,} pixels\nHeight: {float(value['terrain'].min()):.3f} to {float(value['terrain'].max()):.3f} m\nConverter dataset: {value['context']['report']['dataset']}\n\nSource files:\n"+'\n'.join(Path(s['file']).name for s in value['sources'])+'\n\nNotes:\n'+'\n\n'.join(value['warnings']))
    self.view.select(0);self.render()
    if value['context'].get('convertedLua'):
     info=value['context']['convertedLua'];self.show(self.text.get('1.0','end').rstrip()+f"\n\nConverted Lua: {Path(info['file']).name}\n{info['roadSegments']} road segments, {info['railSegments']} rail segments; {info['corridorPolylines']} joined corridors\nLua/report checksum: {'verified' if info['reportChecksumVerified'] else 'older report without checksum'}\nRoad/rail guides come from the converted map. Water features come from original OSM.")
    if value['options']['biomes']:
     summary=biomes.summary(value);self.show(self.text.get('1.0','end').rstrip()+f"\n\nVanilla climate: {summary['climate']}\nBiome regions:\n"+'\n'.join(f"{p['label']}: {p['percent']:.2f}%" for p in summary['palette']))
   elif kind=='export':
    self.progress['value']=100;self.percent.set('100%');self.status.set('Heightmap exported · use the supplied TF3 import settings');self.open_button.configure(state='normal')
    self.show(f"Export complete\n\nPNG: {value['files']['png']}\n\nTF3 import values:\nMinimum: {value['importMinimumMetres']:g} m\nMaximum: {value['importMaximumMetres']:g} m\nWater: {value['waterLevelMetres']:g} m\n\n16-bit encoding step: {value['pngEncodingStepMetres']:.6f} m\nThis numeric step does not establish source measurement accuracy.\n\nAlso saved: edited-height GeoTIFF, preview, project, detailed report, attribution and import instructions.\n\n"+'\n\n'.join(value['warnings']))
    self.view.select(1)
    if value.get('biomes'):self.show(self.text.get('1.0','end').rstrip()+f"\n\nBiome PNG: {value['files']['biomes']}\nChoose {value['biomes']['climate']} in TF3 and follow the Biomes section in the import instructions.")
   else:self.status.set('Cancelled' if kind=='cancelled' else 'Heightmap operation failed · see report');self.show(value);self.view.select(1)
   self.freeze(False)
   if self.close_when_done:self.destroy();return
  self.after(80,self.poll)

 def show(self,text):
  self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',text);self.text.configure(state='disabled')

 def render(self):
  if not hasattr(self,'canvas'):return
  self.render_pending=False;self.canvas.delete('all');self.image_bounds=None;w=self.canvas.winfo_width();h=self.canvas.winfo_height()
  if min(w,h)<20:return
  if not self.result:self.canvas.create_text(w/2,h/2,text='Your terrain appears here\nafter building',font=('Segoe UI',12),fill='#71909a',justify='center');return
  result=self.result if not self.before.get() else {**self.result,'terrain':self.result['baseline']}
  if self.biome_view.get() and not self.result['options']['biomes']:
   self.canvas.create_text(w/2,h/2,text='Enable biome export in Biomes,\nthen Build terrain.',font=('Segoe UI',12),fill='#71909a',justify='center');return
  image=biomes.preview(self.result,(max(2,w-20),max(2,h-20)),self.overlay.get()) if self.biome_view.get() else preview_image(result,(max(2,w-20),max(2,h-20)),self.overlay.get())
  self.photo=ImageTk.PhotoImage(image);x=(w-image.width)/2;y=(h-image.height)/2
  self.canvas.create_image(x,y,image=self.photo,anchor='nw');self.image_bounds=(x,y,image.width,image.height)

 def coordinates(self,event):
  if not self.image_bounds or not self.result:return None
  x0,y0,w,h=self.image_bounds;fx=(event.x-x0)/(w-1);fy=(event.y-y0)/(h-1)
  if not 0<=fx<=1 or not 0<=fy<=1:return None
  size=self.result['context']['size'];return (fx-.5)*size[0],(.5-fy)*size[1]

 def hover(self,event):
  p=self.coordinates(event)
  if p is None:return
  x,y=p;result=self.result;ny,nx=result['terrain'].shape;size=result['context']['size'];row=round((.5-y/size[1])*(ny-1));col=round((x/size[0]+.5)*(nx-1))
  lat,lon=geographic(x,y,result['context']['bounds'],size);terrain=result['baseline'] if self.before.get() else result['terrain']
  self.coords.set(f'Height: {terrain[row,col]:.3f} m · X {x:.1f}, Y {y:.1f} m\nLatitude {lat:.7f} · Longitude {lon:.7f}')
  if self.biome_view.get():self.coords.set(self.coords.get()+f" · {biomes.BIOME_CHOICES[int(biomes.ensure(result)[row,col])]}")

 def stamp(self,event):
  if self.biome_editing.get():self.stamp_biome(event);return
  if self.busy or self.dirty or not self.editing.get() or self.before.get():return
  p=self.coordinates(event)
  if p is None:return
  try:
   stroke={'tool':self.brush_tool.get(),'x':p[0],'y':p[1],'radius':float(self.brush_radius.get()),'strength':float(self.brush_strength.get()),'target':float(self.brush_target.get())}
   if stroke['tool'] in {'Smooth','Flatten'} and stroke['strength']>1:raise ValueError('Smooth / Flatten strength must be between 0 and 1.')
   if len(self.strokes)>=10000:raise ValueError('A project can contain at most 10,000 brush stamps.')
   undo=apply_stroke(self.result['terrain'],self.result['context']['size'],stroke)
  except ValueError as exc:messagebox.showerror('Check brush settings',str(exc),parent=self);return
  self.strokes.append(stroke);self.result['strokes']=self.strokes
  self.result['biomes']=None
  self.biome_undo=[];self.biome_undo_button.configure(state='disabled')
  if undo:
   self.undo.append(undo)
   while len(self.undo)>8 or sum(v[4].nbytes for v in self.undo)>128*1024*1024:self.undo.pop(0)
  self.undo_button.configure(state='normal' if self.undo else 'disabled');self.last_stamp=(p[0],p[1],time.monotonic());self.status.set(f'{stroke["tool"]} applied · {len(self.strokes)} brush stamps');self.schedule_render()

 def drag_stamp(self,event):
  p=self.coordinates(event)
  if p is None:return
  try:radius=float(self.biome_radius.get() if self.biome_editing.get() else self.brush_radius.get())
  except ValueError:return
  if self.last_stamp and (time.monotonic()-self.last_stamp[2]<.15 or math.dist(p,self.last_stamp[:2])<radius*.35):return
  self.stamp(event)

 def schedule_render(self):
  if not self.render_pending:self.render_pending=True;self.after_idle(self.render)

 def undo_stamp(self):
  if self.busy or not self.undo or not self.result:return
  r0,r1,c0,c1,old=self.undo.pop();self.result['terrain'][r0:r1,c0:c1]=old;self.strokes.pop();self.result['strokes']=self.strokes
  self.result['biomes']=None
  self.biome_undo=[];self.biome_undo_button.configure(state='disabled')
  self.undo_button.configure(state='normal' if self.undo else 'disabled');self.status.set('Last brush stamp undone');self.render()

 def clear_strokes(self):
  if self.busy:return
  self.strokes=[];self.undo=[];self.undo_button.configure(state='disabled');self.build()

 def stamp_biome(self,event):
  if self.busy or self.dirty or not self.result or not self.result['options']['biomes'] or not self.biome_view.get():return
  p=self.coordinates(event)
  if p is None:return
  try:
   stroke={'x':p[0],'y':p[1],'radius':float(self.biome_radius.get()),'biome':biomes.biome_id(self.biome_brush.get())}
   if len(self.biome_strokes)>=10000:raise ValueError('At most 10,000 biome brush stamps are supported.')
   undo=biomes.paint(biomes.ensure(self.result),self.result['context']['size'],stroke)
  except ValueError as exc:messagebox.showerror('Check biome brush settings',str(exc),parent=self);return
  self.biome_strokes.append(stroke);self.result['biomeStrokes']=self.biome_strokes
  if undo:
   self.biome_undo.append(undo)
   while len(self.biome_undo)>8 or sum(v[4].nbytes for v in self.biome_undo)>128*1024*1024:self.biome_undo.pop(0)
  self.biome_undo_button.configure(state='normal' if self.biome_undo else 'disabled');self.last_stamp=(*p,time.monotonic());self.status.set(f'Biome {stroke["biome"]} painted · {len(self.biome_strokes)} stamps');self.schedule_render()

 def undo_biome(self):
  if self.busy or not self.biome_undo or not self.result:return
  self.biome_undo.pop();self.biome_strokes.pop();self.result['biomeStrokes']=self.biome_strokes
  # Rebuild from current heights so terrain edits made after painting are retained.
  self.result['biomes']=None;self.biome_undo_button.configure(state='normal' if self.biome_undo else 'disabled');self.status.set('Last biome stamp undone');self.render()

 def clear_biomes(self):
  if self.busy:return
  self.biome_strokes=[];self.biome_undo=[];self.biome_undo_button.configure(state='disabled');self.build()

 def open_output(self):
  path=Path(self.output_path.get())
  if path.exists():os.startfile(str(path.resolve().parent))

 def close(self):
  if self.busy:self.close_when_done=True;self.cancel()
  else:self.destroy()

if __name__=='__main__':App().mainloop()

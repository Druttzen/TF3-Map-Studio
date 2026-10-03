"""Windows desktop OSM-to-Lua converter. GPL-3.0."""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from converter import export, export_file, export_new_mod, atomic_write, MOD_ID, validate_bounds
from settings import DEFAULTS, FEATURES, CHOICES, SPECIES, MODELS, MATERIALS, normalize_options
from job import Cancelled
from map_sizes import CUSTOM, SIZES, FORMATS, dimensions, experimental, matching_preset, validate_preset

MODES=['Save Lua map file','Update installed mod','Create standalone mod folder']
APP_VERSION='0.10-preview'
LABELS={
    'forest_spacing':'Forest spacing (m)', 'shrub_spacing':'Shrub spacing (m)',
    'max_generated_trees':'Maximum generated trees / shrubs', 'tree_jitter':'Position variation (0–0.49)',
    'seed':'Random seed (blank = map seed)', 'road_style':'Road style', 'rail_profile':'Track profile',
    'electrification':'Rail electrification', 'high_speed_threshold':'High-speed threshold (km/h)',
    'road_segment_length':'Maximum road segment (m)', 'rail_segment_length':'Maximum rail segment (m)',
    'tunnel_depth':'Estimated tunnel depth (m)', 'object_rotation':'Object rotation (degrees)',
    'import_batch_size':'Scenery items per game batch', 'import_delay':'Delay between game jobs (seconds)',
}


def validate_profile(profile):
    if not isinstance(profile,dict) or profile.get('version')!=1:
        raise ValueError('Choose a version 1 OSM TF3 settings profile.')
    options=normalize_options(profile.get('options'))
    size=profile.get('size')
    bounds=profile.get('bounds')
    if not isinstance(size,list) or len(size)!=2 or any(type(v) not in {int,float} for v in size):
        raise ValueError('Profile map size must contain two numbers.')
    if bounds is not None and (not isinstance(bounds,list) or len(bounds)!=4 or any(type(v) not in {int,float} for v in bounds)):
        raise ValueError('Profile bounds must contain four numbers.')
    validate_bounds(bounds or [-1,-1,1,1],size)
    validate_preset(profile.get('mapPreset'),size)
    if profile.get('mode',MODES[0]) not in MODES: raise ValueError('Unknown output mode in profile.')
    for key in ('source','target'):
        if not isinstance(profile.get(key,''),str): raise ValueError('Profile paths must be text.')
    return {**profile,'options':options}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'OSM → Lua Map · Transport Fever 3 · {APP_VERSION}')
        self.geometry('1080x670'); self.minsize(960,600)
        self.configure(bg='#edf2f4')
        self.events=queue.Queue(); self.busy=False; self.cancel_event=threading.Event()
        self.started=0; self.result=None; self.saved_states=[]; self.close_when_done=False
        self.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(self); style.theme_use('clam')
        for cls in ['TFrame','TLabel','TCheckbutton','TRadiobutton','TLabelframe','TLabelframe.Label']:
            style.configure(cls,background='#edf2f4',foreground='#18333c',font=('Segoe UI',10))
        style.configure('TButton',font=('Segoe UI',10),padding=(10,7))
        style.configure('TNotebook',background='#edf2f4')
        style.configure('TNotebook.Tab',padding=(10,7),font=('Segoe UI',10))
        style.configure('Accent.TButton',background='#087c83',foreground='white')
        style.map('Accent.TButton',background=[('active','#08666d'),('disabled','#b5c6cb')])
        style.configure('Horizontal.TProgressbar',background='#087c83',troughcolor='#d6e3e7')
        header=tk.Frame(self,bg='#163b46',padx=22,pady=13); header.pack(fill='x')
        tk.Label(header,text='OSM → LUA MAP',bg='#163b46',fg='white',font=('Segoe UI',21,'bold')).pack(side='left')
        tk.Label(header,text='TRANSPORT FEVER 3 · PREVIEW 0.10\nVanilla objects · standalone converter',bg='#163b46',fg='#b9dce1',font=('Segoe UI',10),justify='right').pack(side='right')
        body=ttk.Frame(self,padding=(16,12)); body.pack(fill='both',expand=True)
        body.columnconfigure(0,weight=3); body.columnconfigure(1,weight=2); body.rowconfigure(0,weight=1)
        self.book=ttk.Notebook(body); self.book.grid(row=0,column=0,sticky='nsew',padx=(0,12))
        self.pages={name:self.page(name) for name in ['Project','Features','Networks','Vegetation','Vanilla objects','In game']}
        self.source=tk.StringVar(); self.mode=tk.StringVar(value=MODES[0]); self.target=tk.StringVar()
        self.width=tk.StringVar(value='1000'); self.height=tk.StringVar(value='1000')
        self.map_size=tk.StringVar(value=CUSTOM); self.map_format=tk.StringVar(value=FORMATS[0])
        self.map_hint=tk.StringVar(); self.setting_dimensions=False
        self.custom_bounds=tk.BooleanVar(value=False)
        self.bounds=[tk.StringVar() for _ in range(4)]
        self.values={key:tk.StringVar(value=str(value)) for key,value in DEFAULTS.items() if not isinstance(value,(list,dict))}
        self.features={key:tk.BooleanVar(value=True) for key in FEATURES}
        self.species={key:{name:tk.BooleanVar(value=name in DEFAULTS[key]) for name in SPECIES} for key in ['broadleaf_species','conifer_species','shrub_species']}
        self.models={key:tk.StringVar(value=value) for key,value in DEFAULTS['object_models'].items()}
        self.materials={key:tk.StringVar(value=value) for key,value in DEFAULTS['surface_materials'].items()}
        self.build_project(); self.build_features(); self.build_networks(); self.build_vegetation(); self.build_mappings(); self.build_game()
        self.width.trace_add('write',self.dimensions_edited); self.height.trace_add('write',self.dimensions_edited)
        self.update_map_hint()
        side=ttk.Frame(body); side.grid(row=0,column=1,sticky='nsew'); side.rowconfigure(1,weight=1); side.columnconfigure(0,weight=1)
        ttk.Label(side,text='MAP PREVIEW',font=('Segoe UI',11,'bold')).grid(row=0,column=0,sticky='w',pady=(0,8))
        self.results=ttk.Notebook(side); self.results.grid(row=1,column=0,sticky='nsew')
        preview=ttk.Frame(self.results); self.results.add(preview,text='Map')
        self.canvas=tk.Canvas(preview,bg='#f9fbfc',highlightthickness=0); self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda event:self.draw_preview())
        ttk.Label(preview,text='Roads: teal   Rail: orange   Vegetation: green\nPreview uses a sample for large maps.',font=('Segoe UI',9)).pack(anchor='w',pady=6)
        report=ttk.Frame(self.results); self.results.add(report,text='Report')
        self.output=tk.Text(report,wrap='word',bg='white',fg='#18333c',font=('Segoe UI',10),relief='flat',padx=12,pady=12,width=30)
        scrollbar=ttk.Scrollbar(report,command=self.output.yview); self.output.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y'); self.output.pack(fill='both',expand=True)
        self.show('Choose an OSM XML file and your exact TF3 map dimensions. Adjust the tabs, then convert.\n\nSave a Lua dataset directly, update the installed importer, or create a complete standalone mod folder.\n\nOnly vanilla resource references are used. No game assets are bundled.\n\nOSM buildings, functioning towns, rivers and automatic railway signals still require the game tools. PBF files must first be converted to OSM XML.\n\nUse Verify built objects in the game after importing to inspect saved roads, rails and scenery. The fictional sample imports in TF3 build 40408. Large real maps and actual vehicle routes still need testing.')
        footer=ttk.Frame(self,padding=(18,8,18,14)); footer.pack(side='bottom',fill='x',before=body)
        line=ttk.Frame(footer); line.pack(fill='x',pady=(0,8))
        self.status=tk.StringVar(value='Ready to convert'); self.percent=tk.StringVar(value='0%'); self.elapsed=tk.StringVar(value='')
        ttk.Label(line,textvariable=self.status).pack(side='left'); ttk.Label(line,textvariable=self.elapsed).pack(side='right',padx=10); ttk.Label(line,textvariable=self.percent).pack(side='right')
        self.progress=ttk.Progressbar(footer,mode='determinate',maximum=100); self.progress.pack(fill='x',pady=(0,10))
        buttons=ttk.Frame(footer); buttons.pack(fill='x')
        self.convert_button=ttk.Button(buttons,text='Convert map',command=self.convert,style='Accent.TButton'); self.convert_button.pack(side='left')
        self.cancel_button=ttk.Button(buttons,text='Cancel',command=self.cancel,state='disabled'); self.cancel_button.pack(side='left',padx=8)
        self.open_button=ttk.Button(buttons,text='Open output folder',command=self.open_output,state='disabled'); self.open_button.pack(side='left')
        self.profile_buttons=[]
        for text,action in [('Reset settings',self.reset),('Load settings…',self.load_profile),('Save settings…',self.save_profile)]:
            b=ttk.Button(buttons,text=text,command=action); b.pack(side='right',padx=(8,0)); self.profile_buttons.append(b)
        self.after(80,self.poll)

    def page(self,name):
        outer=ttk.Frame(self.book); self.book.add(outer,text=name)
        canvas=tk.Canvas(outer,bg='#edf2f4',highlightthickness=0); bar=ttk.Scrollbar(outer,command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set); bar.pack(side='right',fill='y'); canvas.pack(fill='both',expand=True)
        frame=ttk.Frame(canvas,padding=14); frame.columnconfigure(1,weight=1)
        window=canvas.create_window(0,0,window=frame,anchor='nw')
        frame.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(window,width=event.width))
        def wheel(event):
            if self.book.select()==str(outer) and str(event.widget).startswith(str(outer)+'.'):
                canvas.yview_scroll(int(-event.delta/120),'units')
        outer.bind_all('<MouseWheel>',wheel,add='+')
        return frame

    def note(self,frame,text,row):
        label=ttk.Label(frame,text=text,wraplength=510,font=('Segoe UI',9))
        label.grid(row=row,column=0,columnspan=3,sticky='w',pady=(4,12))
        frame.bind('<Configure>',lambda e:label.configure(wraplength=max(240,e.width-34)),add='+')

    def field(self,frame,row,label,var,choices=None):
        ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=7)
        entry=ttk.Combobox(frame,textvariable=var,values=choices,state='readonly',width=19) if choices else ttk.Entry(frame,textvariable=var,width=20)
        entry.grid(row=row,column=1,columnspan=2,sticky='ew',pady=7)
        return entry

    def path(self,frame,row,label,var,action,extra=None):
        ttk.Label(frame,text=label).grid(row=row,column=0,columnspan=2 if extra else 3,sticky='w',pady=(12,4))
        if extra:ttk.Button(frame,text='Download OSM…',command=extra).grid(row=row,column=2,padx=(8,0),pady=(8,4))
        ttk.Entry(frame,textvariable=var).grid(row=row+1,column=0,columnspan=2,sticky='ew')
        ttk.Button(frame,text='Browse…',command=action).grid(row=row+1,column=2,padx=(8,0))
        frame.columnconfigure(0,weight=1)

    def build_project(self):
        f=self.pages['Project']
        self.path(f,0,'OSM XML file (.osm)',self.source,self.choose_source,self.open_download)
        combo=self.field(f,2,'Output',self.mode,MODES); combo.bind('<<ComboboxSelected>>',self.mode_changed)
        self.path(f,3,'Output file or mod folder',self.target,self.choose_target)
        self.note(f,'Save Lua: dataset + report. Update mod: choose its existing folder. New mod: choose a parent folder; the app creates druttzen_osm_vanilla. Close TF3 before updating its dataset.',5)
        self.size_combo=self.field(f,6,'TF3 map size',self.map_size,[*SIZES,CUSTOM])
        self.size_combo.bind('<<ComboboxSelected>>',self.preset_changed)
        self.format_combo=self.field(f,7,'TF3 map format',self.map_format,FORMATS)
        self.format_combo.bind('<<ComboboxSelected>>',self.preset_changed)
        self.field(f,8,'Map width (metres)',self.width); self.field(f,9,'Map height (metres)',self.height)
        hint=ttk.Label(f,textvariable=self.map_hint,wraplength=510,font=('Segoe UI',9))
        hint.grid(row=10,column=0,columnspan=3,sticky='w',pady=(4,12))
        f.bind('<Configure>',lambda e:hint.configure(wraplength=max(240,e.width-34)),add='+')
        ttk.Checkbutton(f,text='Use custom geographic bounds',variable=self.custom_bounds).grid(row=11,column=0,columnspan=3,sticky='w',pady=6)
        for row,(label,var) in enumerate(zip(['Minimum latitude','Minimum longitude','Maximum latitude','Maximum longitude'],self.bounds),12): self.field(f,row,label,var)
        self.note(f,'With custom bounds off, the converter uses bounds in the OSM file, or derives them from its nodes. Features are clipped at the map edge.',16)

    def preset_changed(self,event=None):
        if self.map_size.get()!=CUSTOM:
            w,h=dimensions(self.map_size.get(),self.map_format.get())
            self.setting_dimensions=True
            try: self.width.set(str(w)); self.height.set(str(h))
            finally: self.setting_dimensions=False
        self.update_map_hint()

    def dimensions_edited(self,*args):
        if not self.setting_dimensions:
            self.map_size.set(CUSTOM)
            self.update_map_hint()

    def update_map_hint(self):
        custom=self.map_size.get()==CUSTOM
        self.format_combo.configure(state='disabled' if custom else 'readonly')
        text=('Enter exact dimensions for an existing map. The demonstration uses 1000 × 1000 metres.' if custom else
              f'{self.map_size.get()} · {self.map_format.get()}: {self.width.get()} × {self.height.get()} metres, width × height.')
        if not custom and experimental(self.map_size.get(),self.map_format.get()):
            text+=' Enable experimentalMapFeatures in TF3 to select this size or format in the game.'
        self.map_hint.set(text+' Bounds fill this rectangle. Dimensions also go into the Lua and report for Heightmap Studio. Editing width or height selects Custom dimensions.')

    def build_features(self):
        f=self.pages['Features']; self.note(f,'Choose what appears in the exported Lua map. Disabled bridges and tunnels are excluded entirely.',0)
        for row,(key,label) in enumerate(FEATURES.items(),1): ttk.Checkbutton(f,text=label,variable=self.features[key]).grid(row=row,column=0,columnspan=3,sticky='w',pady=4)
        self.note(f,'Footpaths use the smallest vanilla road. Place markers carry names; they do not create functioning towns. Building footprints, rivers and signal placement are outside this converter’s current support.',len(FEATURES)+1)

    def build_networks(self):
        f=self.pages['Networks']; self.note(f,'Automatic follows OSM tags. Vanilla profiles approximate lane counts, widths and speeds. One-way and tram roads keep suitable vanilla profiles.',0)
        keys=['road_style','rail_profile','electrification','high_speed_threshold','road_segment_length','rail_segment_length','tunnel_depth']
        for row,key in enumerate(keys,1): self.field(f,row,LABELS[key],self.values[key],CHOICES.get(key))
        self.note(f,'Segment lengths control subdivision, not road speed. Smaller values add detail and increase import time. Tunnel depth is an estimate relative to endpoint terrain. Check grades after importing.',len(keys)+1)

    def build_vegetation(self):
        f=self.pages['Vegetation']; self.note(f,'Spacing controls density. The shared limit applies to generated forest and shrub items; individually tagged trees are separate. The same settings and seed reproduce the same map.',0)
        keys=['forest_spacing','shrub_spacing','max_generated_trees','tree_jitter','seed']
        for row,key in enumerate(keys,1): self.field(f,row,LABELS[key],self.values[key])
        for row,key in enumerate(self.species,6):
            group=ttk.LabelFrame(f,text={'broadleaf_species':'Broadleaf forests','conifer_species':'Conifer forests','shrub_species':'Shrub areas'}[key],padding=8)
            group.grid(row=row,column=0,columnspan=3,sticky='ew',pady=7)
            for i,(name,var) in enumerate(self.species[key].items()): ttk.Checkbutton(group,text=name,variable=var).grid(row=i//4,column=i%4,sticky='w',padx=4,pady=3)
        self.note(f,'Select at least one vanilla species in each palette. A limit of zero disables generated vegetation.',9)

    def build_mappings(self):
        f=self.pages['Vanilla objects']; self.note(f,'Choose a vanilla replacement for each supported OSM object and ground category. These are references to objects already in TF3.',0)
        labels={'tree':'Individual tree','fountain':'Fountain','bollard':'Bollard','advertising_column':'Advertising column'}
        for row,(key,var) in enumerate(self.models.items(),1): self.field(f,row,labels[key],var,list(MODELS))
        self.field(f,5,LABELS['object_rotation'],self.values['object_rotation'])
        for row,(key,var) in enumerate(self.materials.items(),6): self.field(f,row,key.capitalize()+' ground',var,list(MATERIALS))
        self.note(f,'Replacements are decorative. Rotations apply to tagged objects; generated vegetation uses seeded random rotations. No additional mods or copied game assets are required.',9)

    def build_game(self):
        f=self.pages['In game']; self.note(f,'These defaults travel with the dataset and appear in the in-game OSM Import panel. The panel lets you change batch size and pace during an import.',0)
        for row,key in enumerate(['import_batch_size','import_delay'],1): self.field(f,row,LABELS[key],self.values[key])
        self.note(f,'After conversion: enable the standalone mod on a new map, then click OSM Import in the game’s mod button area. Its scroll list contains Check map and resources, Start, Pause, Resume, Retry, Skip, Show progress, Verify built objects, Show place names and Read map size.\n\nVerify built objects reads the saved roads, rails, scenery and markers without building anything. Show place names displays recorded marker names and coordinates. Ground paint appearance and actual vehicle routes still need a map check.\n\nSave Lua mode exports an importer dataset, not a heightmap or a saved game. Copy it to content/osm/dataset.lua in the mod, or use Update installed mod.\n\nThe fictional sample imports in TF3 build 40408. Large real maps and actual vehicle routes still need testing.',3)

    @staticmethod
    def default_target():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam') as key: steam=Path(winreg.QueryValueEx(key,'SteamPath')[0])
            choices=sorted((steam/'userdata').glob('*/3493540/local/mods/'+MOD_ID))
            if len(choices)==1: return str(choices[0])
        except (ImportError,OSError): pass
        return ''

    def choose_source(self):
        path=filedialog.askopenfilename(parent=self,title='Choose OSM XML',filetypes=[('OSM XML','*.osm')])
        if path:
            self.source.set(path)
            if self.mode.get()==MODES[0] and not self.target.get(): self.target.set(str(Path(path).with_suffix('.lua')))

    def open_download(self):
        if self.busy:return
        try:
            size=[float(self.width.get()),float(self.height.get())]
            bounds=[float(var.get()) for var in self.bounds] if self.custom_bounds.get() else None
            validate_bounds(bounds or [-1,-1,1,1],size)
            from map_picker import MapPicker
            preset=None if self.map_size.get()==CUSTOM else {'size':self.map_size.get(),'format':self.map_format.get()}
            MapPicker(self,size,bounds,self.download_complete,preset)
        except (ValueError,OSError) as exc:messagebox.showerror('Check map area',str(exc),parent=self)

    def download_complete(self,result,preset):
        self.setting_dimensions=True
        try:self.width.set(str(result['mapSize'][0]));self.height.set(str(result['mapSize'][1]))
        finally:self.setting_dimensions=False
        self.map_size.set(preset['size'] if preset else CUSTOM);self.map_format.set(preset['format'] if preset else FORMATS[0]);self.update_map_hint()
        self.custom_bounds.set(True)
        for var,value in zip(self.bounds,result['bounds']):var.set(format(value,'.17g'))
        self.source.set(result['output'])
        if self.mode.get()==MODES[0] and not self.target.get():self.target.set(str(Path(result['output']).with_suffix('.lua')))
        self.result=None;self.draw_preview();self.open_button.configure(state='disabled')
        self.status.set('OSM downloaded · exact yellow-frame bounds selected · ready to convert')
        counts=result['counts']
        self.show(f"Downloaded OSM XML:\n{result['output']}\n\nMap overview PNG:\n{result.get('overview', 'Unavailable')}\n\nDownload log:\n{result['log']}\n\n{counts['nodes']:,} nodes · {counts['ways']:,} ways · {counts['relations']:,} relations\n\nThe locked yellow-frame bounds and chosen TF3 size are selected for conversion. Heightmap Studio receives the same bounds and size through the converted Lua and JSON report.\n\n© OpenStreetMap contributors · ODbL\nhttps://www.openstreetmap.org/copyright\n\nComplete referenced geometry can extend outside the frame; conversion clips it to the selection.")

    def choose_target(self):
        if self.mode.get()==MODES[0]: path=filedialog.asksaveasfilename(parent=self,title='Save Lua map',defaultextension='.lua',filetypes=[('Lua map','*.lua')])
        else:
            path=filedialog.askdirectory(parent=self,title='Choose existing mod folder' if self.mode.get()==MODES[1] else 'Choose parent folder for the new mod')
            if path and self.mode.get()==MODES[2]: path=str(Path(path)/MOD_ID)
        if path: self.target.set(path)

    def mode_changed(self,event=None):
        self.target.set(self.default_target() if self.mode.get()==MODES[1] else str(Path(self.source.get()).with_suffix('.lua')) if self.mode.get()==MODES[0] and self.source.get() else '')

    def settings(self):
        options={key:var.get() for key,var in self.values.items()}
        for key in options:
            if key not in CHOICES and key!='seed':
                try: options[key]=float(options[key])
                except ValueError: raise ValueError(LABELS[key]+' must be a number.')
        options['features']={key:var.get() for key,var in self.features.items()}
        options.update({key:[name for name,var in palette.items() if var.get()] for key,palette in self.species.items()})
        options['object_models']={key:var.get() for key,var in self.models.items()}
        options['surface_materials']={key:var.get() for key,var in self.materials.items()}
        return normalize_options(options)

    def profile(self):
        try:
            size=[float(self.width.get()),float(self.height.get())]
            bounds=[float(var.get()) for var in self.bounds] if self.custom_bounds.get() else None
        except ValueError: raise ValueError('Map dimensions and custom bounds must be numbers.')
        preset=None if self.map_size.get()==CUSTOM else {'size':self.map_size.get(),'format':self.map_format.get()}
        return validate_profile({'version':1,'options':self.settings(),'size':size,'mapPreset':preset,'bounds':bounds,'source':self.source.get().strip(),'target':self.target.get().strip(),'mode':self.mode.get()})

    def apply_profile(self,profile):
        p=validate_profile(profile); options=p['options']
        for key,var in self.values.items(): var.set(str(options[key]))
        for key,var in self.features.items(): var.set(options['features'][key])
        for key,palette in self.species.items():
            for name,var in palette.items(): var.set(name in options[key])
        for key,var in self.models.items(): var.set(options['object_models'][key])
        for key,var in self.materials.items(): var.set(options['surface_materials'][key])
        self.setting_dimensions=True
        try: self.width.set(str(p['size'][0])); self.height.set(str(p['size'][1]))
        finally: self.setting_dimensions=False
        preset=p.get('mapPreset') if 'mapPreset' in p else matching_preset(p['size'])
        self.map_size.set(preset['size'] if preset else CUSTOM); self.map_format.set(preset['format'] if preset else FORMATS[0])
        self.update_map_hint(); self.custom_bounds.set(p.get('bounds') is not None)
        for var,value in zip(self.bounds,p.get('bounds') or ['']*4): var.set(str(value))
        self.source.set(p.get('source','')); self.target.set(p.get('target','')); self.mode.set(p.get('mode',MODES[0]))

    def reset(self):
        self.apply_profile({'version':1,'options':deepcopy(DEFAULTS),'size':[1000,1000],'bounds':None,'source':self.source.get(),'target':self.target.get(),'mode':self.mode.get()})
        self.status.set('Conversion settings reset to defaults')

    def save_profile(self):
        try:
            profile=self.profile()
            path=filedialog.asksaveasfilename(parent=self,title='Save converter settings',defaultextension='.json',filetypes=[('Settings profile','*.json')])
            if path: atomic_write(path,json.dumps(profile,indent=2,ensure_ascii=False)+'\n'); self.status.set('Settings saved')
        except (ValueError,OSError) as exc: messagebox.showerror('Could not save settings',str(exc),parent=self)

    def load_profile(self):
        path=filedialog.askopenfilename(parent=self,title='Load converter settings',filetypes=[('Settings profile','*.json')])
        if not path: return
        try: self.apply_profile(json.loads(Path(path).read_text(encoding='utf-8-sig'))); self.status.set('Settings loaded')
        except (ValueError,OSError) as exc: messagebox.showerror('Could not load settings',str(exc),parent=self)

    def freeze(self,enabled):
        if enabled:
            self.saved_states=[]
            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child,(ttk.Entry,ttk.Combobox,ttk.Checkbutton,ttk.Button)):
                        self.saved_states.append((child,str(child.cget('state')))); child.configure(state='disabled')
                    walk(child)
            walk(self.book)
            for button in self.profile_buttons: button.configure(state='disabled')
        else:
            for widget,state in self.saved_states: widget.configure(state=state)
            for button in self.profile_buttons: button.configure(state='normal')
        self.convert_button.configure(state='disabled' if enabled else 'normal')
        self.cancel_button.configure(state='normal' if enabled else 'disabled')
        self.open_button.configure(state='normal' if not enabled and self.result else 'disabled')

    def convert(self):
        if self.busy: return
        try:
            p=self.profile()
            if not p['source'] or not Path(p['source']).is_file(): raise ValueError('Choose an existing .osm file first.')
            if not p['target']: raise ValueError('Choose an output file or folder first.')
            action={MODES[0]:export_file,MODES[1]:export,MODES[2]:export_new_mod}[p['mode']]
        except ValueError as exc: messagebox.showerror('Check settings',str(exc),parent=self); return
        self.busy=True; self.close_when_done=False; self.cancel_event.clear(); self.started=time.monotonic(); self.result=None
        self.freeze(True); self.progress['value']=0; self.percent.set('0%'); self.status.set('Starting conversion…')
        self.show('Preparing the selected map…'); self.draw_preview()
        def progress(percent,stage,detail): self.events.put(('progress',(percent,stage,detail)))
        def worker():
            try: self.events.put(('ok',action(p['source'],p['target'],p['bounds'],p['size'],options=p['options'],progress=progress,cancel=self.cancel_event)))
            except Cancelled as exc: self.events.put(('cancelled',str(exc)))
            except Exception as exc: self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def cancel(self):
        self.cancel_event.set(); self.cancel_button.configure(state='disabled'); self.status.set('Cancelling… keeping existing output files')

    def poll(self):
        if self.busy:
            seconds=int(time.monotonic()-self.started); self.elapsed.set(f'{seconds//60:02d}:{seconds%60:02d}')
        while True:
            try: kind,result=self.events.get_nowait()
            except queue.Empty: break
            if kind=='progress':
                percent,stage,detail=result; self.progress['value']=percent; self.percent.set(f'{percent:.0f}%')
                if not self.cancel_event.is_set(): self.status.set(stage+(' · '+detail if detail else ''))
                if percent>=98: self.cancel_button.configure(state='disabled')
                continue
            self.busy=False
            if kind=='ok':
                self.result=result; self.progress['value']=100; self.percent.set('100%'); self.status.set('Map exported successfully')
                self.show(f"{result['edges']:,} road / rail segments\n{result['sceneryItems']:,} scenery items\n{result['placeLabels']:,} named markers\n\nSaved Lua:\n{result['output']}\n\nSaved report:\n{result['report']}\n\nDataset: {result['dataset']}\n\n"+('Notes:\n'+'\n\n'.join(result['warnings']) if result['warnings'] else 'No conversion warnings.'))
                self.draw_preview()
            else:
                self.status.set('Conversion cancelled' if kind=='cancelled' else 'Conversion failed — check the report')
                self.show(result); self.results.select(1)
            self.freeze(False)
            if self.close_when_done: self.destroy(); return
        self.after(80,self.poll)

    def show(self,text):
        self.output.configure(state='normal'); self.output.delete('1.0','end'); self.output.insert('1.0',text); self.output.configure(state='disabled')

    def draw_preview(self):
        if not hasattr(self,'canvas'): return
        self.canvas.delete('all'); width=self.canvas.winfo_width(); height=self.canvas.winfo_height()
        if width<10 or height<10: return
        if not self.result:
            self.canvas.create_text(width/2,height/2,text='Your map appears here\nafter conversion',fill='#6c8c95',font=('Segoe UI',12),justify='center'); return
        data=self.result['_preview']; w,h=data['size']; scale=min((width-28)/w,(height-28)/h)
        def point(p): return width/2+p[0]*scale,height/2-p[1]*scale
        self.canvas.create_rectangle(*point([-w/2,h/2]),*point([w/2,-h/2]),fill='#edf4ee',outline='#b5c9c2')
        for item in data['scenery']:
            if 'face' in item: self.canvas.create_polygon(*[n for p in item['face'] for n in point(p)],fill='#d6dadd',outline='')
            elif 'pos' in item:
                x,y=point(item['pos']); self.canvas.create_oval(x-1.5,y-1.5,x+1.5,y+1.5,fill='#65985d' if item.get('category')=='vegetation' else '#496173',outline='')
        for edge in data['edges']:
            a=data['nodes'][edge['node0']]['pos']; b=data['nodes'][edge['node1']]['pos']
            self.canvas.create_line(*point(a),*point(b),fill='#d5843e' if edge['kind']=='TRACK' else '#087c83',width=2)
        for label in data['labels']: self.canvas.create_text(*point(label['pos']),text=label['name'],fill='#18333c',font=('Segoe UI',8))
        if data.get('limited'): self.canvas.create_text(8,8,text='Sample preview',anchor='nw',fill='#6c8c95',font=('Segoe UI',9))

    def open_output(self):
        if self.result: os.startfile(str(Path(self.result['output']).parent))

    def close(self):
        if self.busy: self.close_when_done=True; self.cancel()
        else: self.destroy()


if __name__=='__main__': App().mainloop()

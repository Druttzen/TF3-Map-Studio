"""Native map area picker with a movable yellow TF3-size frame. GPL-3.0."""
from collections import OrderedDict
import io
import math
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import webbrowser
from PIL import Image,ImageTk
from job import Cancelled
from map_sizes import CUSTOM,SIZES,FORMATS,dimensions,matching_preset
from osm_download import Selection,TileCache,TILES,OVERPASS,download,pixel,pixel_geographic,mercator,geographic,fit_zoom,visible_tiles

class MapPicker(tk.Toplevel):
    def __init__(self,parent,size,bounds,on_done,preset=None):
        super().__init__(parent)
        self.title('Download OpenStreetMap · TF3 area');self.geometry('1000x650');self.minsize(900,600)
        self.transient(parent);self.protocol('WM_DELETE_WINDOW',self.close)
        self.on_done=on_done;self.busy=False;self.pending_download=None;self.close_when_done=False;self.cancel_event=threading.Event()
        self.stop=threading.Event();self.events=queue.Queue();self.tile_jobs=queue.Queue(maxsize=1);self.generation=0
        self.images=OrderedDict();self.photos=[];self.drag_start=None;self.dragged=False;self.resize_timer=None;self.ignore_dimensions=False;self.dimensions_valid=True
        center=(59.3293,18.0686)
        coverage=1
        if bounds:
            a,b=mercator(bounds[0],bounds[1]);c,d=mercator(bounds[2],bounds[3]);center=geographic((a+c)/2,(b+d)/2)
            coverage=max(.01,min(100,(c-a)*math.cos(math.radians(center[0]))/size[0]))
        self.selection=Selection(size,center,coverage);self.view_center=center;self.zoom=14
        self.width=tk.StringVar(value=str(size[0]));self.height=tk.StringVar(value=str(size[1]))
        preset=preset or matching_preset(size)
        self.map_size=tk.StringVar(value=preset['size'] if preset else CUSTOM);self.map_format=tk.StringVar(value=preset['format'] if preset else FORMATS[0])
        self.coverage=tk.StringVar(value=format(coverage,'.6g'));self.latitude=tk.StringVar(value=format(center[0],'.7f'));self.longitude=tk.StringVar(value=format(center[1],'.7f'))
        self.endpoint=tk.StringVar(value=OVERPASS);self.status=tk.StringVar(value='Move the yellow frame, then click to lock its coordinates.')
        self.bounds_text=tk.StringVar();self.map_status=tk.StringVar(value='Loading visible map tiles…');self.progress_mode=None
        header=tk.Frame(self,bg='#163b46',padx=18,pady=10);header.pack(fill='x')
        tk.Label(header,text='DOWNLOAD OPENSTREETMAP',bg='#163b46',fg='white',font=('Segoe UI',16,'bold')).pack(anchor='w')
        tk.Label(header,text='Move the yellow frame · click to lock · save OSM XML + overview PNG',bg='#163b46',fg='#b9dce1',font=('Segoe UI',10)).pack(anchor='w')
        footer=ttk.Frame(self,padding=(14,7));footer.pack(side='bottom',fill='x')
        ttk.Label(footer,textvariable=self.status,wraplength=960).pack(anchor='w')
        self.progress=ttk.Progressbar(footer,maximum=100);self.progress.pack(fill='x',pady=5)
        buttons=ttk.Frame(footer);buttons.pack(fill='x')
        self.download_button=ttk.Button(buttons,text='Download locked area…',style='Accent.TButton',command=self.start_download,state='disabled');self.download_button.pack(side='left')
        self.cancel_button=ttk.Button(buttons,text='Cancel download',command=self.cancel,state='disabled');self.cancel_button.pack(side='left',padx=8)
        self.close_button=ttk.Button(buttons,text='Close',command=self.close);self.close_button.pack(side='right')
        body=ttk.Frame(self,padding=(14,10));body.pack(fill='both',expand=True)
        self.controls=ttk.Frame(body);self.controls.pack(side='left',fill='y',padx=(0,12))
        self.controls.columnconfigure(1,weight=1)
        def field(row,label,var,choices=None):
            ttk.Label(self.controls,text=label,font=('Segoe UI',9)).grid(row=row,column=0,sticky='w',padx=(0,7),pady=3)
            widget=ttk.Combobox(self.controls,textvariable=var,values=choices,state='readonly',width=17) if choices else ttk.Entry(self.controls,textvariable=var,width=19)
            widget.grid(row=row,column=1,sticky='ew',pady=3);return widget
        combo=field(0,'TF3 size',self.map_size,[*SIZES,CUSTOM]);combo.bind('<<ComboboxSelected>>',self.preset_changed)
        self.format_combo=field(1,'Format',self.map_format,FORMATS);self.format_combo.bind('<<ComboboxSelected>>',self.preset_changed)
        field(2,'Width (m)',self.width);field(3,'Height (m)',self.height);field(4,'Area scale ×',self.coverage)
        note=ttk.Label(self.controls,text='1×: ground size at the frame centre.\nOther scales stretch that area into TF3.',font=('Segoe UI',9),wraplength=290);note.grid(row=5,column=0,columnspan=2,sticky='w',pady=5)
        field(6,'Latitude',self.latitude);field(7,'Longitude',self.longitude)
        self.go_button=ttk.Button(self.controls,text='Go to coordinates',command=self.go);self.go_button.grid(row=8,column=0,columnspan=2,sticky='ew',pady=5)
        actions=ttk.Frame(self.controls);actions.grid(row=9,column=0,columnspan=2,sticky='ew')
        self.unlock_button=ttk.Button(actions,text='Move frame',command=self.unlock);self.unlock_button.pack(side='left',fill='x',expand=True)
        self.fit_button=ttk.Button(actions,text='Fit frame',command=self.fit);self.fit_button.pack(side='left',fill='x',expand=True,padx=(4,0))
        ttk.Label(self.controls,textvariable=self.bounds_text,wraplength=290,font=('Segoe UI',9),justify='left').grid(row=10,column=0,columnspan=2,sticky='w',pady=9)
        ttk.Label(self.controls,text='OSM data service (HTTPS)',font=('Segoe UI',9)).grid(row=11,column=0,columnspan=2,sticky='w')
        ttk.Entry(self.controls,textvariable=self.endpoint,width=34).grid(row=12,column=0,columnspan=2,sticky='ew',pady=4)
        ttk.Label(self.controls,text='Conversion clips to the yellow frame.',font=('Segoe UI',9),wraplength=290).grid(row=13,column=0,columnspan=2,sticky='w',pady=4)
        map_area=ttk.Frame(body);map_area.pack(side='left',fill='both',expand=True)
        toolbar=ttk.Frame(map_area);toolbar.pack(fill='x',pady=(0,5))
        ttk.Button(toolbar,text='−',width=3,command=lambda:self.change_zoom(-1)).pack(side='left')
        ttk.Button(toolbar,text='+',width=3,command=lambda:self.change_zoom(1)).pack(side='left',padx=5)
        ttk.Label(toolbar,text='Drag to pan · wheel to zoom',font=('Segoe UI',9)).pack(side='left',padx=5)
        self.canvas=tk.Canvas(map_area,bg='#dce8e7',highlightthickness=0,cursor='crosshair');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self.configure_map);self.canvas.bind('<Motion>',self.move_frame)
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.pan);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<MouseWheel>',self.wheel)
        credit=ttk.Label(map_area,text='© OpenStreetMap contributors · ODbL',font=('Segoe UI',9),cursor='hand2');credit.pack(anchor='e',pady=(4,0))
        credit.bind('<Button-1>',lambda e:webbrowser.open('https://www.openstreetmap.org/copyright'))
        ttk.Label(map_area,textvariable=self.map_status,font=('Segoe UI',9),wraplength=620).pack(anchor='w')
        for var in (self.width,self.height,self.coverage):var.trace_add('write',self.dimensions_changed)
        cache=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Druttzen/OSM-TF3/map-tiles'
        self.cache=TileCache(cache,os.environ.get('OSM_TF3_TILE_URL',TILES))
        threading.Thread(target=self.tile_worker,daemon=True).start()
        self.saved_states=[];self.update_frame();self.after(100,self.fit);self.after(80,self.poll);self.grab_set()

    def preset_changed(self,event=None):
        if self.busy:return
        if self.map_size.get()!=CUSTOM:
            w,h=dimensions(self.map_size.get(),self.map_format.get());self.ignore_dimensions=True
            try:self.width.set(str(w));self.height.set(str(h))
            finally:self.ignore_dimensions=False
        self.apply_dimensions()

    def dimensions_changed(self,*args):
        if self.ignore_dimensions or self.busy:return
        self.dimensions_valid=False;self.selection.unlock();self.update_frame()
        if args[0] in (str(self.width),str(self.height)):self.map_size.set(CUSTOM)
        if self.resize_timer:self.after_cancel(self.resize_timer)
        self.resize_timer=self.after(250,self.apply_dimensions)

    def apply_dimensions(self):
        self.resize_timer=None
        try:self.selection.resize((float(self.width.get()),float(self.height.get())),float(self.coverage.get()))
        except ValueError as exc:self.dimensions_valid=False;self.status.set(str(exc));self.download_button.configure(state='disabled');return
        self.dimensions_valid=True
        self.format_combo.configure(state='disabled' if self.map_size.get()==CUSTOM else 'readonly')
        self.status.set('Size changed. Move the frame and click to lock the area again.');self.update_frame();self.fit()

    def point(self,x,y):
        cx,cy=pixel(*self.view_center,self.zoom)
        return pixel_geographic(cx+x-self.canvas.winfo_width()/2,cy+y-self.canvas.winfo_height()/2,self.zoom)

    def screen(self,lat,lon):
        x,y=pixel(lat,lon,self.zoom);cx,cy=pixel(*self.view_center,self.zoom)
        return x-cx+self.canvas.winfo_width()/2,y-cy+self.canvas.winfo_height()/2

    def configure_map(self,event):
        self.render()

    def fit(self):
        if self.busy:return
        self.view_center=self.selection.center;self.zoom=fit_zoom(self.selection.bounds,self.canvas.winfo_width(),self.canvas.winfo_height());self.render()

    def go(self):
        if self.busy:return
        try:
            center=(float(self.latitude.get()),float(self.longitude.get()));self.selection.unlock();self.selection.move(center)
        except ValueError as exc:self.status.set(str(exc));self.update_frame();return
        self.fit();self.status.set('Coordinates selected. Click the map to lock the yellow frame.');self.update_frame()

    def unlock(self):
        if self.busy:return
        self.selection.unlock();self.status.set('Move the yellow frame, then click to lock its coordinates.');self.update_frame()

    def move_frame(self,event):
        if self.busy or self.drag_start is not None or self.selection.locked:return
        try:self.selection.move(self.point(event.x,event.y))
        except ValueError as exc:self.status.set(str(exc));self.download_button.configure(state='disabled');return
        self.update_frame()

    def press(self,event):
        if self.busy:return
        self.drag_start=(event.x,event.y,self.view_center);self.dragged=False

    def pan(self,event):
        if self.busy or self.drag_start is None:return
        x,y,center=self.drag_start
        if math.hypot(event.x-x,event.y-y)>5:self.dragged=True
        if not self.dragged:return
        cx,cy=pixel(*center,self.zoom)
        lat,lon=pixel_geographic(cx+x-event.x,cy+y-event.y,self.zoom)
        self.view_center=(max(-84.9,min(84.9,lat)),max(-179.9,min(179.9,lon)));self.render(fetch=False)

    def release(self,event):
        if self.busy or self.drag_start is None:return
        dragged=self.dragged;self.drag_start=None
        if dragged:self.render();return
        if not self.dimensions_valid:return
        try:self.selection.lock(self.point(event.x,event.y))
        except ValueError as exc:self.status.set(str(exc));return
        self.latitude.set(format(self.selection.center[0],'.7f'));self.longitude.set(format(self.selection.center[1],'.7f'))
        self.status.set('Area locked. Download saves OSM XML, an overview PNG and the coordinate log.');self.update_frame()

    def wheel(self,event):self.change_zoom(1 if event.delta>0 else -1,(event.x,event.y))

    def change_zoom(self,delta,anchor=None):
        if self.busy:return
        zoom=max(2,min(19,self.zoom+delta))
        if zoom==self.zoom:return
        anchor=anchor or (self.canvas.winfo_width()/2,self.canvas.winfo_height()/2)
        lat,lon=self.point(*anchor);self.zoom=zoom
        cx,cy=pixel(lat,lon,zoom)
        lat,lon=pixel_geographic(cx-anchor[0]+self.canvas.winfo_width()/2,cy-anchor[1]+self.canvas.winfo_height()/2,zoom)
        self.view_center=(max(-84.9,min(84.9,lat)),max(-179.9,min(179.9,lon)))
        self.render()

    def update_frame(self):
        self.canvas.delete('frame')
        s,w,n,e=self.selection.bounds
        x,y=self.screen(n,w);xx,yy=self.screen(s,e)
        self.canvas.create_rectangle(x,y,xx,yy,outline='#334139',width=7,tags='frame')
        self.canvas.create_rectangle(x,y,xx,yy,outline='#ffdb00',width=4,tags='frame')
        label=('LOCKED' if self.selection.locked else 'CLICK TO LOCK')+f' · {self.selection.size[0]:g} × {self.selection.size[1]:g} m'
        lx=max(8,min(self.canvas.winfo_width()-15,x));ly=max(8,min(self.canvas.winfo_height()-30,y))
        text=self.canvas.create_text(lx+4,ly+3,text=label,fill='#18333c',anchor='nw',font=('Segoe UI',9,'bold'),tags='frame')
        a,b,c,d=self.canvas.bbox(text)
        self.canvas.create_rectangle(a-3,b-2,c+3,d+2,fill='#ffdb00',outline='',tags='frame');self.canvas.tag_raise(text)
        self.bounds_text.set(f"{'Locked area' if self.selection.locked else 'Moving frame'} · WGS84\nSouth {s:.7f} · West {w:.7f}\nNorth {n:.7f} · East {e:.7f}")
        self.download_button.configure(state='normal' if self.selection.locked and self.dimensions_valid and not self.busy else 'disabled')

    def render(self,fetch=True):
        if not self.winfo_exists():return
        self.canvas.delete('tile');self.photos=[]
        tiles=visible_tiles(self.view_center,self.zoom,self.canvas.winfo_width(),self.canvas.winfo_height());missing=[]
        for z,x,y,px,py in tiles:
            data=self.images.get((z,x,y))
            if data:
                photo=ImageTk.PhotoImage(Image.open(io.BytesIO(data)),master=self.canvas);self.photos.append(photo)
                self.canvas.create_image(px,py,image=photo,anchor='nw',tags='tile')
            else:
                self.canvas.create_rectangle(px,py,px+256,py+256,outline='#c2d0cf',tags='tile');missing.append((z,x,y))
        self.canvas.tag_lower('tile');self.update_frame()
        if fetch:
            self.generation+=1
            try:self.tile_jobs.get_nowait()
            except queue.Empty:pass
            self.tile_jobs.put_nowait((self.generation,missing))
            self.map_status.set('Loading visible map tiles…' if missing else 'OpenStreetMap · yellow frame is the download boundary')

    def tile_worker(self):
        while not self.stop.is_set():
            try:generation,tiles=self.tile_jobs.get(timeout=.2)
            except queue.Empty:continue
            for key in tiles:
                if self.stop.is_set() or generation!=self.generation:break
                try:self.events.put(('tile',(generation,key,self.cache.get(*key,cancel=self.stop))))
                except Cancelled:return
                except Exception:self.events.put(('tile_error',(generation,'Map tiles unavailable. Check the connection; the yellow frame and coordinates still work.')));break
            else:self.events.put(('tiles_done',generation))

    def freeze(self,enabled):
        if enabled:
            self.saved_states=[]
            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child,(ttk.Entry,ttk.Combobox,ttk.Button)):
                        self.saved_states.append((child,str(child.cget('state'))));child.configure(state='disabled')
                    walk(child)
            walk(self.controls)
        else:
            for widget,state in self.saved_states:widget.configure(state=state)
        self.cancel_button.configure(state='normal' if enabled else 'disabled');self.update_frame()

    def start_download(self):
        if self.busy or not self.selection.locked or not self.dimensions_valid:return
        # Pending dimension edits must never use a stale locked rectangle.
        if self.resize_timer:self.after_cancel(self.resize_timer);self.apply_dimensions();return
        target=filedialog.asksaveasfilename(parent=self,title='Save selected OSM XML',defaultextension='.osm',filetypes=[('OSM XML','*.osm')],initialfile='selected-map.osm')
        if not target:return
        bounds=list(self.selection.bounds);size=list(self.selection.size);coverage=self.selection.coverage;endpoint=self.endpoint.get().strip()
        preset=None if self.map_size.get()==CUSTOM else {'size':self.map_size.get(),'format':self.map_format.get()}
        # Show the entire selected area; only this visible viewport is fetched.
        self.fit()
        self.pending_download=(bounds,size,target,endpoint,coverage,preset)
        self.busy=True;self.cancel_event.clear();self.freeze(True)
        self.status.set('Preparing overview · waiting for the visible map tiles…')
        self.progress.configure(mode='indeterminate');self.progress.start(12);self.progress_mode='indeterminate'
        self.begin_ready_download()

    def begin_ready_download(self):
        if self.pending_download is None:return
        width,height=self.canvas.winfo_width(),self.canvas.winfo_height()
        keys=[(z,x,y) for z,x,y,_,_ in visible_tiles(self.view_center,self.zoom,width,height)]
        if any(key not in self.images for key in keys):return
        bounds,size,target,endpoint,coverage,preset=self.pending_download;self.pending_download=None
        overview={'size':(width,height),'center':tuple(self.view_center),'zoom':self.zoom,'tiles':{key:self.images[key] for key in keys}}
        def progress(p,stage,detail):self.events.put(('progress',(p,stage,detail)))
        def worker():
            try:self.events.put(('ok',(download(bounds,size,target,endpoint,coverage,progress,self.cancel_event,overview=overview),preset)))
            except Cancelled as exc:self.events.put(('cancelled',str(exc)))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def cancel(self):
        self.cancel_event.set();self.cancel_button.configure(state='disabled');self.status.set('Cancelling download… existing files are kept.')
        if self.pending_download is not None:
            self.pending_download=None;self.events.put(('cancelled','Download cancelled. Existing files were kept.'))

    def poll(self):
        while True:
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='tile':
                generation,key,data=value;self.images[key]=data
                while len(self.images)>128:self.images.popitem(last=False)
                if generation==self.generation:self.render(fetch=False)
            elif kind=='tile_error':
                generation,text=value
                if generation==self.generation:
                    self.map_status.set(text)
                    if self.pending_download is not None:
                        self.pending_download=None;self.events.put(('error','Could not load the map overview. Check the connection and retry the download. Existing files were kept.'))
            elif kind=='tiles_done':
                if value==self.generation:self.map_status.set('OpenStreetMap · yellow frame is the download boundary')
            elif kind=='progress':
                p,stage,detail=value
                if p is None:
                    if self.progress_mode!='indeterminate':self.progress.configure(mode='indeterminate');self.progress.start(12);self.progress_mode='indeterminate'
                else:
                    self.progress.stop();self.progress.configure(mode='determinate',value=p);self.progress_mode='determinate'
                    if p>=98:self.cancel_button.configure(state='disabled')
                if not self.cancel_event.is_set():self.status.set(stage+(' · '+detail if detail else ''))
            else:
                self.busy=False;self.progress.stop();self.freeze(False)
                if kind=='ok':
                    result,preset=value;self.on_done(result,preset)
                    self.status.set('OSM XML, overview PNG and download log saved. Close this view to convert the selected file.');self.progress.configure(mode='determinate',value=100)
                else:
                    self.status.set(value)
                    if kind=='error':messagebox.showerror('OSM download failed',value,parent=self)
                if self.close_when_done:self.close();return
        self.begin_ready_download()
        self.after(80,self.poll)

    def close(self):
        if self.busy:self.close_when_done=True;self.cancel();return
        self.stop.set();self.grab_release();self.destroy()

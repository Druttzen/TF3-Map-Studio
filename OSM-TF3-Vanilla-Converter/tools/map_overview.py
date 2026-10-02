"""Export the displayed OSM viewport without fetching extra tiles. GPL-3.0."""
import io
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,PngImagePlugin
from osm_download import pixel,pixel_geographic,visible_tiles,check

HEADER=100
FOOTER=54

def save_overview(target,bounds,size,snapshot,cancel=None):
    width,height=snapshot['size'];center=snapshot['center'];zoom=snapshot['zoom']
    if not (200<=width<=10000 and 100<=height<=10000):
        raise ValueError('The map overview viewport has invalid dimensions.')
    cx,cy=pixel(*center,zoom)
    def point(lat,lon):
        x,y=pixel(lat,lon,zoom)
        return round(x-cx+width/2),round(y-cy+height/2)
    s,w,n,e=bounds;x,y=point(n,w);xx,yy=point(s,e)
    if not (0<=x<xx<width and 0<=y<yy<height):
        raise ValueError('Fit the entire yellow frame into the map before saving its overview.')
    canvas=Image.new('RGB',(width,height),'#dce8e7')
    for z,tx,ty,px,py in visible_tiles(center,zoom,width,height):
        check(cancel)
        data=snapshot['tiles'].get((z,tx,ty))
        if data is None:raise ValueError('Map tiles are still loading. The overview was not saved.')
        with Image.open(io.BytesIO(data)) as tile:
            if tile.format!='PNG' or tile.size!=(256,256):raise ValueError('Invalid overview map tile.')
            canvas.paste(tile.convert('RGB'),(round(px),round(py)))
    draw=ImageDraw.Draw(canvas)
    draw.rectangle((x,y,xx,yy),outline='#334139',width=7)
    draw.rectangle((x+1,y+1,xx-1,yy-1),outline='#ffdb00',width=4)
    def font(size,bold=False):
        try:return ImageFont.truetype(str(Path('C:/Windows/Fonts')/('segoeuib.ttf' if bold else 'segoeui.ttf')),size)
        except OSError:return ImageFont.load_default(size=size)
    label='LOCKED AREA'
    draw.rectangle((x+5,y+5,x+116,y+26),fill='#ffdb00')
    draw.text((x+9,y+6),label,fill='#18333c',font=font(13,True))
    result=Image.new('RGB',(width,height+HEADER+FOOTER),'#163b46')
    result.paste(canvas,(0,HEADER));draw=ImageDraw.Draw(result)
    lines=[('OPENSTREETMAP · TF3 MAP OVERVIEW',16,True),
           (f'TF3 map: {size[0]:g} × {size[1]:g} m · Yellow frame: downloaded area',12,False),
           (f'South {s:.7f} · West {w:.7f}',12,False),
           (f'North {n:.7f} · East {e:.7f}',12,False)]
    for index,(text,fs,bold) in enumerate(lines):
        if draw.textlength(text,font=font(fs,bold))>width-24:
            fs=10
        draw.text((12,8 if bold else 35+19*(index-1)),text,fill='white',font=font(fs,bold))
    draw.text((12,HEADER+height+7),'© OpenStreetMap contributors · ODbL 1.0',fill='white',font=font(12))
    draw.text((12,HEADER+height+27),'https://www.openstreetmap.org/copyright',fill='#b9dce1',font=font(12))
    north,west=pixel_geographic(cx-width/2,cy-height/2,zoom)
    south,east=pixel_geographic(cx+width/2,cy+height/2,zoom)
    metadata={'bounds':list(bounds),'mapSize':list(size),'pixels':list(result.size),'viewportBounds':[south,west,north,east],'zoom':zoom,'framePixels':[x,y+HEADER,xx,yy+HEADER],'attribution':'© OpenStreetMap contributors','copyrightUrl':'https://www.openstreetmap.org/copyright'}
    info=PngImagePlugin.PngInfo();info.add_text('TF3 Map Overview',json.dumps(metadata,ensure_ascii=False))
    check(cancel);result.save(target,format='PNG',pnginfo=info)
    return metadata

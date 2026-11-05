"""Exercise a frozen app with fictional local data; never contact providers."""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import ssl
import sys
import tempfile


def check(output):
    result={'ok':False}
    try:
        import tkinter
        from PIL import Image
        from converter import export_file,export_new_mod,export,template_folder
        from osm_download import download
        tls=ssl.create_default_context()
        assert tls.cert_store_stats()['x509_ca']>0
        tcl=tkinter.Tcl().call('info','patchlevel')
        if getattr(sys,'frozen',False):
            from tkinter import ttk
            window=tkinter.Tk();window.withdraw()
            try:ttk.Style(window).theme_use('clam');window.update_idletasks()
            finally:window.destroy()
        with closing(sqlite3.connect(':memory:')) as database:
            assert database.execute('SELECT 1').fetchone()==(1,)
        with tempfile.TemporaryDirectory(prefix='osm-tf3-runtime-') as folder:
            folder=Path(folder)
            xml=folder/'fictional.osm'
            xml.write_text('<osm version="0.6"><bounds minlat="0" minlon="0" maxlat=".01" maxlon=".01"/><node id="1" lat=".002" lon=".002"/><node id="2" lat=".008" lon=".008"/><way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>',encoding='utf-8')
            report=export_file(xml,folder/'fictional.lua',None,[1000,1000])
            assert report['edges']>0
            assert report['sourceSha256']==hashlib.sha256(xml.read_bytes()).hexdigest()
            assert report['luaSha256']==hashlib.sha256((folder/'fictional.lua').read_bytes()).hexdigest()
            mod=folder/'tf3_osm_importer_mod'
            export_new_mod(xml,mod,None,[1000,1000])
            assert (mod/'mod.json').read_bytes()==(template_folder()/'mod.json').read_bytes()
            assert (mod/'content/osm/importer.script.lua').read_bytes()==(template_folder()/'content/osm/importer.script.lua').read_bytes()
            assert export(xml,mod,None,[1000,1000])['edges']==report['edges']
            data=xml.read_bytes()
            class Response(io.BytesIO):
                headers={'Content-Length':str(len(data))}
                def geturl(self):return 'https://example.invalid/offline-test'
            downloaded=download([0,0,.01,.1],[10000,1000],folder/'downloaded.osm',opener=lambda *a,**k:Response(data))
            assert len(downloaded['downloadParts'])==2 and downloaded['counts']['nodes']==2
            image=folder/'fictional.png';Image.new('RGB',(8,8)).save(image)
            with Image.open(image) as png:assert png.size==(8,8)
        result={'ok':True,'frozenGui':'hidden Tk window and clam theme initialized' if getattr(sys,'frozen',False) else 'source-mode check','tclVersion':tcl,'tlsRoots':'loaded','sqlite':'query and offline multipart merge passed',
                'luaExport':'source and output hashes verified','standaloneMod':'frozen template bytes verified',
                'installedModUpdate':'fictional local folder only','png':'saved and reopened','networkUsed':False}
    except Exception as exc:
        result['error']=str(exc)
    Path(output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return 0 if result['ok'] else 1

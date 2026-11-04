"""Offline OSM -> converted Lua/report -> terrain/biomes -> importer package.

Each stage runs in its own tool-owned interpreter; fixtures stay under --output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from private_runtime import child_environment, verify

ROOT = Path(__file__).resolve().parents[1]


def stage(name, output):
    if name == 'osm':
        sys.path.insert(0, str(ROOT/'OSM-TF3-Vanilla-Converter/tools'))
        from converter import export_new_mod
        xml = output/'fictional.osm'
        xml.write_text('''<osm version="0.6"><bounds minlat="0" minlon="0" maxlat=".01" maxlon=".01"/>
<node id="1" lat=".002" lon=".002"/><node id="2" lat=".008" lon=".008"/>
<node id="3" lat=".005" lon=".006"><tag k="natural" v="tree"/></node>
<way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>''', encoding='utf-8')
        report = export_new_mod(xml, output/'tf3_osm_importer_mod', [0,0,.01,.01], [256,256])
        assert report['edges'] > 0 and report['sceneryItems'] > 0
        return {'edges': report['edges'], 'scenery': report['sceneryItems'], 'sourceSha256': report['sourceSha256']}
    if name == 'terrain':
        sys.path.insert(0, str(ROOT/'TF3-Heightmap-Studio/tools'))
        import numpy as np
        import rasterio
        from rasterio import Affine
        from PIL import Image
        from alignment import mercator_bounds
        from terrain import prepare, export, load_project
        mod = output/'tf3_osm_importer_mod'; report = mod/'import-report.json'
        info = json.loads(report.read_text(encoding='utf-8'))
        bounds = info['bounds']; x0,y0,x1,y1 = mercator_bounds(bounds)
        affine = Affine((x1-x0)/64,0,x0-(x1-x0)/128,0,-(y1-y0)/64,y1+(y1-y0)/128)
        dem = output/'fictional-dem.tif'; values = 100 + np.arange(65)[:,None]*.1 + np.arange(65)[None,:]*.2
        with rasterio.open(dem,'w',driver='GTiff',width=65,height=65,count=1,dtype='float64',crs='EPSG:3857',transform=affine) as dst:
            dst.write(values,1); dst.set_band_unit(1,'m')
        result = prepare(report,output/'fictional.osm',[dem],{'biomes':True},lua_path=mod/'content/osm/dataset.lua',lua_sha=info['luaSha256'])
        assert result['context']['convertedLua']['reportChecksumVerified']
        exported = export(result,output/'fictional-heightmap.png')
        project = load_project(exported['files']['project'])
        assert project['osmSha256'] == info['sourceSha256']
        assert project['luaSha256'] == info['luaSha256']
        with Image.open(exported['files']['png']) as png: assert png.size == (65,65)
        header = Path(exported['files']['png']).read_bytes()[:26]
        assert header[24:26] == bytes([16,0])
        assert Path(exported['files']['biomes']).is_file()
        # Exercise the public CLI using this exact exported project too.
        subprocess.run([sys.executable,'-I',str(ROOT/'scripts/private_runtime.py'),'run','--tool',str(ROOT/'TF3-Heightmap-Studio'),'--',str(ROOT/'TF3-Heightmap-Studio/tools/cli.py'),str(exported['files']['project']),
                        '--output',str(output/'cli-heightmap.png')], env=child_environment(ROOT/'TF3-Heightmap-Studio'), check=True)
        assert (output/'cli-heightmap.png').read_bytes() == Path(exported['files']['png']).read_bytes()
        return {'pixels':[65,65], 'bitDepth':16, 'biomes':True, 'luaReportIdentityVerified':True, 'projectReloadAndCliRoundTrip':True}
    from lupa import LuaRuntime
    data = LuaRuntime().execute((output/'tf3_osm_importer_mod/content/osm/dataset.lua').read_text(encoding='utf-8'))
    assert data['schema'] == 1 and len(data['edges']) > 0
    archive = output/'importer.zip'
    subprocess.run([sys.executable,'-I',str(ROOT/'TF3-OSM-Importer-Mod/scripts/package_mod.py'),'--output',str(archive)], check=True,
                   env=child_environment(ROOT/'TF3-OSM-Importer-Mod'))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for file in (ROOT/'TF3-OSM-Importer-Mod/mod/tf3_osm_importer_mod').rglob('*'):
            if file.is_file():
                rel = file.relative_to(ROOT/'TF3-OSM-Importer-Mod/mod')
                assert bundle.read(rel.as_posix()) == file.read_bytes()
    return {'generatedLuaExecuted':True, 'importerArchiveIntegrity':True, 'sourceFilesMatchPackage':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=['osm','terrain','importer'])
    args = parser.parse_args(); output = args.output.resolve()
    if args.stage:
        result = stage(args.stage,output)
        (output/(args.stage+'-result.json')).write_text(json.dumps(result,indent=2)+'\n')
        return
    output.mkdir(parents=True, exist_ok=False)
    tools = [('osm','OSM-TF3-Vanilla-Converter'),('terrain','TF3-Heightmap-Studio'),('importer','TF3-OSM-Importer-Mod')]
    result = {'ok':True,'networkUsed':False,'nativeGameTest':False}
    for name,tool in tools:
        root = ROOT/tool; verify(root)
        subprocess.run([str(root/'.runtime/python.exe'),'-I',str(Path(__file__).resolve()),'--stage',name,'--output',str(output)],
                       env=child_environment(root), check=True)
        result[name] = json.loads((output/(name+'-result.json')).read_text())
    assert hashlib.sha256((output/'fictional.osm').read_bytes()).hexdigest() == result['osm']['sourceSha256']
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__': main()

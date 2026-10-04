"""Read-only verification against installed vanilla resources; copies no assets."""
import argparse
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('converter',ROOT/'tools/converter.py')
c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)


def check(game):
    base=Path(game)/'base/content'
    available=set()
    for archive in base.rglob('*.zip'):
        prefix=archive.parent.relative_to(base).as_posix()
        prefix='' if prefix=='.' else prefix+'/'
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                available.add('::/'+prefix+(name[:-4] if name.endswith('.lua') else name))
    for file in base.rglob('*'):
        if file.is_file() and file.suffix!='.zip':
            name=file.relative_to(base).as_posix()
            available.add('::/'+(name[:-4] if name.endswith('.lua') else name))
    required=set(c.TREES+c.CONIFERS+c.SHRUBS+list(c.OBJECTS.values())+list(c.GROUND.values()))
    for highway in c.ROADS:
        for lanes in ['1','2','3','6']:
            for oneway in ['yes','no','-1']:
                for tram in [True,False]:
                    tags={'highway':highway,'lanes':lanes,'oneway':oneway}
                    if tram: tags['railway']='tram'
                    required.add(c.choose_template(tags)[0])
    for railway in c.RAILS:
        for limit in ['80','200']:
            for electric in ['no','contact_line']:
                required.add(c.choose_template({'railway':railway,'maxspeed':limit,'electrified':electric})[0])
    required.update(['::/infrastructure/bridge/steel.bridge','::/infrastructure/tunnel/tunnel_c.tunnel','::/assets/markers/marker_locate.mdl'])
    # Curated static-model substitutions in the bundled runtime are audited too.
    import re
    required.update(re.findall(r'::/[^"\s]+\.mdl',(ROOT/'mod/tf3_osm_importer_mod/content/osm/object_matcher.lua').read_text(encoding='utf8')))
    missing=sorted(required-available)
    ui_modules=['::/gui/main/react.lua','::/gui/main/builtin.lua','::/gui/main/main_mod_button_area.tl',
                '::/gui/main/game_react_globals.tl','::/gui/main/engine_react_util.tl','::/gui/main/stylesheetutil.lua']
    ui_missing=[name for name in ui_modules if (name[:-4] if name.endswith('.lua') else name) not in available]
    definition=json.loads((ROOT/'mod/tf3_osm_importer_mod/mod.json').read_text())
    assert not definition.get('dependencies'), 'External mod dependency'
    return {'checkedVanillaResources':len(required),'missing':missing,'externalModDependencies':definition.get('dependencies',[]),
            'resourceNames':sorted(required),'checkedUiModules':len(ui_modules),'uiMissing':ui_missing,'uiModules':ui_modules}


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('game'); p.add_argument('--output',type=Path)
    args=p.parse_args(); result=check(args.game)
    if args.output: args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='resourceNames'},indent=2))
    raise SystemExit(bool(result['missing'] or result['uiMissing']))

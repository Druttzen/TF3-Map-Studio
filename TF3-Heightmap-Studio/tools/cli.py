"""Reproducible command-line entry point; the Windows app uses the same engine."""
import argparse,json,os
from terrain import prepare,export,load_project

def main():
 parser=argparse.ArgumentParser(description='TF3 Heightmap Studio')
 parser.add_argument('project',help='Saved .heightmap-project.json')
 parser.add_argument('--output',help='Override output PNG path')
 parser.add_argument('--cache',help='Public elevation cache folder')
 args=parser.parse_args();p=load_project(args.project)
 progress=lambda percent,stage,detail:print(f'{percent:5.1f}% {stage} {detail}',flush=True)
 result=prepare(p['converterReport'],p['osmFile'],p['elevationFiles'],p['options'],p['brushStrokes'],cache=args.cache,progress=progress,api_key=os.environ.get('TF3_OPENTOPO_KEY'),lua_path=p.get('convertedLua'),lua_sha=p.get('luaSha256'),biome_strokes=p.get('biomeStrokes'))
 report=export(result,args.output or p['output'],progress=progress)
 print(json.dumps({'png':report['files']['png'],'min':report['importMinimumMetres'],'max':report['importMaximumMetres']},indent=2))
if __name__=='__main__':main()

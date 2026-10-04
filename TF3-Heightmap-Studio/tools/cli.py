"""Reproducible command-line entry point; the Windows app uses the same engine."""
import argparse,json,os
from terrain import prepare,export,load_project
from game_paths import detect, suggested_output

def main():
 parser=argparse.ArgumentParser(description='TF3 Heightmap Studio')
 parser.add_argument('project',help='Saved .heightmap-project.json')
 destination=parser.add_mutually_exclusive_group()
 destination.add_argument('--output',help='Override output PNG path')
 destination.add_argument('--to-tf3',action='store_true',help='Find installed TF3/Steam profile and export to its native heightmap/biome folders')
 parser.add_argument('--cache',help='Public elevation cache folder')
 args=parser.parse_args();p=load_project(args.project)
 game_paths=detect() if args.to_tf3 else None
 if args.to_tf3 and not game_paths.local:parser.error('A unique TF3 user folder could not be selected. Use --output with its heightmaps folder or select it in the app.')
 output=suggested_output(game_paths,p['osmFile']) if args.to_tf3 else args.output or p['output']
 progress=lambda percent,stage,detail:print(f'{percent:5.1f}% {stage} {detail}',flush=True)
 result=prepare(p['converterReport'],p['osmFile'],p['elevationFiles'],p['options'],p['brushStrokes'],cache=args.cache,progress=progress,api_key=os.environ.get('TF3_OPENTOPO_KEY'),lua_path=p.get('convertedLua'),lua_sha=p.get('luaSha256'),biome_strokes=p.get('biomeStrokes'))
 report=export(result,output,progress=progress,game_paths=game_paths)
 print(json.dumps({'png':report['files']['png'],'min':report['importMinimumMetres'],'max':report['importMaximumMetres']},indent=2))
if __name__=='__main__':main()

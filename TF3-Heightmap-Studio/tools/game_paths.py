"""Read installed TF3/Steam paths; never modify the Windows registry. GPL-3.0."""
from dataclasses import dataclass
import os, re, sys
from pathlib import Path

APP_ID='3493540'
UNINSTALL_KEY=r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App '+APP_ID


@dataclass(frozen=True)
class GamePaths:
 installation:Path|None=None
 local:Path|None=None
 profiles:tuple=()
 installation_source:str=''
 profile_source:str=''

 @property
 def heightmaps(self):return self.local/'heightmaps' if self.local else None

 @property
 def biomes(self):return self.local/'biomes' if self.local else None

 def describe(self):
  return {'installation':str(self.installation) if self.installation else None,
          'userData':str(self.local) if self.local else None,
          'installationSource':self.installation_source,'profileSource':self.profile_source}


def registry_locations():
 """Probe both registry views; stale or missing values are handled by discovery."""
 games=[];steam=[];active=''
 try:import winreg
 except ImportError:return games,steam,active
 views=[getattr(winreg,'KEY_WOW64_64KEY',0),getattr(winreg,'KEY_WOW64_32KEY',0)]
 def read(hive,key,name,view=0):
  try:
   with winreg.OpenKey(hive,key,0,winreg.KEY_READ|view) as handle:
    return winreg.QueryValueEx(handle,name)[0]
  except OSError:return None
 for hive in [winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER]:
  for view in views:
   value=read(hive,UNINSTALL_KEY,'InstallLocation',view)
   if isinstance(value,str) and value.strip():games.append((Path(value.strip()),'TF3 Windows install registry'))
 for hive,key,name in [(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam','SteamPath'),
                       (winreg.HKEY_LOCAL_MACHINE,r'Software\Valve\Steam','InstallPath')]:
  for view in views:
   value=read(hive,key,name,view)
   if isinstance(value,str) and value.strip():steam.append(Path(value.strip()))
 value=read(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam\ActiveProcess','ActiveUser')
 if isinstance(value,int) and value!=0:active=str(value&0xffffffff)
 return games,steam,active


def valid_installation(path):
 return (path/'TransportFever3.exe').is_file() and (path/'base/content').is_dir()


def read_vdf(path):
 try:
  if path.stat().st_size>4*1024*1024:return ''
  return path.read_text(encoding='utf-8-sig')
 except (OSError,UnicodeError):return ''


def steam_libraries(roots):
 libraries=list(roots)
 for root in roots:
  text=read_vdf(root/'steamapps/libraryfolders.vdf')
  libraries.extend(Path(p.replace('\\\\','\\')) for p in re.findall(r'"path"\s+"([^"\r\n]+)"',text))
 return list(dict.fromkeys(p.resolve() for p in libraries))


def detect():
 games,roots,active=registry_locations()
 if not roots:
  if sys.platform=='win32':
   roots=[Path(v)/'Steam' for k in ['ProgramFiles(x86)','ProgramFiles'] if (v:=os.environ.get(k))]
  else:roots=[Path.home()/'.local/share/Steam',Path.home()/'.steam/steam']
 roots=list(dict.fromkeys(p.resolve() for p in roots if p.is_dir()))
 libraries=steam_libraries(roots)
 for library in libraries:
  text=read_vdf(library/'steamapps'/('appmanifest_'+APP_ID+'.acf'))
  app=re.search(r'"appid"\s+"(\d+)"',text)
  name=re.search(r'"installdir"\s+"([^"\r\n]+)"',text)
  if app and app[1]==APP_ID and name and name[1] not in {'.','..'} and not any(c in name[1] for c in '/\\:'):
   games.append((library/'steamapps/common'/name[1],'Steam TF3 app manifest'))
  games.append((library/'steamapps/common/Transport Fever 3','Verified TF3 in Steam library'))
 installation=None;source=''
 for path,label in games:
  if valid_installation(path):installation=path.resolve();source=label;break
 profiles=[];active_profiles=[]
 for root in roots:
  userdata=root/'userdata'
  if installation and active and userdata.is_dir():active_profiles.append((userdata/active/APP_ID/'local').resolve())
  try:users=sorted(p for p in userdata.iterdir() if p.is_dir() and p.name.isdigit() and int(p.name)>0)
  except OSError:continue
  for user in users:
   local=user/APP_ID/'local'
   if local.is_dir():profiles.append(local.resolve())
 profiles=list(dict.fromkeys(profiles));active_profiles=list(dict.fromkeys(active_profiles))
 local=None;profile_source=''
 if installation and len(active_profiles)==1:local=active_profiles[0];profile_source='Active Steam account registry'
 elif installation and not active_profiles and len(profiles)==1:local=profiles[0];profile_source='Only existing TF3 Steam profile'
 return GamePaths(installation,local,tuple(profiles),source,profile_source)


def suggested_output(paths,source='',fallback=''):
 """Derive the map name without overwriting an existing heightmap by default."""
 if source:
  name=Path(source).stem
  for suffix in ['.heightmap-project','.heightmap-report','.report']:
   if name.endswith(suffix):name=name[:-len(suffix)];break
 else:name='heightmap'
 name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .') or 'heightmap'
 if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',name,re.I):name='map_'+name
 parent=paths.heightmaps if paths.local else Path(fallback).parent if fallback else None
 if parent is None:return ''
 output=parent/(name+'.png');index=2
 def occupied(path):
  return path.exists() or bool(paths.local and ((paths.biomes/(path.stem+'.biomes.png')).exists() or (paths.local/'heightmap_studio'/path.stem).exists()))
 while occupied(output):output=parent/(name+'-'+str(index)+'.png');index+=1
 return str(output)


def select_user_folder(path,paths=None):
 """Accept a user-selected, existing TF3 local folder without inventing a profile."""
 local=Path(path).resolve();paths=paths or GamePaths()
 steam_layout=local.name.lower()=='local' and local.parent.name==APP_ID and local.parent.parent.name.isdigit()
 if not local.is_dir() or not (steam_layout or (local/'settings.lua').is_file()):
  raise ValueError('Choose the TF3 local user folder, containing settings.lua or inside Steam userdata/<user>/3493540/local.')
 return GamePaths(paths.installation,local,paths.profiles,paths.installation_source,'Selected TF3 user folder')


def export_destination(output,paths=None):
 """Use native folders only for a chosen, verified TF3 heightmaps destination."""
 output=Path(output).resolve()
 if paths is None and output.parent.name.lower()=='heightmaps':paths=detect()
 if paths:
  locations=list(paths.profiles)+([paths.local] if paths.local else [])
  for local in dict.fromkeys(locations):
   if output.parent==(local/'heightmaps').resolve():
    selected=GamePaths(paths.installation,local,paths.profiles,paths.installation_source,paths.profile_source if local==paths.local else 'Chosen existing TF3 profile')
    return {'native':True,'details':local/'heightmap_studio'/output.stem,
            'biomes':local/'biomes','location':selected.describe()}
 return {'native':False,'details':output.parent,'biomes':output.parent,'location':None}

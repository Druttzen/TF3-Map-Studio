"""Read converter-generated Lua tables as data, never execute Lua. GPL-3.0."""
import codecs, hashlib, math, re, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from job import Job

NUMBER=re.compile(r'-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
SPACE=re.compile(r'\s+')
SPECIAL=re.compile(r'["\\\r\n]')
WORD=re.compile(r'[A-Za-z_]+')
DIGITS=re.compile(r'[0-9.eE+\-]+')

class ArrayCount:
 """Scenery/labels are validated and counted without retaining their contents."""
 def __init__(self,count):self.count=count
 def __len__(self):return self.count

class Scanner:
 """Incremental tokenizer; whitespace/comments never accumulate between chunks."""
 def __init__(self,chunks,job):
  self.chunks=iter(chunks);self.job=job;self.buffer='';self.pos=0;self.offset=0;self.eof=False
 def fill(self):
  self.job.check();self.offset+=self.pos;self.buffer=self.buffer[self.pos:];self.pos=0
  try:self.buffer+=next(self.chunks)
  except StopIteration:self.eof=True
 def ensure(self,count=1):
  while len(self.buffer)-self.pos<count and not self.eof:self.fill()
  return len(self.buffer)-self.pos>=count
 def error(self):raise ValueError(f'Unsupported Lua content at character {self.offset+self.pos}. Only converter data tables are accepted.')
 def string(self):
  parts=['"'];self.pos+=1
  while self.ensure():
   m=SPECIAL.search(self.buffer,self.pos);end=m.start() if m else len(self.buffer)
   parts.append(self.buffer[self.pos:end]);self.pos=end
   if not m:continue
   c=self.buffer[self.pos];self.pos+=1
   if c=='"':parts.append(c);return ''.join(parts)
   if c in '\r\n':self.error()
   parts.append('\\')
   if not self.ensure():self.error()
   c=self.buffer[self.pos]
   if c in '"\\':parts.append(c);self.pos+=1
   elif c in '0123456789':
    for _ in range(3):
     if not self.ensure() or self.buffer[self.pos] not in '0123456789':break
     parts.append(self.buffer[self.pos]);self.pos+=1
   else:self.error()
  raise ValueError('Incomplete converter Lua string.')
 def run(self,pattern):
  parts=[]
  while self.ensure():
   m=pattern.match(self.buffer,self.pos)
   if not m:break
   parts.append(m.group());self.pos=m.end()
   if self.pos<len(self.buffer):break
  return ''.join(parts)
 def next(self):
  while self.ensure():
   m=SPACE.match(self.buffer,self.pos)
   if m:self.pos=m.end();continue
   if self.buffer[self.pos]=='-' and self.ensure(2) and self.buffer[self.pos:self.pos+2]=='--':
    self.pos+=2
    while self.ensure():
     end=self.buffer.find('\n',self.pos)
     if end>=0:self.pos=end+1;break
     self.pos=len(self.buffer)
    continue
   c=self.buffer[self.pos]
   if c=='"':return self.string()
   if c in '{}[]=,':self.pos+=1;return c
   if c in '-.0123456789':
    token=self.run(DIGITS)
    if not NUMBER.fullmatch(token):self.error()
    return token
   token=self.run(WORD)
   if token not in {'true','false','nil','return'}:self.error()
   return token
  return None

class Reader:
 def __init__(self,chunks,job,summarize=False):
  self.job=job;self.scanner=Scanner(chunks,job);self.summarize=summarize;self.token=None;self.advance()
 @property
 def pos(self):return self.scanner.offset+self.scanner.pos
 def advance(self):
  self.token=self.scanner.next()
 def take(self,expected):
  if self.token!=expected:raise ValueError(f'Invalid converter Lua: expected {expected!r} at character {self.pos}.')
  self.advance()
 def value(self,depth=0,keep=True):
  if depth>32:raise ValueError('Converter Lua tables are nested too deeply.')
  t=self.token
  if t=='{':
   self.advance();values=[];mapping={};seen=set();count=0;mode=None
   while self.token!='}':
    if self.token is None:raise ValueError('Incomplete converter Lua table.')
    keyed=self.token=='['
    if mode is not None and mode!=keyed:raise ValueError('Mixed Lua tables are not supported.')
    mode=keyed
    if keyed:
     self.advance();key=self.value(depth+1)
     if not isinstance(key,str):raise ValueError('Converter Lua keys must be strings.')
     self.take(']');self.take('=')
     if key in seen:raise ValueError('Duplicate converter Lua key.')
     seen.add(key)
     retain=keep and not (self.summarize and depth==0 and key in {'scenery','labels','warnings','importOptions'})
     item=self.value(depth+1,retain)
     if keep:mapping[key]=item
    else:
     item=self.value(depth+1,keep);count+=1
     if keep:values.append(item)
    if self.token==',':self.advance()
    elif self.token!='}':raise ValueError('Missing comma in converter Lua table.')
   self.advance()
   if keep:return mapping if mode else values
   return {} if mode else ArrayCount(count)
  if t is None:raise ValueError('Incomplete converter Lua data.')
  self.advance()
  if t.startswith('"'):
   def escape(m):
    v=m.group(1)
    if v.isdigit():
     if int(v)>127:raise ValueError('Unsupported byte escape in converter Lua string.')
     return chr(int(v))
    return v
   return re.sub(r'\\([0-9]{1,3}|["\\])',escape,t[1:-1])
  if t in {'true','false','nil'}:return {'true':True,'false':False,'nil':None}[t]
  try:value=float(t) if any(c in t for c in '.eE') else int(t)
  except ValueError:raise ValueError('Executable Lua is not accepted; select a converter-generated dataset.') from None
  if not math.isfinite(value):raise ValueError('Non-finite converter Lua number.')
  return value

def parse_stream(chunks,job=None,summarize=False):
 reader=Reader(chunks,job or Job(),summarize);reader.take('return');value=reader.value()
 if reader.token is not None:raise ValueError('Trailing executable Lua content is not accepted.')
 if not isinstance(value,dict):raise ValueError('Converter Lua must return a dataset table.')
 return value

def parse(text,job=None):return parse_stream([text],job)

def numeric_list(value,length):
 return isinstance(value,list) and len(value)==length and all(type(v) in {int,float} and math.isfinite(v) for v in value)

def read_map(path,report,job=None,expected_sha=None):
 job=job or Job();path=Path(path)
 digest=hashlib.sha256();total=0;size_bytes=path.stat().st_size
 job.update(31,'Reading converted Lua map',path.name)
 with path.open('rb') as source:
  def chunks():
   nonlocal total
   decoder=codecs.getincrementaldecoder('utf-8-sig')()
   while chunk:=source.read(65536):
    job.check();total+=len(chunk);digest.update(chunk)
    job.update(31+min(1,total/max(1,size_bytes)),'Reading converted Lua map',f'{path.name}: {total/1048576:.1f} / {size_bytes/1048576:.1f} MB')
    yield decoder.decode(chunk)
   yield decoder.decode(b'',final=True)
  data=parse_stream(chunks(),job,summarize=True)
 sha=digest.hexdigest()
 for wanted in [report.get('luaSha256'),expected_sha]:
  if wanted and wanted!=sha:raise ValueError('Converted Lua checksum differs from its report or saved project. Restore the matching dataset or run the converter again.')
 if type(data.get('schema')) is not int or data['schema']!=1:raise ValueError('Unsupported converted Lua schema.')
 if data.get('id')!=report['dataset']:raise ValueError('Converted Lua dataset does not match the converter report.')
 if not numeric_list(data.get('bounds'),4) or data['bounds']!=report['bounds'] or not numeric_list(data.get('size'),2) or data['size']!=report['mapSize']:
  raise ValueError('Converted Lua coordinates or map size differ from the converter report.')
 from osm_converter import normalize_options
 if not isinstance(data.get('conversionSettings'),dict) or normalize_options(data['conversionSettings'])!=report['settings']:
  raise ValueError('Converted Lua settings differ from the converter report.')
 nodes=data.get('nodes');edges=data.get('edges');scenery=data.get('scenery');labels=data.get('labels')
 if nodes==[]:nodes={}
 if not isinstance(nodes,dict) or not isinstance(edges,list) or not all(isinstance(v,(list,ArrayCount)) for v in [scenery,labels]):raise ValueError('Invalid converted Lua feature tables.')
 for field,items in [('edges',edges),('sceneryItems',scenery),('placeLabels',labels)]:
  if type(report.get(field)) is not int or report[field]!=len(items):raise ValueError(f'Converted Lua {field} count differs from the converter report.')
 size=report['mapSize'];positions={}
 for i,(key,node) in enumerate(nodes.items()):
  if i%256==0:job.check()
  p=node.get('pos') if isinstance(node,dict) else None
  if not numeric_list(p,2) or any(abs(p[k])>size[k]/2+1e-5 for k in (0,1)):raise ValueError('Converted Lua node lies outside the map or has an invalid position.')
  positions[key]=p
 groups=defaultdict(list);counts={'roadSegments':0,'railSegments':0,'bridgeSegments':0,'tunnelSegments':0}
 for i,edge in enumerate(edges):
  if i%256==0:job.check()
  if not isinstance(edge,dict) or edge.get('kind') not in {'STREET','TRACK'}:raise ValueError('Invalid converted Lua edge kind.')
  a=edge.get('node0');b=edge.get('node1')
  if not isinstance(a,str) or not isinstance(b,str) or a not in positions or b not in positions or a==b or math.dist(positions[a],positions[b])<1e-8:raise ValueError('Converted Lua edge has missing or coincident nodes.')
  if any(type(edge.get(k)) is not bool for k in ['bridge','tunnel']) or not isinstance(edge.get('osmWay'),str):raise ValueError('Invalid converted Lua edge metadata.')
  kind='road' if edge['kind']=='STREET' else 'rail';counts[kind+'Segments']+=1
  counts['bridgeSegments']+=edge['bridge'];counts['tunnelSegments']+=edge['tunnel']
  groups[(edge['osmWay'],kind,edge['bridge'],edge['tunnel'])].append((a,b))
 lines=[]
 # Join subdivision segments, but stop at branches and structure boundaries.
 # Profiles then follow the entire converted corridor rather than restarting at each edge.
 for (way,kind,bridge,tunnel),segments in groups.items():
  adjacent=defaultdict(list)
  for i,(a,b) in enumerate(segments):adjacent[a].append(i);adjacent[b].append(i)
  used=set()
  def walk(start,index):
   chain=[positions[start]];node=start
   while index not in used:
    if len(used)%256==0:job.check()
    used.add(index);a,b=segments[index];node=b if node==a else a;chain.append(positions[node])
    if len(adjacent[node])!=2:break
    candidates=[v for v in adjacent[node] if v not in used]
    if not candidates:break
    index=candidates[0]
   lines.append({'way':way,'kind':kind,'points':chain,'bridge':bridge,'tunnel':tunnel})
  for node,indices in adjacent.items():
   if len(indices)!=2:
    for index in indices:
     if index not in used:walk(node,index)
  for index,(a,b) in enumerate(segments):
   if index not in used:walk(a,index)
 info={'file':str(path.resolve()),'sha256':sha,'dataset':data['id'],'reportChecksumVerified':bool(report.get('luaSha256')),
       'nodes':len(nodes),'edges':len(edges),'sceneryItems':len(scenery),'placeLabels':len(labels),**counts,'corridorPolylines':len(lines)}
 return lines,info

def find_map(report_path,report):
 p=Path(report_path).resolve()
 candidates=[p.with_name(p.name[:-len('.report.json')]+'.lua')] if p.name.endswith('.report.json') else []
 candidates.append(p.parent/'content/osm/dataset.lua')
 if isinstance(report.get('output'),str):candidates.append(p.parent/Path(report['output']))
 return next((str(v.resolve()) for v in candidates if v.is_file()),'')

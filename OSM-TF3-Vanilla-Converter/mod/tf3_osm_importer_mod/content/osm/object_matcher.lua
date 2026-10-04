-- GPL-3.0. Deterministic static-model matching against the current game's repositories.
local matcher={}
local catalog
local curated={
  fountain="::/assets/landmarks/msc/fountain.mdl",
  bollard="::/assets/stations/water/mooring_bollard_passengers.mdl",
  advertising_column="::/assets/buildings/com/advertisements/column_c_01.mdl",
  bench="::/assets/stations/street/bench_era_c_rep_1.mdl",
  waste_basket="::/assets/stations/rail/era_c_trashcan.mdl",
  post_box="::/assets/streets/mailbox_eu_c.mdl",
  street_lamp="::/assets/streets/street_light_eu_c.mdl",
  rock="::/assets/rocks/gr_rck_01/gr_rck_01.mdl",
  memorial="::/assets/landmarks/msc/lion_statue.mdl",
  lighthouse="::/landmarks/lighthouse/lighthouse.mdl",
  storage_tank="::/assets/industries/tanks/oil_storage_medium.mdl",
}
local tokens={fountain={"fountain"},bollard={"bollard"},advertising_column={"advertising_column"},tree={"tree"},bench={"bench"},waste_basket={"trashcan","trash","waste_basket"},
  drinking_water={"drinking_water"},post_box={"mailbox","post_box"},bicycle_parking={"bicycle_parking","bike_rack"},
  street_lamp={"street_light","street_lamp"},rock={"rock"},memorial={"memorial","statue"},
  monument={"monument"},water_tower={"water_tower"},lighthouse={"lighthouse"},storage_tank={"storage_tank","oil_storage"},power_tower={"power_tower","pylon"}}

local function valid(id) return type(id)=="number" and id>=0 end
local function component(v,index)
  if not v then return nil end
  local key=({"x","y","z"})[index]
  return v[key] or v[index]
end
local function finite(v) return type(v)=="number" and v==v and math.abs(v)<math.huge end
local function geometry(model)
  local box=model and model.boundingInfo
  if not box then return nil end
  local a,b={},{}
  for i=1,3 do
    a[i]=component(box.bbMin,i); b[i]=component(box.bbMax,i)
    if not finite(a[i]) or not finite(b[i]) or b[i]<a[i] then return nil end
  end
  if b[1]-a[1]<0.05 or b[2]-a[2]<0.05 then return nil end
  return {width=b[1]-a[1],length=b[2]-a[2],height=b[3]-math.max(0,a[3]),centre={(a[1]+b[1])/2,(a[2]+b[2])/2}}
end
local function kindFor(name,model)
  local m=model.metadata or {}
  if m.transportVehicle or m.signal or m.animal or m.railroadCrossing then return nil end
  -- Mods can declare an unambiguous OSM class without relying on English filenames.
  if type(m.osmImporter)=="table" and type(m.osmImporter.kind)=="string" then return m.osmImporter.kind end
  if name:find("/assets/vegetation/trees/",1,true) then return "tree" end
  if name:match("/buildings/[abc]/r%d/") or name:find("residential",1,true) then return "residential" end
  if name:match("/buildings/[abc]/c%d/") or name:find("commercial",1,true) then return "commercial" end
  if name:match("/buildings/[abc]/i%d/") or name:find("industrial_building",1,true) then return "industrial" end
  for kind,path in pairs(curated) do if name==path then return kind end end
  -- Complete token boundaries avoid e.g. matching a ship called "Rockefeller".
  local lower=name:lower()
  local found
  for kind,words in pairs(tokens) do
    for _,word in ipairs(words) do
      local start,finish=lower:find(word,1,true)
      if start and (start==1 or not lower:sub(start-1,start-1):match("%w"))
        and (finish==#lower or not lower:sub(finish+1,finish+1):match("%w")) then
        if found and found~=kind then return nil end
        found=kind
      end
    end
  end
  return found
end

local function loadCatalog()
  if catalog then return catalog end
  catalog={}
  local rep=api.res.modelRep
  assert(type(rep.getAll)=="function","The loaded model repository cannot be enumerated in this TF3 build")
  local names=rep.getAll(true)
  for id,name in pairs(names) do
    if valid(id) and type(name)=="string" and name:match("^[^:]*::/") and name:sub(-4)==".mdl" then
      local ok,model=pcall(rep.get,id)
      if ok then
        local kind=kindFor(name,model)
        if kind then
          local box=geometry(model)
          if box then catalog[#catalog+1]={name=name,kind=kind,geometry=box,vanilla=name:sub(1,3)=="::/"} end
        end
      end
    end
  end
  table.sort(catalog,function(a,b) return a.name<b.name end)
  return catalog
end

local function fitsRing(p,ring)
  local hit=false
  for i,a in ipairs(ring) do
    local b=ring[i%#ring+1]
    local cross=(p[1]-a[1])*(b[2]-a[2])-(p[2]-a[2])*(b[1]-a[1])
    if math.abs(cross)<0.0001 and p[1]>=math.min(a[1],b[1])-0.001 and p[1]<=math.max(a[1],b[1])+0.001
      and p[2]>=math.min(a[2],b[2])-0.001 and p[2]<=math.max(a[2],b[2])+0.001 then return true end
    if (a[2]>p[2])~=(b[2]>p[2]) and p[1]<a[1]+(p[2]-a[2])*(b[1]-a[1])/(b[2]-a[2]) then hit=not hit end
  end
  return hit
end

local function choice(item,entry,swapped)
  local g=entry.geometry
  local angle=(item.rotation or 0)+(swapped and math.pi/2 or 0)
  local c,s=math.cos(angle),math.sin(angle)
  local pos={item.pos[1]-g.centre[1]*c+g.centre[2]*s,item.pos[2]-g.centre[1]*s-g.centre[2]*c}
  if item.footprint then
    if not fitsRing(item.pos,item.footprint) then return nil end
    for _,corner in ipairs({{-g.width/2,-g.length/2},{g.width/2,-g.length/2},{g.width/2,g.length/2},{-g.width/2,g.length/2}}) do
      if not fitsRing({item.pos[1]+corner[1]*c-corner[2]*s,item.pos[2]+corner[1]*s+corner[2]*c},item.footprint) then return nil end
    end
    -- Corner tests alone would bridge a concave notch. Reject any source
    -- boundary passing through the open interior of the proposed rectangle.
    local hx,hy=g.width/2-0.001,g.length/2-0.001
    local function localPoint(p)
      local x,y=p[1]-item.pos[1],p[2]-item.pos[2]
      return {x*c+y*s,-x*s+y*c}
    end
    for i,p in ipairs(item.footprint) do
      local a,b=localPoint(p),localPoint(item.footprint[i%#item.footprint+1])
      local low,high=0,1
      local dx,dy=b[1]-a[1],b[2]-a[2]
      local intersects=true
      for _,side in ipairs({{-dx,a[1]+hx},{dx,hx-a[1]},{-dy,a[2]+hy},{dy,hy-a[2]}}) do
        if math.abs(side[1])<1e-12 then
          if side[2]<0 then intersects=false; break end
        elseif side[1]<0 then low=math.max(low,side[2]/side[1])
        else high=math.min(high,side[2]/side[1]) end
      end
      if intersects and low<high and high>=0 and low<=1 then return nil end
    end
  end
  return {model=entry.name,pos=pos,rotation=angle,origin=entry.vanilla and "vanilla" or "active mod",
    kind=entry.kind,method=item.dimensions and "class and footprint fit (no scaling)" or "semantic class"}
end

function matcher.resolve(item,options)
  if not item.match then return nil end
  local kind=item.match.kind
  assert(type(kind)=="string" and type(item.pos)=="table","Invalid mapped object")
  -- Keep explicitly chosen vanilla substitutions when the game has them.
  -- This also preserves older datasets' model origin and rotation conventions.
  if item.model and item.model:sub(1,3)=="::/" and valid(api.res.modelRep.find(item.model)) then
    local model=api.res.modelRep.get(api.res.modelRep.find(item.model))
    local m=model.metadata or {}
    assert(not (m.transportVehicle or m.signal or m.animal or m.railroadCrossing),"Configured mapped object is not a static model")
    return {model=item.model,pos={item.pos[1],item.pos[2]},rotation=item.rotation or 0,origin="vanilla",kind=kind,method="configured vanilla substitution"}
  end
  local candidates=loadCatalog()
  for _,vanilla in ipairs({true,false}) do
    if vanilla or options.useActiveMods then
      local best,bestScore
      for _,entry in ipairs(candidates) do
        if entry.vanilla==vanilla and (entry.kind==kind or kind=="building" and (entry.kind=="residential" or entry.kind=="commercial" or entry.kind=="industrial")) then
          for _,swapped in ipairs({false,true}) do
            local resolved=choice(item,entry,swapped)
            if resolved then
              local score=0
              if item.dimensions then
                local w,l=entry.geometry.width,entry.geometry.length
                if swapped then w,l=l,w end
                score=math.abs(math.log(w/item.dimensions[1]))+math.abs(math.log(l/item.dimensions[2]))
              elseif entry.name~=curated[kind] then score=1 end
              if item.match.height and finite(item.match.height) and item.match.height>0 and entry.geometry.height>0 then
                score=score+0.25*math.abs(math.log(entry.geometry.height/item.match.height))
              end
              if not bestScore or score<bestScore then best,bestScore=resolved,score end
            end
          end
        end
      end
      if best then return best end
    end
  end
  return {unmatched=true,kind=kind,reason="No safe class/footprint match in vanilla"..(options.useActiveMods and " or loaded active mods" or " resources")}
end

function matcher.summary(matches)
  local result={vanilla=0,mods=0,unmatched=0,examples={}}
  for _,match in pairs(matches or {}) do
    if match.unmatched then result.unmatched=result.unmatched+1
    elseif match.origin=="vanilla" then result.vanilla=result.vanilla+1
    else result.mods=result.mods+1 end
  end
  local seen={}
  local examples={}
  for _,match in pairs(matches or {}) do
    local label=match.kind..": "..(match.model or match.reason)
    if not seen[label] then seen[label]=true; examples[#examples+1]=label end
  end
  table.sort(examples)
  for i=1,math.min(20,#examples) do result.examples[i]=examples[i] end
  return result
end
return matcher

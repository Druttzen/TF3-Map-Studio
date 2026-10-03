-- GPL-3.0. Experimental local water construction, not navigable game water.
local water={}
water.construction="druttzen_osm_vanilla::/osm/water.con"
water.model="druttzen_osm_vanilla::/osm/water_triangle.mdl"

local function finite(n) return type(n)=="number" and n==n and math.abs(n)<math.huge end
function water.checkEmpty(face,margin)
  local limits=api.engine.mapgen.getMinMaxValidTerrainHeight()
  local x0,y0,x1,y1=math.huge,math.huge,-math.huge,-math.huge
  for _,p in ipairs(face) do
    assert(finite(p[1]) and finite(p[2]),"Invalid shallow-water boundary")
    x0=math.min(x0,p[1]);y0=math.min(y0,p[2]);x1=math.max(x1,p[1]);y1=math.max(y1,p[2])
  end
  local region=api.type.Box3.new(api.type.Vec3f.new(x0-margin,y0-margin,limits[1]),api.type.Vec3f.new(x1+margin,y1+margin,limits[2]))
  local blocked=false;local T=api.type.ComponentType
  api.engine.system.octreeSystem.findIntersectingEntities(region,function(entity)
    local con=api.engine.getComponent(entity,T.CONSTRUCTION)
    -- Other accepted batches of this importer must be allowed at shared banks.
    if api.engine.getComponent(entity,T.BASE_EDGE) or (con and con.fileName~="druttzen_osm_vanilla::/osm/scenery.con") then blocked=true end
  end)
  assert(not blocked,"Shallow water is near an existing road, railway or construction; network heights have priority")
end
function water.settings(source)
  local p={x=0,y=0,level=20,endLevel=20,width=20,length=20,depth=2,carve=false}
  for key in pairs(p) do if source and source[key]~=nil then p[key]=source[key] end end
  return p
end
function water.configure(source,patch)
  assert(type(patch)=="table","Water settings must be a table")
  local p=water.settings(source)
  for key,v in pairs(patch) do
    assert(p[key]~=nil,"Unknown water setting: "..tostring(key))
    if key=="carve" then
      assert(type(v)=="boolean","Carve basin must be true or false")
      assert(not v,"Basin shaping is disabled: native TF3 tests produced terrain spikes")
    else
      assert(finite(v),"Water settings must be finite numbers")
      if key=="width" or key=="length" then assert(v>=1 and v<=100,"Test water dimensions must be 1 to 100 metres")
      elseif key=="depth" then assert(v>=0.1 and v<=20,"Test basin depth must be 0.1 to 20 metres")
      else assert(math.abs(v)<=20000,"Water coordinate/height is out of range") end
    end
    p[key]=v
  end
  return p
end
function water.faces(p)
  p=water.configure(nil,p)
  local a={p.x-p.length/2,p.y-p.width/2,p.level}
  local b={p.x+p.length/2,p.y-p.width/2,p.endLevel}
  local c={p.x+p.length/2,p.y+p.width/2,p.endLevel}
  local d={p.x-p.length/2,p.y+p.width/2,p.level}
  return {{a,b,c},{a,c,d}}
end
function water.transform(face)
  assert(type(face)=="table" and #face==3,"Water mesh requires a triangle")
  for _,p in ipairs(face) do assert(type(p)=="table" and finite(p[1]) and finite(p[2]) and finite(p[3]),"Invalid water triangle coordinate") end
  local a,b,c=face[1],face[2],face[3]
  assert((b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1])>0.000001,"Water triangle must have counter-clockwise, distinct XY vertices")
  return {b[1]-a[1],b[2]-a[2],b[3]-a[3],0,
    c[1]-a[1],c[2]-a[2],c[3]-a[3],0, 0,0,1,0, a[1],a[2],a[3],1}
end

function water.checkRecorded(p,records)
  for _,record in ipairs(records or {}) do
    local q=record.settings
    local margin=(p.carve and 10 or 0)+(q and q.carve and 10 or 0)
    assert(q and not (math.abs(p.x-q.x)<(p.length+q.length)/2+margin and math.abs(p.y-q.y)<(p.width+q.width)/2+margin),
      "Test water overlaps a previously recorded patch; choose another position")
  end
end

-- Read-only planning; keep an explicit margin from all existing networks and
-- constructions. Do not suppress collision errors or delete existing objects.
function water.check(p)
  local faces=water.faces(p)
  local box=api.engine.terrain.getBoundingBox()
  local limits=api.engine.mapgen.getMinMaxValidTerrainHeight()
  for _,face in ipairs(faces) do for _,v in ipairs(face) do
    assert(v[1]>box.min.x+0.01 and v[1]<box.max.x-0.01 and v[2]>box.min.y+0.01 and v[2]<box.max.y-0.01,"Test water is outside the map")
    assert(v[3]>=limits[1] and v[3]<=limits[2] and (not p.carve or v[3]-p.depth>=limits[1]),"Test water/basin height is outside TF3 limits")
  end end
  local blocked=false
  local T=api.type.ComponentType
  -- Check the entire height range, also protecting elevated tracks/bridges.
  -- Basin bank influence has not yet been measured in TF3. Until it is, basin
  -- tests require a map without networks or constructions anywhere. A surface
  -- without terrain shaping uses only the local 20m exclusion margin.
  local region=api.type.Box3.new(api.type.Vec3f.new(p.carve and box.min.x or p.x-p.length/2-20,p.carve and box.min.y or p.y-p.width/2-20,limits[1]),
    api.type.Vec3f.new(p.carve and box.max.x or p.x+p.length/2+20,p.carve and box.max.y or p.y+p.width/2+20,limits[2]))
  api.engine.system.octreeSystem.findIntersectingEntities(region,function(entity)
    if api.engine.getComponent(entity,T.BASE_EDGE) or api.engine.getComponent(entity,T.CONSTRUCTION) then blocked=true end
  end)
  assert(not blocked,"Test water is near an existing road, railway or construction; choose an empty test area")
  local id=api.res.modelRep.find(water.model)
  assert(type(id)=="number" and id>=0,"Experimental water model is unavailable")
  local con=api.res.constructionRep.find(water.construction)
  assert(type(con)=="number" and con>=0,"Experimental water construction is unavailable")
  return faces
end
function water.proposal(p)
  water.check(p)
  local proposal=api.type.SimpleProposal.new()
  local con=api.type.SimpleProposal.ConstructionEntity.new()
  -- Native params access returns a Lua copy. Prepare the whole table before
  -- assigning it, rather than mutating a temporary value returned by the getter.
  local params=water.configure(nil,p); params.seed=0
  con.fileName=water.construction; con.params=params
  con.transf=api.type.Mat4f.new(); con.playerEntity=api.engine.util.getPlayer()
  con.name="OSM experimental water test"
  proposal.constructionsToAdd={con}
  return proposal
end
return water

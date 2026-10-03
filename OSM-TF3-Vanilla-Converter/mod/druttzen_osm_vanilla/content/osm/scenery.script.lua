local script = {}

function script.updateFn(_captureParams, params)
  local sub = { tag = 1, models = {}, groundFaces = {}, terrainAlignmentLists = {{type="EQUAL",faces={}}} }
  for _, item in ipairs(params.items or {}) do
    if item.model then
      local c, s = math.cos(item.rotation or 0), math.sin(item.rotation or 0)
      sub.models[#sub.models+1] = {
        id = item.model,
        transf = {c,s,0,0, -s,c,0,0, 0,0,1,0, item.pos[1],item.pos[2],item.pos[3],1},
      }
    elseif item.texture then
      if item.depth~=nil then
        assert(item.depth==0.5 and item.texture=="druttzen_osm_vanilla::/osm/dirty_water.gtex","Invalid shallow-water construction")
        assert(#item.face==3,"Shallow-water bed must be a triangle")
        local face={}
        for _,p in ipairs(item.face) do
          assert(type(p[3])=="number" and p[3]==p[3] and math.abs(p[3])<math.huge,"Invalid saved bed height")
          face[#face+1]={p[1],p[2],p[3],1}
        end
        sub.terrainAlignmentLists[#sub.terrainAlignmentLists+1]={type="LESS",faces={face},slopeLow=0.5,slopeHigh=0.5}
      end
      sub.groundFaces[#sub.groundFaces+1] = {
        face = item.face,
        modes = {{type="FILL",key=item.texture}},
        loop = true,
      }
    end
  end
  return {
    cost = 0, maintenanceCost = 0, noCostAtAll = true,
    -- Metadata annotates retained constructions; TF3 still optimizes model-only
    -- batches into asset groups. Their IDs are kept in the importer journal.
    metadata = {druttzenOsmImporter={schema=1}},
    subconstructions = {sub},
  }
end

-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return script
end

local controls = ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local script = {}

function script.updateFn(_captureParams, params)
  local sub = { tag = 1, models = {}, groundFaces = {}, terrainAlignmentLists = {{type="EQUAL",faces={}}} }
  local origin=params.origin or {0,0}
  for _, item in ipairs(params.items or {}) do
    if item.model then
      local c, s = math.cos(item.rotation or 0), math.sin(item.rotation or 0)
      sub.models[#sub.models+1] = {
        id = item.model,
        transf = {c,s,0,0, -s,c,0,0, 0,0,1,0, item.pos[1],item.pos[2],item.pos[3],1},
      }
    elseif item.texture then
      local groundFace,reason=controls.groundFace(item.face)
      assert(groundFace,reason)
      local fill={type="FILL",key=item.texture}
      if item.depth~=nil or item.waterSurface~=nil then
        assert(item.texture=="druttzen_osm_vanilla::/osm/dirty_water.gtex","Invalid mapped-water construction")
        local protected=item.waterSurface=="flat" or item.waterSurface=="follow"
        assert(protected or (item.waterSurface==nil and item.depth==0.5),"Invalid mapped-water alignment")
        assert(#item.face==3,"Mapped water must be a triangle")
        local face={}
        for _,p in ipairs(item.face) do
          assert(type(p[3])=="number" and p[3]==p[3] and math.abs(p[3])<math.huge,"Invalid saved bed height")
          face[#face+1]={p[1]-origin[1],p[2]-origin[2],p[3],1}
        end
        -- TF3 needs one UV per point to render a construction ground fill.
        -- All UVs use the same material in the one-pixel Water Dirty mask.
        fill.texCoords={{0,0},{1,0},{0,1}}
        groundFace=face
        if protected then
          if item.waterSurface=="flat" then
            assert(face[1][3]==face[2][3] and face[2][3]==face[3][3],"Lake alignment must be flat")
          end
          local alignment=sub.terrainAlignmentLists[1]
          alignment.slopeLow=0.5
          alignment.slopeHigh=0.5
          alignment.faces[#alignment.faces+1]=face
        else
          sub.terrainAlignmentLists[#sub.terrainAlignmentLists+1]={type="LESS",faces={face},slopeLow=0.5,slopeHigh=0.5}
        end
      end
      sub.groundFaces[#sub.groundFaces+1] = {
        face = groundFace,
        modes = {fill},
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

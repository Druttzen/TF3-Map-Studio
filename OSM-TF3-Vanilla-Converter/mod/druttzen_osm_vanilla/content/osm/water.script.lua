local water=ug_require "druttzen_osm_vanilla::/osm/water.lua"
local script={}
function script.updateFn(_captureParams,params)
  local p=water.configure(nil,water.settings(params))
  local sub={tag=1,models={},groundFaces={},terrainAlignmentLists={{type="EQUAL",faces={}}}}
  for _,face in ipairs(water.faces(p)) do
    sub.models[#sub.models+1]={id=water.model,transf=water.transform(face)}
  end
  return {cost=0,maintenanceCost=0,noCostAtAll=true,
    metadata={druttzenOsmWater={experimental=true,navigable=false}},subconstructions={sub}}
end
function data() return script end

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
      sub.groundFaces[#sub.groundFaces+1] = {
        face = item.face,
        modes = {{type="FILL",key=item.texture}},
        loop = true,
      }
    end
  end
  return {
    cost = 0, maintenanceCost = 0, noCostAtAll = true,
    subconstructions = {sub},
  }
end

-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return script
end

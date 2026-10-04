-- GPL-3.0. Native TF3 mod button and scrollable command/settings panel.
local react=ug_require "::/gui/main/react.lua"
local builtin=ug_require "::/gui/main/builtin.lua"
local mainButtons=ug_require "::/gui/main/main_mod_button_area.tl"
local windows=ug_require "::/gui/main/game_react_globals.tl"
local polling=ug_require "::/gui/main/engine_react_util.tl"
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local uiSnapshot=ug_require "druttzen_osm_vanilla::/osm/ui_snapshot.lua"
local panelId="druttzen-osm-import-panel"
local result={}

local function send(command,param)
  api.cmd.sendCommand(api.cmd.makeScriptingSendEventCmd("OSM control panel","druttzen_osm_vanilla","osm."..command,param or {}))
end
local function text(value,class)
  if class and class:find("osm-import-note",1,true) then
    return builtin.RichTextView{meta={class=class},text=value,isHtml=false,isMarkdown=false}
  end
  return builtin.TextView{meta={class=class or "font-scale-body"},text=value}
end
local function close()
  local windowApi=windows.getDefaultWindowApi()
  if windowApi then windowApi.removeAllWindows(result.OsmImportPanel) end
end

-- WindowContainer needs the native Window identity, supplied by a wrapper recipe.
result.OsmImportPanel=react.RegisterWrapperRecipe("OsmImportPanel",builtin.Window,function()
  local snapshot=polling.useStepStateTimer(function()
    -- React recipes run with a read-only API. Native GUI scripts read a
    -- GameScript component directly instead of firing a GUI script event.
    local entity=api.engine.system.gameScriptSystem.getEntityForGameScript("druttzen_osm_vanilla::/osm/importer.gs")
    if not entity then return nil end
    local gameScript=api.engine.getComponent(entity,api.type.ComponentType.GAME_SCRIPT)
    if not gameScript then return nil end
    return uiSnapshot.fromState(gameScript.state,api.engine.terrain.getBoundingBox())
  end,0.25):old()
  if type(snapshot)~="table" or not snapshot.options then
    return builtin.Window{
      meta={class="osm-import-panel"},id=panelId,title="OSM Importer",closable=true,movable=true,
      onClose=close,content=text("Waiting for the importer to initialise. Close and reopen the panel if needed."),
    }
  end
  local ruleState={phase=snapshot.phase,datasetId=snapshot.started and snapshot.datasetId or nil,labels=snapshot.labels,builtTowns=snapshot.builtTowns,waterBusy=snapshot.waterBusy,waterBuilt=snapshot.waterBuilt,
    errorKind=snapshot.errorKind,datasetMatches=snapshot.datasetMatches,pendingAccepted=snapshot.pendingAccepted,
    acceptedUnjournalled=snapshot.acceptedUnjournalled}
  local rows={}
  local commandRows={}
  for _,command in ipairs(controls.commands) do
    local key=command.key
    commandRows[#commandRows+1]=builtin.Button{
      meta={id="druttzen-osm-command-"..key,localKey=key,class="osm-import-command",
        tooltip=command.help,enabled=controls.enabled(key,ruleState) and not (key=="waterBuild" and snapshot.waterBuilt)},
      content=text(command.label),onClick=function() send(key) end,
    }
  end
  rows[#rows+1]=text("What to import","font-scale-headline")
  rows[#rows+1]=text(snapshot.started and "Selections are saved and locked for this import." or "Choose the parts to build before pressing Start import.")
  if not snapshot.hasMappedObjectMetadata then
    rows[#rows+1]=text("This map file comes from an older converter. Reconvert the original XML for building outlines, extra objects and functioning-town tags. Keep the current file if this import has already started.","osm-import-note")
  end
  for _,category in ipairs(controls.categories) do
    local key=category.key
    rows[#rows+1]=builtin.CheckBox{
      meta={id="druttzen-osm-option-"..key,localKey=key,enabled=not snapshot.started and not snapshot.checking},
      label=category.label.." ("..tostring(snapshot.available[key] or 0)..")",value=snapshot.options[key] and 1 or 0,
      onValueChange=function(value) send("configure",{[key]=value==1}) end,
    }
  end
  rows[#rows+1]=text("Mapped object types present in this file","font-scale-headline")
  for _,kind in ipairs(controls.objectKinds) do
    local key="object_"..kind.key
    local count=snapshot.objectKinds[kind.key] or 0
    if count>0 then
      rows[#rows+1]=builtin.CheckBox{
        meta={id="druttzen-osm-option-"..key,localKey=key,enabled=not snapshot.started and not snapshot.checking},
        label=kind.label.." ("..tostring(count)..")",value=snapshot.options[key] and 1 or 0,
        onValueChange=function(value) send("configure",{[key]=value==1}) end,
      }
    end
  end
  rows[#rows+1]=text("Each object type also requires its category above to be selected.","osm-import-note")
  rows[#rows+1]=text("Object matching and town behaviour","font-scale-headline")
  for _,policy in ipairs(controls.policies) do
    local key=policy.key
    rows[#rows+1]=builtin.CheckBox{
      meta={id="druttzen-osm-option-"..key,localKey=key,enabled=not snapshot.started and not snapshot.checking},
      label=policy.label,value=snapshot.options[key] and 1 or 0,
      onValueChange=function(value) send("configure",{[key]=value==1}) end,
    }
  end
  rows[#rows+1]=text("Vanilla matches take priority. Only models loaded by active mods are searched. Building substitutes are decorative; they do not become simulated homes, stations or industries.","osm-import-note")
  rows[#rows+1]=text("Town creation can generate initial streets. Turning off new town roads freezes ALL automatic town growth, including buildings. This TF3 build has no verified road-only growth switch. Existing towns are unaffected.","osm-import-note")
  if snapshot.matchSummary then
    local m=snapshot.matchSummary
    rows[#rows+1]=text(string.format("Object check: %d vanilla, %d active mod, %d without a safe match (left unbuilt).",m.vanilla,m.mods,m.unmatched),"osm-import-note")
    for _,example in ipairs(m.examples) do rows[#rows+1]=text(example,"osm-import-note") end
  else rows[#rows+1]=text("Press Check map and match objects to preview the replacements before Start import.","osm-import-note") end
  for _,entry in ipairs(snapshot.unavailableObjects) do
    rows[#rows+1]=text(string.format("Kept for reference, no supported automatic build: %s (%d).",entry.tag,entry.count),"osm-import-note")
  end
  rows[#rows+1]=text("Commands","font-scale-headline")
  for _,row in ipairs(commandRows) do rows[#rows+1]=row end
  rows[#rows+1]=text("Adjust import pace","font-scale-headline")
  rows[#rows+1]=text("Automatically pause after successful build steps")
  rows[#rows+1]=text("One step builds one road/rail segment, one scenery batch or one marker. Resume starts another run.")
  local limits={}
  local limitPreset=false
  for _,limit in ipairs({0,10,100,1000,10000}) do
    if limit==snapshot.options.stepLimit then limitPreset=true end
    limits[#limits+1]=builtin.ComboBoxItem{value=limit,content=text(limit==0 and "No automatic pause" or tostring(limit).." steps")}
  end
  if not limitPreset then limits[#limits+1]=builtin.ComboBoxItem{value=snapshot.options.stepLimit,content=text(tostring(snapshot.options.stepLimit).." steps")} end
  rows[#rows+1]=builtin.ComboBox{
    meta={id="druttzen-osm-step-limit",class="osm-import-choice",enabled=not snapshot.checking},value=snapshot.options.stepLimit,items=limits,
    onValueChange=function(value) send("configure",{stepLimit=tonumber(value)}) end,
  }
  rows[#rows+1]=text("These settings can be changed while the import is running or paused.")
  rows[#rows+1]=text("Scenery items per step")
  local batches={}
  for _,size in ipairs({1,10,25,50,100}) do
    batches[#batches+1]=builtin.ComboBoxItem{value=size,content=text(tostring(size))}
  end
  -- A console-set valid size outside the presets is still displayed accurately.
  local preset=false
  for _,size in ipairs({1,10,25,50,100}) do if size==snapshot.options.batchSize then preset=true end end
  if not preset then batches[#batches+1]=builtin.ComboBoxItem{value=snapshot.options.batchSize,content=text(tostring(snapshot.options.batchSize))} end
  rows[#rows+1]=builtin.ComboBox{
    meta={id="druttzen-osm-batch",class="osm-import-choice"},value=snapshot.options.batchSize,items=batches,
    onValueChange=function(value) send("configure",{batchSize=tonumber(value)}) end,
  }
  rows[#rows+1]=text("Delay between steps (simulation seconds)")
  local delays={}
  for _,delay in ipairs({0,0.1,0.5,1,2}) do
    delays[#delays+1]=builtin.ComboBoxItem{value=delay,content=text(delay==0 and "Fastest" or tostring(delay).." seconds")}
  end
  preset=false
  for _,delay in ipairs({0,0.1,0.5,1,2}) do if delay==snapshot.options.interval then preset=true end end
  if not preset then delays[#delays+1]=builtin.ComboBoxItem{value=snapshot.options.interval,content=text(tostring(snapshot.options.interval).." seconds")} end
  rows[#rows+1]=builtin.ComboBox{
    meta={id="druttzen-osm-delay",class="osm-import-choice"},value=snapshot.options.interval,items=delays,
    onValueChange=function(value) send("configure",{interval=tonumber(value)}) end,
  }
  rows[#rows+1]=text("Dataset and map","font-scale-headline")
  rows[#rows+1]=text("Prepared area: "..tostring(snapshot.datasetWidth).." × "..tostring(snapshot.datasetHeight).." m")
  rows[#rows+1]=text(string.format("Current map: %.0f × %.0f m",snapshot.mapWidth,snapshot.mapHeight))
  rows[#rows+1]=text("Prepare or replace OSM data with the desktop converter while TF3 is closed.")
  rows[#rows+1]=text("Signals and functioning towns use the vanilla game tools. Read marker names with Show place names.")
  rows[#rows+1]=text("New imports use base terrain heights for roads/rails, excluding construction terrain alignments. Explicit sourced heights in game coordinates take priority. Terrain alignment occurs through the road/rail build proposal.")
  rows[#rows+1]=text("Mapped water","font-scale-headline")
  rows[#rows+1]=text(string.format("Prepared water features: %d. Lakes retained without flooding: %d.",snapshot.mappedWaterCount,snapshot.mappedLakeCount))
  rows[#rows+1]=text("Small mapped waters use the original OSM outlines and Water Dirty. Start import lowers their bed by 0.5 m. Missing stream widths use the configured approximation. Reconvert older OSM datasets with Preview 0.12 to include water metadata. Local sea level is not supported; lakes remain pending. Use a separate test map: this shallow-water version needs native validation.")
  rows[#rows+1]=text("Experimental elevated water surface","font-scale-headline")
  rows[#rows+1]=text("Use a separate test save. Each rectangular patch is decorative water. Equal start/end heights make a flat lake surface; different heights test a sloping stream surface. Coordinates and heights are game metres. Prepare another water patch retains completed objects and unlocks the next settings. Recorded patches cannot overlap. Ship navigation is not established.")
  local editable=controls.enabled("waterBuild",ruleState) and not snapshot.waterBuilt
  local fields={
    {key="x",label="Centre X",min=-20000,max=20000},{key="y",label="Centre Y",min=-20000,max=20000},
    {key="level",label="Water start height",min=-20000,max=20000},{key="endLevel",label="Water end height",min=-20000,max=20000},
    {key="length",label="Length along X (metres)",min=1,max=100},{key="width",label="Width along Y (metres)",min=1,max=100},
  }
  for _,field in ipairs(fields) do
    local key=field.key
    rows[#rows+1]=text(field.label)
    rows[#rows+1]=builtin.DoubleSpinBox{
      meta={id="druttzen-osm-water-"..key,localKey="water-"..key,enabled=editable},
      value=snapshot.waterSettings[key],min=field.min,max=field.max,
      onValueChange=function(v) send("waterConfigure",{[key]=v}) end,
    }
  end
  rows[#rows+1]=text("Mapped ponds and small waterways use a 0.5 m shallow bed and Landscaping Water Dirty through Start import. Existing and planned network corridors are protected. Elevated model water is a separate surface-only test; experimental basin shaping is disabled after native terrain spikes. Lakes retain their OSM metadata; a local sea level is not supported by the installed API.")
  if #snapshot.warnings>0 then
    rows[#rows+1]=text("Conversion notes","font-scale-headline")
    for i,warning in ipairs(snapshot.warnings) do
      rows[#rows+1]=builtin.RichTextView{meta={localKey="warning-"..i,class="osm-import-note, font-scale-body"},text=warning,isHtml=false,isMarkdown=false}
    end
  end
  local header={
    text("Status: "..snapshot.phase,"font-scale-headline"),
    text(string.format("Roads / rails: %d / %d    Scenery: %d / %d    Markers: %d / %d",
      snapshot.builtEdges,snapshot.totals.edges,snapshot.builtScenery,snapshot.totals.scenery,snapshot.labels,snapshot.totals.labels)),
    text("Skipped steps: "..snapshot.skipped),
    text(string.format("Functioning towns: %d / %d",snapshot.builtTowns,snapshot.totals.towns)),
    text("Recorded experimental water patches: "..snapshot.waterCount),
  }
  if snapshot.error then header[#header+1]=text(snapshot.error,"osm-import-note, font-scale-body") end
  if snapshot.notice then header[#header+1]=text(snapshot.notice,"osm-import-note, font-scale-body") end
  return builtin.Window{
    meta={class="osm-import-panel"},id=panelId,title="TF3 OSM Importer",closable=true,movable=true,
    onClose=close,initialX=40,initialY=80,
    content=builtin.BoxLayout{
      orientation=builtin.type.Orientation.Vertical,
      children={
        builtin.ScrollArea{
          meta={id="druttzen-osm-status-scroll",class="osm-import-status-scroll"},
          horizontalPolicy=builtin.type.ScrollBarPolicy.AlwaysOff,verticalPolicy=builtin.type.ScrollBarPolicy.AsNeeded,
          content=builtin.Component{meta={class="osm-import-status"},layout=builtin.BoxLayout{
            orientation=builtin.type.Orientation.Vertical,children=header}},
        },
        builtin.ScrollArea{
          meta={id="druttzen-osm-scroll",class="osm-import-scroll"},
          horizontalPolicy=builtin.type.ScrollBarPolicy.AlwaysOff,verticalPolicy=builtin.type.ScrollBarPolicy.AsNeeded,
          content=builtin.Component{meta={class="osm-import-list"},layout=builtin.BoxLayout{
            orientation=builtin.type.Orientation.Vertical,children=rows}},
        },
      },
    },
  }
end)

result.OsmImportButton=react.RegisterPluginRecipe(mainButtons.MainModButtonAreaExtension,"OsmImportButton",function()
  -- MainModButtonArea inserts plugin recipes into a layout; recipe roots must
  -- be layouts too, otherwise TF3 rejects the entire native interface.
  return builtin.BoxLayout{
    children={builtin.Button{
      meta={id="druttzen-osm-open",class="osm-import-open",tooltip="Open OSM import commands, progress and settings"},
      content=text("OSM Import"),
      onClick=function()
        local windowApi=windows.getDefaultWindowApi()
        if not windowApi then return end
        if api.gui.byId.isVisible(panelId) then close()
        else windowApi.addSingletonWindow(result.OsmImportPanel,{}) end
      end,
    }},
  }
end)
-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return result
end

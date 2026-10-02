-- GPL-3.0. Native TF3 mod button and scrollable command/settings panel.
local react=ug_require "::/gui/main/react.lua"
local builtin=ug_require "::/gui/main/builtin.lua"
local mainButtons=ug_require "::/gui/main/main_mod_button_area.tl"
local windows=ug_require "::/gui/main/game_react_globals.tl"
local polling=ug_require "::/gui/main/engine_react_util.tl"
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
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

result.OsmImportPanel=react.RegisterRecipe("OsmImportPanel",function()
  local snapshot=polling.useStepStateTimer(function()
    return api.gui.fireGuiScriptEvent("druttzen_osm_vanilla","osm.ui.snapshot",{})
  end,0.25):old()
  if type(snapshot)~="table" or not snapshot.options then
    return builtin.Window{
      meta={class="osm-import-panel"},id=panelId,title="OSM Importer",closable=true,movable=true,
      onClose=close,content=text("Waiting for the importer to initialise. Close and reopen the panel if needed."),
    }
  end
  local ruleState={phase=snapshot.phase,datasetId=snapshot.started and snapshot.datasetId or nil}
  local rows={text("Commands","font-scale-headline")}
  for _,command in ipairs(controls.commands) do
    local key=command.key
    rows[#rows+1]=builtin.Button{
      meta={id="druttzen-osm-command-"..key,localKey=key,class="osm-import-command",
        tooltip=command.help,enabled=controls.enabled(key,ruleState)},
      content=text(command.label),onClick=function() send(key) end,
    }
  end
  rows[#rows+1]=text("What to import","font-scale-headline")
  rows[#rows+1]=text(snapshot.started and "Selections are saved and locked for this import." or "Choose the parts to build before pressing Start import.")
  for _,category in ipairs(controls.categories) do
    local key=category.key
    rows[#rows+1]=builtin.CheckBox{
      meta={id="druttzen-osm-option-"..key,localKey=key,enabled=not snapshot.started},
      label=category.label,value=snapshot.options[key] and 1 or 0,
      onValueChange=function(value) send("configure",{[key]=value==1}) end,
    }
  end
  rows[#rows+1]=text("Adjust import pace","font-scale-headline")
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
  rows[#rows+1]=text("Signals and functioning towns use the vanilla game tools. Place names use markers.")
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
  }
  if snapshot.error then header[#header+1]=text(snapshot.error,"osm-import-note, font-scale-body") end
  if snapshot.notice then header[#header+1]=text(snapshot.notice,"osm-import-note, font-scale-body") end
  return builtin.Window{
    meta={class="osm-import-panel"},id=panelId,title="OSM Importer · Vanilla",closable=true,movable=true,
    onClose=close,initialX=40,initialY=80,
    content=builtin.BoxLayout{
      orientation=builtin.type.Orientation.Vertical,
      children={
        builtin.Component{meta={class="osm-import-status"},layout=builtin.BoxLayout{children=header}},
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
  return builtin.Button{
    meta={id="druttzen-osm-open",class="osm-import-open",tooltip="Open OSM import commands, progress and settings"},
    content=text("OSM Import"),
    onClick=function()
      local windowApi=windows.getDefaultWindowApi()
      if not windowApi then return end
      if api.gui.byId.isVisible(panelId) then close()
      else windowApi.addSingletonWindow(result.OsmImportPanel,{}) end
    end,
  }
end)
-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return result
end

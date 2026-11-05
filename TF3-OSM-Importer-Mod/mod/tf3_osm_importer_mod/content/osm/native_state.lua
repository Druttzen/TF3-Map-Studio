-- GPL-3.0. Transactional, lazy access to TF3's documented NativeLuaTable state.
-- GameScriptState.get_native/set_native and NativeLuaTable.clone/find/insert
-- avoid materializing every saved node, match and model position on each step.
local bridge={}

function bridge.open(nativeState)
  if not nativeState.get_native or not nativeState.set_native then
    local current=nativeState:get()
    return {
      get=function() return current end,
      set=function(_,value) current=value; nativeState:set(value) end,
      hasEventSubscriptions=function() return nativeState:hasEventSubscriptions() end,
      subscribeToEvent=function(_,name) nativeState:subscribeToEvent(name) end,
    }
  end

  local proxies=setmetatable({},{__mode="k"})
  local wrap,flush,plain
  local function nativeTable(value)
    return (type(value)=="userdata" or type(value)=="table") and value.find and value.clone
  end
  plain=function(value,seen)
    if type(value)~="table" then return value end
    seen=seen or {}
    assert(not seen[value],"A saved import table contains a cycle")
    seen[value]=true
    local result={}
    for key,item in pairs(value) do result[key]=plain(item,seen) end
    seen[value]=nil
    return result
  end
  flush=function(proxy)
    local info=assert(proxies[proxy])
    if not next(info.dirty) then return info.native end
    -- Clone first. A failed command/commit must not mutate a table retained
    -- by the game's previous saved state, including nested journal records.
    local result=info.native:clone()
    for key in pairs(info.dirty) do
      local value=info.cache[key]
      if value==nil then result:remove(key)
      elseif proxies[value] then result:insert_native(key,flush(value))
      else result:insert(key,plain(value)) end
    end
    info.native=result
    -- Keep dirty entries through this synchronous callback. Locally created
    -- tables may still be modified by an accepted-command finalizer after
    -- its first durable checkpoint; the next commit must include those edits.
    return result
  end
  wrap=function(native,onChange)
    local proxy={}
    local info={native=native,cache={},known={},dirty={},added={},addedKnown={}}
    proxies[proxy]=info
    local function mark(key)
      info.dirty[key]=true
      if onChange then onChange() end
    end
    return setmetatable(proxy,{
      __index=function(_,key)
        if not info.known[key] then
          local value=info.native:find(key)
          if nativeTable(value) then value=wrap(value,function() mark(key) end) end
          info.cache[key]=value; info.known[key]=true
        end
        return info.cache[key]
      end,
      __newindex=function(_,key,value)
        if not info.addedKnown[key] and info.native:find(key)==nil then
          info.addedKnown[key]=true; info.added[#info.added+1]=key
        end
        info.cache[key]=value; info.known[key]=true; mark(key)
      end,
      __len=function()
        local size=info.native:size()
        for key in pairs(info.dirty) do
          local before=info.native:find(key)~=nil
          local after=info.cache[key]~=nil
          if before~=after then size=size+(after and 1 or -1) end
        end
        return size
      end,
      __pairs=function()
        local base=info.native
        local key,finished,added=nil,false,0
        return function()
          while not finished do
            key=base:next(key)
            if key==nil then finished=true
            elseif proxy[key]~=nil then return key,proxy[key] end
          end
          while added<#info.added do
            added=added+1
            local newKey=info.added[added]
            if base:find(newKey)==nil and proxy[newKey]~=nil then return newKey,proxy[newKey] end
          end
        end
      end,
    })
  end

  local persisted=nativeState:get_native()
  local root=wrap(persisted)
  return {
    get=function() return root end,
    set=function(_,value)
      if value~=root or not proxies[root] then
        local replacement=persisted:clone()
        local key=replacement:next()
        while key~=nil do
          local following=replacement:next(key)
          replacement:remove(key); key=following
        end
        for name,item in pairs(value) do
          if proxies[item] then replacement:insert_native(name,flush(item))
          else replacement:insert(name,plain(item)) end
        end
        nativeState:set_native(replacement)
        persisted=replacement
        -- Preserve the caller's new table identity for later local edits.
        -- Subsequent commits of this ordinary replacement are uncommon
        -- initialization paths; native proxy commits resume next callback.
        root=value
      else
        local replacement=flush(root)
        nativeState:set_native(replacement); persisted=replacement
      end
    end,
    hasEventSubscriptions=function() return nativeState:hasEventSubscriptions() end,
    subscribeToEvent=function(_,name) nativeState:subscribeToEvent(name) end,
  }
end

return bridge

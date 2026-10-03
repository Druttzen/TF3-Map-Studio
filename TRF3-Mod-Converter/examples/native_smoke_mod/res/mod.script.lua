local helper = ug_require "mapstudio_converter_smoke_030::/helper.lua"

function data()
    return {
        preRunFn = function(configDict, allModParams, baseConfig)
            print("TF3_MAPSTUDIO_CONVERTER_030_PRE_OBSERVED config=" .. type(configDict) .. " params=" .. type(allModParams) .. " base=" .. type(baseConfig))
        end,
        runFn = function(configDict, allModParams)
            local params = allModParams[getCurrentModId()]
            -- Build 40408 supplies the selected 1-based option index here, even
            -- with numbers=[7.0]. Preserve and report that observed distinction.
            assert(params and params.mode == 1, "Converted mod parameter missing or changed")
            assert(helper.marker == "helper_ok", "Converted local helper reference failed")
            print("TF3_MAPSTUDIO_CONVERTER_030_RUN_OK mode=" .. params.mode .. " helper=" .. helper.marker .. " config=" .. type(configDict))
        end,
        postRunFn = function(configDict, allModParams)
            local params = allModParams[getCurrentModId()]
            assert(params and params.mode == 1, "Converted postRun parameter missing or changed")
            print("TF3_MAPSTUDIO_CONVERTER_030_POST_OK mode=" .. params.mode .. " helper=" .. helper.marker)
        end,
    }
end

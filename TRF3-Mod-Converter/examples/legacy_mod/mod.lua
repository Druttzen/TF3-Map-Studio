-- Static legacy metadata; no executable callbacks.
function data()
    return {
        info = {
            name = "Example Mod",
            description = [[
A small example for the TRF3 metadata converter.
Use your own mod folder to convert real resources.]],
            minorVersion = 1,
            authors = { { name = "Example Creator", role = "CREATOR" } },
            tags = { "Misc" },
            severityAdd = "NONE",
            severityRemove = "WARNING"
        }
    }
end

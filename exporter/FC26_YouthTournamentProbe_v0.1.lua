-- FC26 Youth Tournament Probe v0.1
-- Read-only diagnostic for discovering CareerModeEvent IDs around youth 5x5.
-- Logs event phase, ID and name only. It does not inspect event payloads,
-- access career database tables, read/write game memory, or alter the save.

require 'imports/career_mode/helpers'

assert(IsInCM(), "FC26 Youth Tournament Probe must be executed while a career is loaded")

local STATE_KEY = "FC26_YOUTH_TOURNAMENT_PROBE_STATE"
local previous = rawget(_G, STATE_KEY)

if previous then
    if previous.pre_handler and type(RemoveEventHandler) == "function" then
        pcall(RemoveEventHandler, previous.pre_handler)
    end
    if previous.post_handler and type(RemoveEventHandler) == "function" then
        pcall(RemoveEventHandler, previous.post_handler)
    end
end

local state = {active = true}
rawset(_G, STATE_KEY, state)

local function safe_event_name(event_id)
    if type(GetCMEventNameByID) ~= "function" then
        return "name_lookup_unavailable"
    end

    local ok, result = pcall(GetCMEventNameByID, event_id)
    if not ok then
        return "name_lookup_error"
    end
    if result == nil then
        return "unknown"
    end
    return tostring(result):gsub("[\r\n|]", "_")
end

local function log_event(phase, _, event_id, _)
    if not state.active then
        return
    end

    local id = tonumber(event_id)
    local id_text = id and tostring(id) or tostring(event_id or "unknown")
    local line = string.format(
        "[YOUTH_PROBE] %s | event_id=%s | event_name=%s | at=%s",
        phase,
        id_text,
        safe_event_name(id or event_id),
        os.date("%Y-%m-%d %H:%M:%S")
    )

    if LOGGER and LOGGER.LogInfo then
        pcall(function() LOGGER:LogInfo(line) end)
    end
end

local ok, result = pcall(
    AddEventHandler,
    "pre__CareerModeEvent",
    function(events_manager, event_id, event)
        log_event("pre", events_manager, event_id, event)
    end
)
if ok then
    state.pre_handler = result
else
    state.active = false
    rawset(_G, STATE_KEY, nil)
    error("Could not register pre__CareerModeEvent: " .. tostring(result))
end

ok, result = pcall(
    AddEventHandler,
    "post__CareerModeEvent",
    function(events_manager, event_id, event)
        log_event("post", events_manager, event_id, event)
    end
)
if ok then
    state.post_handler = result
else
    state.active = false
    if state.pre_handler and type(RemoveEventHandler) == "function" then
        pcall(RemoveEventHandler, state.pre_handler)
    end
    rawset(_G, STATE_KEY, nil)
    error("Could not register post__CareerModeEvent: " .. tostring(result))
end

if LOGGER and LOGGER.LogInfo then
    pcall(function()
        LOGGER:LogInfo("[YOUTH_PROBE] started; logging pre/post career event IDs and names only")
    end)
end

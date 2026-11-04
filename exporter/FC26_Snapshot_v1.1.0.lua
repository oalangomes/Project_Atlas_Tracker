-- FC26 Snapshot v1.1.0
-- Production community snapshot exporter for Project Atlas Tracker.
-- Read-only; writes one atomic career snapshot to Documents\FC26 Export\Snapshots.


local MEMORY = require 'imports/core/memory'
require 'imports/other/helpers'
require 'imports/services/enums'
require 'imports/career_mode/helpers'

assert(IsInCM(), "FC26 Snapshot Exporter must be executed while a career is loaded")

local EXPORTER_VERSION = "1.1.0"
local SCHEMA_VERSION = "1.2.0"
local CSV_BOM = "\239\187\191"
local LOG_LINES = {}
local TABLE_CACHE = {}
local MISSING_FIELD_LOGGED = {}
local UNAVAILABLE_FIELDS = {}
-- Current FC26 builds do not expose players.joindate via GetRecordFieldValue.
-- Live Editor logs a native "no field" error even when Lua receives nil, so
-- probing this field per player would flood the console. Skip it explicitly.
local KNOWN_UNAVAILABLE_FIELDS = {
    ["players.joindate"] = true,
}
local MANIFEST_ROWS = {}
local SNAPSHOT_CONTEXT = {}
local TEAM_PROFITABILITY_EXPORTED = false
local TEAM_PROFITABILITY_NONEMPTY_COUNT = 0
local TEAM_PROFITABILITY_TOTAL_TEAMS = 0

local function now_text()
    return os.date("%Y-%m-%d %H:%M:%S")
end

local function now_iso_local()
    return os.date("%Y-%m-%dT%H:%M:%S%z")
end

local function now_iso_utc()
    return os.date("!%Y-%m-%dT%H:%M:%SZ")
end

local function log(message)
    local line = string.format("[%s] %s", now_text(), tostring(message))
    table.insert(LOG_LINES, line)
    if LOGGER and LOGGER.LogInfo then
        pcall(function() LOGGER:LogInfo(line) end)
    end
end

local function trim(value)
    if value == nil then
        return ""
    end
    local text = tostring(value)
    text = text:gsub("^\239\187\191", "")
    text = text:gsub("^%s+", ""):gsub("%s+$", "")
    return text
end

local function command_succeeded(a, _, c)
    if a == true then
        return true
    end
    if type(a) == "number" then
        return a == 0
    end
    return c == 0
end

local function ensure_dir(path)
    local a, b, c = os.execute('if not exist "' .. path .. '" mkdir "' .. path .. '"')
    if not command_succeeded(a, b, c) then
        error("Could not create directory: " .. path)
    end
end

local function resolve_export_root()
    local user_profile = os.getenv("USERPROFILE")
    assert(type(user_profile) == "string" and user_profile ~= "",
        "USERPROFILE environment variable is unavailable.")
    return user_profile .. "\\Documents\\FC26 Export\\Snapshots",
        "community_fixed_path", false
end

local function random_hex(length)
    local chars = "0123456789abcdef"
    local result = {}
    for i = 1, length do
        local index = math.random(1, #chars)
        result[i] = chars:sub(index, index)
    end
    return table.concat(result)
end

math.randomseed(os.time() + math.floor(os.clock() * 1000000))

local EXPORT_ROOT, EXPORT_CONFIG_SOURCE, EXPORT_ROOT_IS_FALLBACK = resolve_export_root()
local INCOMING_ROOT = EXPORT_ROOT .. "\\incoming"
local READY_ROOT = EXPORT_ROOT .. "\\ready"
local IMPORTED_ROOT = EXPORT_ROOT .. "\\imported"
local FAILED_ROOT = EXPORT_ROOT .. "\\failed"
local SNAPSHOT_ID = os.date("!%Y%m%dT%H%M%SZ") .. "-" .. random_hex(16)
local SNAPSHOT_FOLDER_NAME = "snapshot_" .. os.date("%Y%m%d_%H%M%S") .. "_" .. SNAPSHOT_ID:sub(-8)
local PARTIAL_DIR = INCOMING_ROOT .. "\\" .. SNAPSHOT_FOLDER_NAME .. ".partial"
local READY_DIR = READY_ROOT .. "\\" .. SNAPSHOT_FOLDER_NAME
local output_dir = PARTIAL_DIR

ensure_dir(EXPORT_ROOT)
ensure_dir(INCOMING_ROOT)
ensure_dir(READY_ROOT)
ensure_dir(IMPORTED_ROOT)
ensure_dir(FAILED_ROOT)
ensure_dir(PARTIAL_DIR)

local function get_file_size(path)
    local file = io.open(path, "rb")
    if not file then
        return 0
    end
    local size = file:seek("end") or 0
    file:close()
    return size
end

local function fnv1a32(text)
    local hash = 2166136261
    local value = tostring(text or "")
    for i = 1, #value do
        hash = ((hash ~ value:byte(i)) * 16777619) & 0xFFFFFFFF
    end
    return hash
end

local function json_escape(value)
    local text = tostring(value or "")
    text = text:gsub("\\", "\\\\")
    text = text:gsub('"', '\\"')
    text = text:gsub("\b", "\\b")
    text = text:gsub("\f", "\\f")
    text = text:gsub("\n", "\\n")
    text = text:gsub("\r", "\\r")
    text = text:gsub("\t", "\\t")
    return text
end

local function json_string(value)
    return '"' .. json_escape(value) .. '"'
end

local function json_number(value, default_value)
    local number = tonumber(value)
    if number == nil then
        return tostring(default_value or 0)
    end
    return tostring(number)
end

local function write_ready_marker(directory)
    local path = directory .. "\\READY"
    local file, err = io.open(path, "wb")
    if not file then
        error("Could not create READY marker: " .. tostring(err))
    end
    file:write("schema_version=" .. SCHEMA_VERSION .. "\r\n")
    file:write("snapshot_id=" .. SNAPSHOT_ID .. "\r\n")
    file:write("completed_at_utc=" .. now_iso_utc() .. "\r\n")
    file:close()
end

local function move_directory(source, destination)
    local ok, err = os.rename(source, destination)
    if ok then
        return true
    end

    local a, b, c = os.execute('move /Y "' .. source .. '" "' .. destination .. '" >NUL')
    if command_succeeded(a, b, c) then
        return true
    end
    return false, err
end

local function csv_escape(value)
    if value == nil then
        return ""
    end

    local text = tostring(value)
    if string.find(text, '[,"\r\n]') then
        text = '"' .. string.gsub(text, '"', '""') .. '"'
    end
    return text
end

local function write_csv_row(file, values)
    local escaped = {}
    for i = 1, #values do
        escaped[i] = csv_escape(values[i])
    end
    file:write(table.concat(escaped, ","))
    file:write("\r\n")
end

local function open_csv(filename, columns)
    local path = output_dir .. "\\" .. filename
    local file, err = io.open(path, "wb")
    if not file then
        error("Could not create " .. path .. ": " .. tostring(err))
    end

    file:write(CSV_BOM)
    write_csv_row(file, columns)
    return file, path
end

local function add_manifest(filename, row_count, status, note)
    table.insert(MANIFEST_ROWS, {
        filename,
        row_count or 0,
        status or "ok",
        note or "",
        get_file_size(output_dir .. "\\" .. filename)
    })
end

local function get_table(table_name)
    if TABLE_CACHE[table_name] ~= nil then
        return TABLE_CACHE[table_name]
    end

    local ok, result = pcall(function()
        return LE.db:GetTable(table_name)
    end)

    if not ok or result == nil then
        TABLE_CACHE[table_name] = false
        log("Table unavailable: " .. table_name .. " (" .. tostring(result) .. ")")
        return nil
    end

    TABLE_CACHE[table_name] = result
    return result
end

local function get_field(table_name, db_table, record, field_name, default_value)
    local key = table_name .. "." .. field_name
    if KNOWN_UNAVAILABLE_FIELDS[key] or UNAVAILABLE_FIELDS[key] then
        return default_value
    end

    local ok, value = pcall(function()
        return db_table:GetRecordFieldValue(record, field_name)
    end)

    if not ok then
        UNAVAILABLE_FIELDS[key] = true
        if not MISSING_FIELD_LOGGED[key] then
            MISSING_FIELD_LOGGED[key] = true
            log("Field unavailable: " .. key .. " (disabled for this export run)")
        end
        return default_value
    end

    if value == nil then
        return default_value
    end
    return value
end

local function iterate_table(table_name, callback)
    local db_table = get_table(table_name)
    if not db_table then
        return 0, "table_unavailable"
    end

    local ok_first, current_record = pcall(function()
        return db_table:GetFirstRecord()
    end)

    if not ok_first then
        log("Could not read first record from " .. table_name .. ": " .. tostring(current_record))
        return 0, "read_error"
    end

    local count = 0
    while current_record and current_record > 0 do
        callback(db_table, current_record, count + 1)
        count = count + 1

        local ok_next, next_record = pcall(function()
            return db_table:GetNextValidRecord()
        end)
        if not ok_next then
            log("Could not read next record from " .. table_name .. ": " .. tostring(next_record))
            return count, "read_error"
        end
        current_record = next_record
    end

    return count, "ok"
end

local function is_positive_id(value)
    local number = tonumber(value)
    return number ~= nil and number > 0 and number < 4294967295
end

local function safe_player_name(player_id)
    if not is_positive_id(player_id) then
        return ""
    end

    local ok, name = pcall(function()
        return GetPlayerName(tonumber(player_id))
    end)

    if ok and name ~= nil then
        return tostring(name)
    end
    return ""
end

local function safe_team_name(team_id)
    if not is_positive_id(team_id) then
        return ""
    end

    local ok, name = pcall(function()
        return GetTeamName(tonumber(team_id))
    end)

    if ok and name ~= nil then
        return tostring(name)
    end
    return ""
end

local function safe_player_team_id(player_id)
    if not is_positive_id(player_id) then
        return 0
    end

    local ok, team_id = pcall(function()
        return GetTeamIdFromPlayerId(tonumber(player_id))
    end)

    if ok and team_id ~= nil then
        return team_id
    end
    return 0
end

local function safe_football_position_name(position_id)
    local number = tonumber(position_id)
    if number == nil or number < 0 or number >= 28 then
        return ""
    end

    local ok, name = pcall(function()
        return GetPlayerPrimaryPositionName(number)
    end)

    if ok and name ~= nil then
        local text = tostring(name)
        if text ~= "INVALID" then
            return text
        end
    end
    return ""
end

local function teamsheet_slot_label(slot_id)
    local number = tonumber(slot_id)
    if number == 28 then
        return "SUB"
    elseif number == 29 then
        return "RES"
    end
    return safe_football_position_name(number)
end

local function get_game_date()
    local ok, date = pcall(function()
        return GetCurrentDate()
    end)

    if not ok or date == nil then
        return "", "", ""
    end

    return date.year or "", date.month or "", date.day or ""
end


local function safe_competition_name(comp_object_id)
    local number = tonumber(comp_object_id)
    if number == nil or number <= 0 then
        return ""
    end

    local ok, name = pcall(function()
        return GetCompetitionNameByObjID(number)
    end)

    if ok and name ~= nil then
        local text = tostring(name)
        if text ~= "" then
            return text
        end
    end
    return ""
end

-- EA career dates are stored as elapsed days since 1582-10-14.
-- 1970-01-01 is day 141428 in that system.
local function days_since_1970_to_civil(z)
    z = math.floor(tonumber(z) or 0)
    z = z + 719468
    local era
    if z >= 0 then
        era = z // 146097
    else
        era = (z - 146096) // 146097
    end
    local doe = z - era * 146097
    local yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    local year = yoe + era * 400
    local doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    local mp = (5 * doy + 2) // 153
    local day = doy - (153 * mp + 2) // 5 + 1
    local month = mp + (mp < 10 and 3 or -9)
    year = year + (month <= 2 and 1 or 0)
    return year, month, day
end

local function ea_day_to_iso(raw_value)
    local raw = tonumber(raw_value)
    if raw == nil or raw <= 0 then
        return ""
    end

    -- Some match-related structures use YYYYMMDD directly.
    if raw >= 19000101 and raw <= 25001231 then
        local year = raw // 10000
        local month = (raw // 100) % 100
        local day = raw % 100
        if month >= 1 and month <= 12 and day >= 1 and day <= 31 then
            return string.format("%04d-%02d-%02d", year, month, day)
        end
    end

    local year, month, day = days_since_1970_to_civil(raw - 141428)
    if year < 1900 or year > 2500 then
        return ""
    end
    return string.format("%04d-%02d-%02d", year, month, day)
end

local function fixture_time_to_text(raw_value)
    local raw = tonumber(raw_value)
    if raw == nil or raw < 0 or raw > 2359 then
        return ""
    end

    -- Fixture memory stores time as HHMM (for example 1245 or 2000).
    local hour = raw // 100
    local minute = raw % 100
    if hour > 23 or minute > 59 then
        return ""
    end
    return string.format("%02d:%02d", hour, minute)
end

local function normalize_penalty_score(raw_value)
    local value = tonumber(raw_value)
    if value == nil or value == 255 then
        return ""
    end
    return value
end

local function make_fixture_key(fixture, home_team_id, away_team_id)
    return table.concat({
        tostring(fixture.competition_object_id or ""),
        tostring(fixture.date_raw or ""),
        tostring(home_team_id or ""),
        tostring(away_team_id or ""),
        tostring(fixture.match_group_id or ""),
        tostring(fixture.fixture_id or "")
    }, ":")
end

local function result_from_managed_perspective(is_completed, side, home_score, away_score)
    if not is_completed or (side ~= "HOME" and side ~= "AWAY") then
        return ""
    end

    local home = tonumber(home_score)
    local away = tonumber(away_score)
    if home == nil or away == nil then
        return ""
    end

    local managed_score = side == "HOME" and home or away
    local opponent_score = side == "HOME" and away or home
    if managed_score > opponent_score then
        return "W"
    elseif managed_score < opponent_score then
        return "L"
    end
    return "D"
end

local function get_fce_data_manager()
    local interface = GetPlugin(ENUM_djb2IFCEInterface_CLSS)
    return MEMORY:ReadMultilevelPointer(interface, {0x18, 0x10, 0x08, 0x00})
end

local function read_valid_standings()
    local result = {}
    local manager = get_fce_data_manager()
    local list = MEMORY:ReadPointer(manager + 0x88)
    local item_size = 0x18
    local begin_ptr = MEMORY:ReadPointer(list + 0x28)
    local max_items = MEMORY:ReadInt(list + 0x1C) - 1

    for index = 0, max_items do
        local current = begin_ptr + (item_size * index)
        local is_used = MEMORY:ReadBool(current + 0x16)
        local team_id = MEMORY:ReadInt(current + 0x04)
        if is_used and team_id > 0 then
            result[index] = {
                id = MEMORY:ReadShort(current + 0x00),
                competition_object_id = MEMORY:ReadShort(current + 0x02),
                team_id = team_id,
                team_index = MEMORY:ReadChar(current + 0x08)
            }
        end
    end
    return result
end

local function read_valid_fixtures()
    local result = {}
    local manager = get_fce_data_manager()
    local list = MEMORY:ReadPointer(manager + 0x60)
    local item_size = 0x18
    local begin_ptr = MEMORY:ReadPointer(list + 0x28)
    local max_items = MEMORY:ReadInt(list + 0x1C) - 1

    for index = 0, max_items do
        local current = begin_ptr + (item_size * index)
        local is_used = MEMORY:ReadBool(current + 0x14)
        if is_used then
            table.insert(result, {
                date_raw = MEMORY:ReadInt(current + 0x00),
                time_raw = MEMORY:ReadShort(current + 0x04),
                fixture_id = MEMORY:ReadShort(current + 0x06),
                competition_object_id = MEMORY:ReadShort(current + 0x08),
                home_standing_index = MEMORY:ReadShort(current + 0x0A),
                away_standing_index = MEMORY:ReadShort(current + 0x0C),
                match_group_id = MEMORY:ReadChar(current + 0x0E),
                home_score = MEMORY:ReadChar(current + 0x0F),
                home_penalties = MEMORY:ReadChar(current + 0x10),
                away_score = MEMORY:ReadChar(current + 0x11),
                away_penalties = MEMORY:ReadChar(current + 0x12),
                completed = MEMORY:ReadBool(current + 0x13)
            })
        end
    end
    return result
end

local function run_export()
    log("FC26 Snapshot v" .. EXPORTER_VERSION .. " started")
    log("Export root: " .. EXPORT_ROOT)
    log("Config source: " .. EXPORT_CONFIG_SOURCE)
    log("Partial output directory: " .. output_dir)

    local leagues_by_id = {}
    local team_league_by_id = {}
    local teams_by_id = {}
    local players_by_id = {}
    local competitions_by_object_id = {}
    local fixture_competition_id_by_fixture_id = {}
    local fixture_stadium_id_by_fixture_id = {}
    local all_player_stats = nil
    local match_rating_rows = {}
    local managed_team_fixtures = {}
    local managed_team_fixtures_by_date = {}
    local managed_last_match_positions = {}
    local managed_completed_fixture_count = 0
    local global_completed_fixture_count = 0
    local latest_managed_completed_date_raw = 0

    local function register_competition(comp_object_id, source, preferred_name, static_competition_id)
        local number = tonumber(comp_object_id)
        if number == nil or number <= 0 then
            return
        end
        local item = competitions_by_object_id[number]
        if item == nil then
            local resolved_name = preferred_name or ""
            if resolved_name == "" then
                resolved_name = safe_competition_name(number)
            end
            item = {
                competition_object_id = number,
                competition_name = resolved_name,
                competition_id = tonumber(static_competition_id),
                sources = {}
            }
            competitions_by_object_id[number] = item
        elseif (item.competition_name == nil or item.competition_name == "") and preferred_name and preferred_name ~= "" then
            item.competition_name = preferred_name
        end
        local static_number = tonumber(static_competition_id)
        if static_number and static_number > 0 then
            if item.competition_id == nil then
                item.competition_id = static_number
            elseif item.competition_id ~= static_number then
                item.competition_id_conflict = true
            end
        end
        if source and source ~= "" then
            item.sources[source] = true
        end
    end

    -- Static competition IDs are the IDs used by EA media files such as l20.png and t20.png.
    -- Career memory exposes a different competition object ID. The fixtures database table
    -- provides the crosswalk through fixtureid. Missing tables are tolerated.
    do
        local _, mapping_status = iterate_table("fixtures", function(tbl, record)
            local fixture_id = tonumber(get_field("fixtures", tbl, record, "fixtureid", ""))
            local competition_id = tonumber(get_field("fixtures", tbl, record, "competitionid", ""))
            local stadium_id = tonumber(get_field("fixtures", tbl, record, "stadiumid", ""))
            if fixture_id and competition_id and competition_id > 0 then
                fixture_competition_id_by_fixture_id[fixture_id] = competition_id
            end
            if fixture_id and stadium_id and stadium_id > 0 then
                fixture_stadium_id_by_fixture_id[fixture_id] = stadium_id
            end
        end)
        if mapping_status ~= "ok" then
            log("Static competition ID crosswalk unavailable: " .. tostring(mapping_status))
        end
    end

    -- ---------------------------------------------------------------------
    -- Leagues
    -- ---------------------------------------------------------------------
    do
        local filename = "leagues.csv"
        local file = open_csv(filename, {
            "league_id", "league_name", "country_id", "level", "league_type",
            "is_women_competition", "is_international_league"
        })

        local written = 0
        local _, status = iterate_table("leagues", function(tbl, record)
            local league_id = get_field("leagues", tbl, record, "leagueid", 0)
            if is_positive_id(league_id) then
                local item = {
                    league_id = league_id,
                    league_name = get_field("leagues", tbl, record, "leaguename", ""),
                    country_id = get_field("leagues", tbl, record, "countryid", 0),
                    level = get_field("leagues", tbl, record, "level", 0),
                    league_type = get_field("leagues", tbl, record, "leaguetype", 0),
                    is_women = get_field("leagues", tbl, record, "iswomencompetition", 0),
                    is_international = get_field("leagues", tbl, record, "isinternationalleague", 0)
                }
                leagues_by_id[tonumber(league_id)] = item
                write_csv_row(file, {
                    item.league_id, item.league_name, item.country_id, item.level,
                    item.league_type, item.is_women, item.is_international
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported leagues: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- League/team links
    -- ---------------------------------------------------------------------
    do
        local filename = "team_leagues.csv"
        local file = open_csv(filename, {
            "team_id", "league_id", "league_name", "previous_league_id",
            "previous_league_name", "current_table_position", "points",
            "matches_played", "home_wins", "home_draws", "home_losses",
            "away_wins", "away_draws", "away_losses",
            "home_goals_for", "home_goals_against", "away_goals_for", "away_goals_against",
            "goal_difference", "previous_year_table_position", "champion",
            "objective", "highest_possible", "yet_to_win", "highest_probable",
            "has_achieved_objective", "unbeaten_home", "unbeaten_away", "unbeaten_league",
            "unbeaten_all_comps", "last_game_result", "actual_vs_expectations",
            "team_long_form", "team_short_form", "team_form", "grouping", "artificial_key"
        })

        local written = 0
        local _, status = iterate_table("leagueteamlinks", function(tbl, record)
            local team_id = get_field("leagueteamlinks", tbl, record, "teamid", 0)
            local league_id = get_field("leagueteamlinks", tbl, record, "leagueid", 0)
            if is_positive_id(team_id) and is_positive_id(league_id) then
                local previous_league_id = get_field("leagueteamlinks", tbl, record, "prevleagueid", 0)
                local league = leagues_by_id[tonumber(league_id)]
                local previous_league = leagues_by_id[tonumber(previous_league_id)]
                local home_wins = get_field("leagueteamlinks", tbl, record, "homewins", "")
                local home_draws = get_field("leagueteamlinks", tbl, record, "homedraws", "")
                local home_losses = get_field("leagueteamlinks", tbl, record, "homelosses", "")
                local away_wins = get_field("leagueteamlinks", tbl, record, "awaywins", "")
                local away_draws = get_field("leagueteamlinks", tbl, record, "awaydraws", "")
                local away_losses = get_field("leagueteamlinks", tbl, record, "awaylosses", "")
                local home_gf = get_field("leagueteamlinks", tbl, record, "homegf", "")
                local home_ga = get_field("leagueteamlinks", tbl, record, "homega", "")
                local away_gf = get_field("leagueteamlinks", tbl, record, "awaygf", "")
                local away_ga = get_field("leagueteamlinks", tbl, record, "awayga", "")
                local numeric_home_gf, numeric_home_ga = tonumber(home_gf), tonumber(home_ga)
                local numeric_away_gf, numeric_away_ga = tonumber(away_gf), tonumber(away_ga)
                local goal_difference = ""
                if numeric_home_gf and numeric_home_ga and numeric_away_gf and numeric_away_ga then
                    goal_difference = (numeric_home_gf + numeric_away_gf) - (numeric_home_ga + numeric_away_ga)
                end
                local item = {
                    team_id = team_id,
                    league_id = league_id,
                    league_name = league and league.league_name or "",
                    previous_league_id = previous_league_id,
                    previous_league_name = previous_league and previous_league.league_name or "",
                    current_table_position = get_field("leagueteamlinks", tbl, record, "currenttableposition", ""),
                    points = get_field("leagueteamlinks", tbl, record, "points", ""),
                    matches_played = get_field("leagueteamlinks", tbl, record, "nummatchesplayed", ""),
                    home_wins = home_wins, home_draws = home_draws, home_losses = home_losses,
                    away_wins = away_wins, away_draws = away_draws, away_losses = away_losses,
                    home_goals_for = home_gf, home_goals_against = home_ga,
                    away_goals_for = away_gf, away_goals_against = away_ga,
                    goal_difference = goal_difference,
                    previous_year_table_position = get_field("leagueteamlinks", tbl, record, "previousyeartableposition", ""),
                    champion = get_field("leagueteamlinks", tbl, record, "champion", 0),
                    objective = get_field("leagueteamlinks", tbl, record, "objective", ""),
                    highest_possible = get_field("leagueteamlinks", tbl, record, "highestpossible", ""),
                    yet_to_win = get_field("leagueteamlinks", tbl, record, "yettowin", ""),
                    highest_probable = get_field("leagueteamlinks", tbl, record, "highestprobable", ""),
                    has_achieved_objective = get_field("leagueteamlinks", tbl, record, "hasachievedobjective", ""),
                    unbeaten_home = get_field("leagueteamlinks", tbl, record, "unbeatenhome", ""),
                    unbeaten_away = get_field("leagueteamlinks", tbl, record, "unbeatenaway", ""),
                    unbeaten_league = get_field("leagueteamlinks", tbl, record, "unbeatenleague", ""),
                    unbeaten_all_comps = get_field("leagueteamlinks", tbl, record, "unbeatenallcomps", ""),
                    last_game_result = get_field("leagueteamlinks", tbl, record, "lastgameresult", ""),
                    actual_vs_expectations = get_field("leagueteamlinks", tbl, record, "actualvsexpectations", ""),
                    team_long_form = get_field("leagueteamlinks", tbl, record, "Teamlongform", ""),
                    team_short_form = get_field("leagueteamlinks", tbl, record, "teamshortform", ""),
                    team_form = get_field("leagueteamlinks", tbl, record, "teamform", ""),
                    grouping = get_field("leagueteamlinks", tbl, record, "grouping", ""),
                    artificial_key = get_field("leagueteamlinks", tbl, record, "artificialkey", "")
                }
                team_league_by_id[tonumber(team_id)] = item
                write_csv_row(file, {
                    item.team_id, item.league_id, item.league_name,
                    item.previous_league_id, item.previous_league_name,
                    item.current_table_position, item.points, item.matches_played,
                    item.home_wins, item.home_draws, item.home_losses,
                    item.away_wins, item.away_draws, item.away_losses,
                    item.home_goals_for, item.home_goals_against,
                    item.away_goals_for, item.away_goals_against, item.goal_difference,
                    item.previous_year_table_position, item.champion,
                    item.objective, item.highest_possible, item.yet_to_win, item.highest_probable,
                    item.has_achieved_objective, item.unbeaten_home, item.unbeaten_away,
                    item.unbeaten_league, item.unbeaten_all_comps, item.last_game_result,
                    item.actual_vs_expectations, item.team_long_form, item.team_short_form,
                    item.team_form, item.grouping, item.artificial_key
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported team/league links: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Teams
    -- ---------------------------------------------------------------------
    do
        local filename = "teams.csv"
        local file = open_csv(filename, {
            "team_id", "team_name", "league_id", "league_name", "previous_league_id",
            "previous_league_name", "overall", "attack", "midfield", "defence",
            "domestic_prestige", "international_prestige", "profitability",
            "foundation_year", "club_worth", "stadium_capacity", "gender"
        })

        local written = 0
        local _, status = iterate_table("teams", function(tbl, record)
            local team_id = get_field("teams", tbl, record, "teamid", 0)
            if is_positive_id(team_id) then
                local league_link = team_league_by_id[tonumber(team_id)]
                local team_name = get_field("teams", tbl, record, "teamname", "")
                if team_name == "" then
                    team_name = safe_team_name(team_id)
                end

                local item = {
                    team_id = team_id,
                    team_name = team_name,
                    overall = get_field("teams", tbl, record, "overallrating", ""),
                    attack = get_field("teams", tbl, record, "attackrating", ""),
                    midfield = get_field("teams", tbl, record, "midfieldrating", ""),
                    defence = get_field("teams", tbl, record, "defenserating", ""),
                    domestic_prestige = get_field("teams", tbl, record, "domesticprestige", ""),
                    international_prestige = get_field("teams", tbl, record, "internationalprestige", ""),
                    profitability = get_field("teams", tbl, record, "profitability", ""),
                    foundation_year = get_field("teams", tbl, record, "foundationyear", ""),
                    club_worth = get_field("teams", tbl, record, "clubworth", ""),
                    stadium_capacity = get_field("teams", tbl, record, "teamstadiumcapacity", ""),
                    gender = get_field("teams", tbl, record, "gender", "")
                }
                teams_by_id[tonumber(team_id)] = item
                TEAM_PROFITABILITY_TOTAL_TEAMS = TEAM_PROFITABILITY_TOTAL_TEAMS + 1
                if trim(item.profitability) ~= "" then
                    TEAM_PROFITABILITY_NONEMPTY_COUNT = TEAM_PROFITABILITY_NONEMPTY_COUNT + 1
                end

                write_csv_row(file, {
                    item.team_id, item.team_name,
                    league_link and league_link.league_id or "",
                    league_link and league_link.league_name or "",
                    league_link and league_link.previous_league_id or "",
                    league_link and league_link.previous_league_name or "",
                    item.overall, item.attack, item.midfield, item.defence,
                    item.domestic_prestige, item.international_prestige,
                    item.profitability, item.foundation_year, item.club_worth, item.stadium_capacity,
                    item.gender
                })
                written = written + 1
            end
        end)

        file:close()
        TEAM_PROFITABILITY_EXPORTED = TEAM_PROFITABILITY_NONEMPTY_COUNT > 0
        local team_status = status
        local team_note = "profitability non-empty for "
            .. tostring(TEAM_PROFITABILITY_NONEMPTY_COUNT)
            .. " of " .. tostring(TEAM_PROFITABILITY_TOTAL_TEAMS) .. " teams"
        if not TEAM_PROFITABILITY_EXPORTED then
            team_status = "warning"
            team_note = team_note .. "; teams.profitability unavailable or empty"
            log("WARNING: No team profitability values were exported")
        end
        add_manifest(filename, written, team_status, team_note)
        log("Exported teams: " .. written
            .. "; profitability values: " .. TEAM_PROFITABILITY_NONEMPTY_COUNT)
    end

    -- ---------------------------------------------------------------------
    -- Career metadata / user club / deterministic identity candidate
    -- ---------------------------------------------------------------------
    local managed_team_id = 0
    local season_count = ""
    local user_display_name = ""
    local primary_compobjid = ""
    local user_id = ""
    local manager_nationality_id = ""
    local initial_team_id = 0
    local initial_league_id = 0
    local career_fingerprint_candidate = ""
    do
        local _, user_status = iterate_table("career_users", function(tbl, record)
            local candidate_user_id = get_field("career_users", tbl, record, "userid", -1)
            local club_team_id = get_field("career_users", tbl, record, "clubteamid", -1)
            local user_type = get_field("career_users", tbl, record, "usertype", -1)
            if tonumber(candidate_user_id) and tonumber(candidate_user_id) >= 0
                and tonumber(club_team_id) and tonumber(club_team_id) >= 0
                and tonumber(user_type) and tonumber(user_type) >= 0 then
                managed_team_id = club_team_id
                season_count = get_field("career_users", tbl, record, "seasoncount", "")
                primary_compobjid = get_field("career_users", tbl, record, "primarycompobjid", "")
                user_id = candidate_user_id
                manager_nationality_id = get_field("career_users", tbl, record, "nationalityid", "")
                local first_name = get_field("career_users", tbl, record, "firstname", "")
                local surname = get_field("career_users", tbl, record, "surname", "")
                local common_name = get_field("career_users", tbl, record, "commonname", "")
                user_display_name = common_name ~= "" and common_name
                    or trim(tostring(first_name) .. " " .. tostring(surname))
            end
        end)

        local earliest_season = nil
        iterate_table("career_managerhistory", function(tbl, record)
            local season = tonumber(get_field("career_managerhistory", tbl, record, "season", 0)) or 0
            local team_id = tonumber(get_field("career_managerhistory", tbl, record, "teamid", 0)) or 0
            local league_id = tonumber(get_field("career_managerhistory", tbl, record, "leagueid", 0)) or 0
            local games_played = tonumber(get_field("career_managerhistory", tbl, record, "games_played", 0)) or 0
            if season > 0 and team_id > 0 and (earliest_season == nil or season < earliest_season) then
                earliest_season = season
                initial_team_id = team_id
                initial_league_id = league_id
            end
        end)

        if initial_team_id <= 0 then
            initial_team_id = tonumber(managed_team_id) or 0
        end

        local identity_basis = table.concat({
            "fc26v2",
            tostring(user_display_name),
            tostring(user_id),
            tostring(manager_nationality_id),
            tostring(initial_team_id)
        }, "|")
        career_fingerprint_candidate = "fc26v2-" .. string.format("%08x", fnv1a32(identity_basis))

        local game_year, game_month, game_day = get_game_date()
        local career_date_iso = ""
        local career_date_sort = 0
        if tonumber(game_year) and tonumber(game_month) and tonumber(game_day) then
            career_date_iso = string.format("%04d-%02d-%02d", game_year, game_month, game_day)
            career_date_sort = tonumber(string.format("%04d%02d%02d", game_year, game_month, game_day)) or 0
        end

        local managed_team = teams_by_id[tonumber(managed_team_id)]
        local initial_team = teams_by_id[tonumber(initial_team_id)]

        SNAPSHOT_CONTEXT = {
            snapshot_id = SNAPSHOT_ID,
            schema_version = SCHEMA_VERSION,
            exporter_version = EXPORTER_VERSION,
            exported_at_local = now_iso_local(),
            exported_at_utc = now_iso_utc(),
            export_root = EXPORT_ROOT,
            export_config_source = EXPORT_CONFIG_SOURCE,
            career_fingerprint_candidate = career_fingerprint_candidate,
            career_identity_basis = identity_basis,
            career_identity_confidence = "stable_candidate_v2_not_save_guid",
            user_id = user_id,
            manager_display_name = user_display_name,
            manager_nationality_id = manager_nationality_id,
            initial_team_id = initial_team_id,
            initial_team_name = initial_team and initial_team.team_name or safe_team_name(initial_team_id),
            initial_league_id = initial_league_id,
            managed_team_id = managed_team_id,
            managed_team_name = managed_team and managed_team.team_name or safe_team_name(managed_team_id),
            primary_compobjid = primary_compobjid,
            season_index = tonumber(season_count) or 0,
            career_date_iso = career_date_iso,
            career_date_sort = career_date_sort,
            managed_completed_fixture_count = 0,
            global_completed_fixture_count = 0,
            detailed_player_match_stats = false,
            match_events = false
        }

        local filename = "career_metadata.csv"
        local file = open_csv(filename, {"key", "value"})
        local metadata = {
            {"schema_version", SCHEMA_VERSION},
            {"exporter_version", EXPORTER_VERSION},
            {"live_editor_version", LE_VERSION or ""},
            {"snapshot_id", SNAPSHOT_ID},
            {"exported_at_local", SNAPSHOT_CONTEXT.exported_at_local},
            {"exported_at_utc", SNAPSHOT_CONTEXT.exported_at_utc},
            {"export_trigger", tostring(_G.FC26_EXPORT_EXPORT_TRIGGER or "")},
            {"post_match_capture_id", tostring(_G.FC26_EXPORT_POST_MATCH_CAPTURE_ID or "")},
            {"export_scope", "current_loaded_career"},
            {"export_root", EXPORT_ROOT},
            {"export_config_source", EXPORT_CONFIG_SOURCE},
            {"export_root_is_fallback", 0},
            {"career_fingerprint_candidate", career_fingerprint_candidate},
            {"career_identity_confidence", "stable_candidate_v2_not_save_guid"},
            {"career_date", career_date_iso},
            {"career_date_sort", career_date_sort},
            {"season_index", SNAPSHOT_CONTEXT.season_index},
            {"managed_team_source", "career_users.clubteamid"},
            {"managed_team_id", managed_team_id},
            {"managed_team_name", SNAPSHOT_CONTEXT.managed_team_name},
            {"initial_team_id", initial_team_id},
            {"initial_team_name", SNAPSHOT_CONTEXT.initial_team_name},
            {"manager_display_name", user_display_name},
            {"manager_nationality_id", manager_nationality_id},
            {"primary_compobjid", primary_compobjid},
            {"team_profitability_source", "teams.profitability"},
            {"team_profitability_exported", TEAM_PROFITABILITY_EXPORTED and 1 or 0},
            {"team_profitability_nonempty_count", TEAM_PROFITABILITY_NONEMPTY_COUNT},
            {"team_profitability_total_teams", TEAM_PROFITABILITY_TOTAL_TEAMS}
        }

        for i = 1, #metadata do
            write_csv_row(file, metadata[i])
        end

        file:close()
        add_manifest(filename, #metadata, user_status)
        log("Exported career metadata; managed team: " .. tostring(SNAPSHOT_CONTEXT.managed_team_name))
    end

    -- ---------------------------------------------------------------------
    -- Players with resolved names
    -- ---------------------------------------------------------------------
    local unresolved_names = {}
    do
        local filename = "players.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "team_id", "team_name",
            "overall", "potential", "primary_position_id", "primary_position",
            "position_2_id", "position_2", "position_3_id", "position_3",
            "position_4_id", "position_4", "nationality_id", "birthdate_raw",
            "contract_valid_until", "player_join_team_date_raw", "player_join_team_date",
            "height", "weight", "preferred_foot_id",
            "weak_foot", "skill_moves", "international_reputation", "is_retiring",
            "gender", "firstname_id", "lastname_id", "commonname_id",
            "jersey_name_id", "pacdiv", "shohan", "paskic", "driref", "defspe",
            "phypos", "acceleration", "sprint_speed", "agility", "balance",
            "reactions", "ball_control", "dribbling", "finishing", "shot_power",
            "long_shots", "volleys", "penalties", "positioning", "vision",
            "crossing", "free_kick_accuracy", "short_passing", "long_passing",
            "curve", "interceptions", "heading_accuracy", "defensive_awareness",
            "standing_tackle", "sliding_tackle", "jumping", "stamina", "strength",
            "aggression", "composure", "gk_diving", "gk_handling", "gk_kicking",
            "gk_reflexes", "gk_positioning"
        })

        local written = 0
        local _, status = iterate_table("players", function(tbl, record)
            local player_id = get_field("players", tbl, record, "playerid", 0)
            if is_positive_id(player_id) then
                local display_name = safe_player_name(player_id)
                if display_name == "" then
                    table.insert(unresolved_names, player_id)
                end

                local team_id = safe_player_team_id(player_id)
                local team = teams_by_id[tonumber(team_id)]
                local primary_position_id = get_field("players", tbl, record, "preferredposition1", "")
                local position_2_id = get_field("players", tbl, record, "preferredposition2", "")
                local position_3_id = get_field("players", tbl, record, "preferredposition3", "")
                local position_4_id = get_field("players", tbl, record, "preferredposition4", "")

                local player = {
                    player_id = player_id,
                    display_name = display_name,
                    team_id = team_id,
                    team_name = team and team.team_name or safe_team_name(team_id),
                    overall = get_field("players", tbl, record, "overallrating", ""),
                    potential = get_field("players", tbl, record, "potential", ""),
                    primary_position_id = primary_position_id,
                    primary_position = safe_football_position_name(primary_position_id)
                }
                players_by_id[tonumber(player_id)] = player

                local join_raw = get_field("players", tbl, record, "joindate", "")
                write_csv_row(file, {
                    player.player_id, player.display_name, player.team_id, player.team_name,
                    player.overall, player.potential,
                    primary_position_id, player.primary_position,
                    position_2_id, safe_football_position_name(position_2_id),
                    position_3_id, safe_football_position_name(position_3_id),
                    position_4_id, safe_football_position_name(position_4_id),
                    get_field("players", tbl, record, "nationality", ""),
                    get_field("players", tbl, record, "birthdate", ""),
                    get_field("players", tbl, record, "contractvaliduntil", ""),
                    join_raw,
                    ea_day_to_iso(join_raw),
                    get_field("players", tbl, record, "height", ""),
                    get_field("players", tbl, record, "weight", ""),
                    get_field("players", tbl, record, "preferredfoot", ""),
                    get_field("players", tbl, record, "weakfootabilitytypecode", ""),
                    get_field("players", tbl, record, "skillmoves", ""),
                    get_field("players", tbl, record, "internationalrep", ""),
                    get_field("players", tbl, record, "isretiring", ""),
                    get_field("players", tbl, record, "gender", ""),
                    get_field("players", tbl, record, "firstnameid", ""),
                    get_field("players", tbl, record, "lastnameid", ""),
                    get_field("players", tbl, record, "commonnameid", ""),
                    get_field("players", tbl, record, "playerjerseynameid", ""),
                    get_field("players", tbl, record, "pacdiv", ""),
                    get_field("players", tbl, record, "shohan", ""),
                    get_field("players", tbl, record, "paskic", ""),
                    get_field("players", tbl, record, "driref", ""),
                    get_field("players", tbl, record, "defspe", ""),
                    get_field("players", tbl, record, "phypos", ""),
                    get_field("players", tbl, record, "acceleration", ""),
                    get_field("players", tbl, record, "sprintspeed", ""),
                    get_field("players", tbl, record, "agility", ""),
                    get_field("players", tbl, record, "balance", ""),
                    get_field("players", tbl, record, "reactions", ""),
                    get_field("players", tbl, record, "ballcontrol", ""),
                    get_field("players", tbl, record, "dribbling", ""),
                    get_field("players", tbl, record, "finishing", ""),
                    get_field("players", tbl, record, "shotpower", ""),
                    get_field("players", tbl, record, "longshots", ""),
                    get_field("players", tbl, record, "volleys", ""),
                    get_field("players", tbl, record, "penalties", ""),
                    get_field("players", tbl, record, "positioning", ""),
                    get_field("players", tbl, record, "vision", ""),
                    get_field("players", tbl, record, "crossing", ""),
                    get_field("players", tbl, record, "freekickaccuracy", ""),
                    get_field("players", tbl, record, "shortpassing", ""),
                    get_field("players", tbl, record, "longpassing", ""),
                    get_field("players", tbl, record, "curve", ""),
                    get_field("players", tbl, record, "interceptions", ""),
                    get_field("players", tbl, record, "headingaccuracy", ""),
                    get_field("players", tbl, record, "defensiveawareness", ""),
                    get_field("players", tbl, record, "standingtackle", ""),
                    get_field("players", tbl, record, "slidingtackle", ""),
                    get_field("players", tbl, record, "jumping", ""),
                    get_field("players", tbl, record, "stamina", ""),
                    get_field("players", tbl, record, "strength", ""),
                    get_field("players", tbl, record, "aggression", ""),
                    get_field("players", tbl, record, "composure", ""),
                    get_field("players", tbl, record, "gkdiving", ""),
                    get_field("players", tbl, record, "gkhandling", ""),
                    get_field("players", tbl, record, "gkkicking", ""),
                    get_field("players", tbl, record, "gkreflexes", ""),
                    get_field("players", tbl, record, "gkpositioning", "")
                })

                written = written + 1
                if written % 1000 == 0 then
                    log("Players processed: " .. written)
                end
            end
        end)

        file:close()
        local player_status = status
        local note = ""
        if #unresolved_names > 0 then
            player_status = "warning"
            note = tostring(#unresolved_names) .. " unresolved player names"
        end
        add_manifest(filename, written, player_status, note)
        log("Exported players: " .. written .. "; unresolved names: " .. #unresolved_names)
    end

    do
        local filename = "unresolved_player_names.csv"
        local file = open_csv(filename, {"player_id", "reason"})
        for i = 1, #unresolved_names do
            write_csv_row(file, {unresolved_names[i], "GetPlayerName returned an empty value"})
        end
        file:close()
        add_manifest(filename, #unresolved_names, #unresolved_names == 0 and "ok" or "warning")
    end

    -- ---------------------------------------------------------------------
    -- Roster links
    -- ---------------------------------------------------------------------
    do
        local filename = "rosters.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "team_id", "team_name", "jersey_number",
            "teamsheet_slot_raw", "teamsheet_slot_label", "primary_position_id",
            "primary_position", "form", "injury"
        })

        local written = 0
        local _, status = iterate_table("teamplayerlinks", function(tbl, record)
            local player_id = get_field("teamplayerlinks", tbl, record, "playerid", 0)
            local team_id = get_field("teamplayerlinks", tbl, record, "teamid", 0)
            if is_positive_id(player_id) and is_positive_id(team_id) then
                local player = players_by_id[tonumber(player_id)]
                local team = teams_by_id[tonumber(team_id)]
                write_csv_row(file, {
                    player_id,
                    player and player.display_name or safe_player_name(player_id),
                    team_id,
                    team and team.team_name or safe_team_name(team_id),
                    get_field("teamplayerlinks", tbl, record, "jerseynumber", ""),
                    get_field("teamplayerlinks", tbl, record, "position", ""),
                    teamsheet_slot_label(get_field("teamplayerlinks", tbl, record, "position", "")),
                    player and player.primary_position_id or "",
                    player and player.primary_position or "",
                    get_field("teamplayerlinks", tbl, record, "form", ""),
                    get_field("teamplayerlinks", tbl, record, "injury", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status, "Season statistics intentionally excluded; use season_stats.csv")
        log("Exported roster links: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Loans
    -- ---------------------------------------------------------------------
    do
        local filename = "loans.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "parent_team_id", "parent_team_name",
            "loan_team_id", "loan_team_name", "loan_end_raw", "loan_end_date",
            "is_loan_to_buy"
        })

        local written = 0
        local _, status = iterate_table("playerloans", function(tbl, record)
            local player_id = get_field("playerloans", tbl, record, "playerid", 0)
            if is_positive_id(player_id) then
                local parent_team_id = get_field("playerloans", tbl, record, "teamidloanedfrom", 0)
                local player = players_by_id[tonumber(player_id)]
                local loan_team_id = player and player.team_id or safe_player_team_id(player_id)
                local parent_team = teams_by_id[tonumber(parent_team_id)]
                local loan_team = teams_by_id[tonumber(loan_team_id)]
                local loan_end_raw = get_field("playerloans", tbl, record, "loandateend", "")
                write_csv_row(file, {
                    player_id,
                    player and player.display_name or safe_player_name(player_id),
                    parent_team_id,
                    parent_team and parent_team.team_name or safe_team_name(parent_team_id),
                    loan_team_id,
                    loan_team and loan_team.team_name or safe_team_name(loan_team_id),
                    loan_end_raw,
                    ea_day_to_iso(loan_end_raw),
                    get_field("playerloans", tbl, record, "isloantobuy", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported loans: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Detailed career contracts
    -- ---------------------------------------------------------------------
    do
        local filename = "contracts.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "team_id", "team_name", "duration_months",
            "contract_status", "player_role", "wage", "contract_date",
            "last_status_change_date", "loan_wage_split", "signon_bonus",
            "performance_bonus_type", "performance_bonus_value",
            "performance_bonus_count", "performance_bonus_count_achieved",
            "is_performance_bonus_achieved"
        })

        local written = 0
        local _, status = iterate_table("career_playercontract", function(tbl, record)
            local player_id = get_field("career_playercontract", tbl, record, "playerid", 0)
            if is_positive_id(player_id) then
                local team_id = get_field("career_playercontract", tbl, record, "teamid", 0)
                local player = players_by_id[tonumber(player_id)]
                local team = teams_by_id[tonumber(team_id)]
                write_csv_row(file, {
                    player_id,
                    player and player.display_name or safe_player_name(player_id),
                    team_id,
                    team and team.team_name or safe_team_name(team_id),
                    get_field("career_playercontract", tbl, record, "duration_months", ""),
                    get_field("career_playercontract", tbl, record, "contract_status", ""),
                    get_field("career_playercontract", tbl, record, "playerrole", ""),
                    get_field("career_playercontract", tbl, record, "wage", ""),
                    get_field("career_playercontract", tbl, record, "contract_date", ""),
                    get_field("career_playercontract", tbl, record, "last_status_change_date", ""),
                    get_field("career_playercontract", tbl, record, "loan_wage_split", ""),
                    get_field("career_playercontract", tbl, record, "signon_bonus", ""),
                    get_field("career_playercontract", tbl, record, "performancebonustype", ""),
                    get_field("career_playercontract", tbl, record, "performancebonusvalue", ""),
                    get_field("career_playercontract", tbl, record, "performancebonuscount", ""),
                    get_field("career_playercontract", tbl, record, "performancebonuscountachieved", ""),
                    get_field("career_playercontract", tbl, record, "isperformancebonusachieved", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported detailed contracts: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Youth academy
    -- ---------------------------------------------------------------------
    do
        local filename = "youth_players.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "overall", "potential", "primary_position_id",
            "primary_position", "player_tier", "months_in_squad",
            "potential_variance", "swing_low_potential"
        })

        local written = 0
        local _, status = iterate_table("career_youthplayers", function(tbl, record)
            local player_id = get_field("career_youthplayers", tbl, record, "playerid", 0)
            if is_positive_id(player_id) then
                local player = players_by_id[tonumber(player_id)]
                write_csv_row(file, {
                    player_id,
                    player and player.display_name or safe_player_name(player_id),
                    player and player.overall or "",
                    player and player.potential or "",
                    player and player.primary_position_id or "",
                    player and player.primary_position or "",
                    get_field("career_youthplayers", tbl, record, "playertier", ""),
                    get_field("career_youthplayers", tbl, record, "monthsinsquad", ""),
                    get_field("career_youthplayers", tbl, record, "potentialvariance", ""),
                    get_field("career_youthplayers", tbl, record, "swinglowpotential", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported youth players: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Match rating history
    -- ---------------------------------------------------------------------
    do
        local filename = "match_ratings.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "date_raw", "date", "rating",
            "minutes_played", "rating_position_raw", "rating_position_hint",
            "artificial_key"
        })

        local written = 0
        local _, status = iterate_table("career_playermatchratinghistory", function(tbl, record)
            local player_id = get_field("career_playermatchratinghistory", tbl, record, "playerid", 0)
            if is_positive_id(player_id) then
                local player = players_by_id[tonumber(player_id)]
                local position_id = get_field("career_playermatchratinghistory", tbl, record, "position", "")
                local date_raw = get_field("career_playermatchratinghistory", tbl, record, "date", "")
                local row = {
                    player_id = player_id,
                    display_name = player and player.display_name or safe_player_name(player_id),
                    date_raw = date_raw,
                    date = ea_day_to_iso(date_raw),
                    rating = get_field("career_playermatchratinghistory", tbl, record, "rating", ""),
                    minutes_played = get_field("career_playermatchratinghistory", tbl, record, "minsplayed", ""),
                    position_id = position_id,
                    position = safe_football_position_name(position_id),
                    artificial_key = get_field("career_playermatchratinghistory", tbl, record, "artificialkey", "")
                }
                table.insert(match_rating_rows, row)
                write_csv_row(file, {
                    row.player_id, row.display_name, row.date_raw, row.date,
                    row.rating, row.minutes_played, row.position_id, row.position,
                    row.artificial_key
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported match rating history: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Last-match player state retained by the career database
    -- ---------------------------------------------------------------------
    do
        local filename = "last_match_players.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "team_id", "team_name",
            "is_managed_team", "minutes_played", "actual_position_id",
            "actual_position", "player_overall", "player_fact_raw", "artificial_key"
        })

        local written = 0
        local _, status = iterate_table("career_playerlastmatchhistory", function(tbl, record)
            local player_id = get_field("career_playerlastmatchhistory", tbl, record, "playerid", 0)
            local team_id = get_field("career_playerlastmatchhistory", tbl, record, "teamid", 0)
            if is_positive_id(player_id) and is_positive_id(team_id) then
                local player = players_by_id[tonumber(player_id)]
                local team = teams_by_id[tonumber(team_id)]
                local position_id = get_field("career_playerlastmatchhistory", tbl, record, "position", "")
                if tonumber(team_id) == tonumber(managed_team_id) then
                    managed_last_match_positions[tonumber(player_id)] = {
                        position_id = position_id,
                        position = safe_football_position_name(position_id)
                    }
                end
                write_csv_row(file, {
                    player_id,
                    player and player.display_name or safe_player_name(player_id),
                    team_id,
                    team and team.team_name or safe_team_name(team_id),
                    tonumber(team_id) == tonumber(managed_team_id) and 1 or 0,
                    get_field("career_playerlastmatchhistory", tbl, record, "minsplayed", ""),
                    position_id,
                    safe_football_position_name(position_id),
                    get_field("career_playerlastmatchhistory", tbl, record, "playeroverall", ""),
                    get_field("career_playerlastmatchhistory", tbl, record, "playerfact", ""),
                    get_field("career_playerlastmatchhistory", tbl, record, "artificialkey", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status, "Contains retained last-match state for many teams; use is_managed_team to filter the current user club")
        log("Exported last-match player state: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Player development snapshot
    -- ---------------------------------------------------------------------
    do
        local filename = "player_growth.csv"
        local columns = {
            "player_id", "display_name", "curve", "overall", "acceleration",
            "sprint_speed", "agility", "balance", "reactions", "ball_control",
            "dribbling", "finishing", "shot_power", "long_shots", "volleys",
            "penalties", "positioning", "vision", "crossing", "free_kick_accuracy",
            "short_passing", "long_passing", "interceptions", "heading_accuracy",
            "defensive_awareness", "standing_tackle", "sliding_tackle", "jumping",
            "stamina", "strength", "aggression", "composure", "gk_diving",
            "gk_handling", "gk_kicking", "gk_reflexes", "gk_positioning"
        }
        local file = open_csv(filename, columns)

        local written = 0
        local _, status = iterate_table("career_playergrowthuserseason", function(tbl, record)
            local player_id = get_field("career_playergrowthuserseason", tbl, record, "playerid", 0)
            if is_positive_id(player_id) then
                local player = players_by_id[tonumber(player_id)]
                write_csv_row(file, {
                    player_id,
                    player and player.display_name or safe_player_name(player_id),
                    get_field("career_playergrowthuserseason", tbl, record, "curve", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "overall", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "acceleration", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "sprintspeed", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "agility", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "balance", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "reactions", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "ballcontrol", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "dribbling", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "finishing", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "shotpower", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "longshots", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "volleys", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "penalties", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "positioning", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "vision", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "crossing", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "freekickaccuracy", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "shortpassing", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "longpassing", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "interceptions", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "headingaccuracy", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "defensiveawareness", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "standingtackle", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "slidingtackle", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "jumping", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "stamina", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "strength", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "aggression", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "composure", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "gkdiving", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "gkhandling", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "gkkicking", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "gkreflexes", ""),
                    get_field("career_playergrowthuserseason", tbl, record, "gkpositioning", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported player growth rows: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Player awards
    -- ---------------------------------------------------------------------
    do
        local filename = "player_awards.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "team_id", "team_name", "season",
            "award_type_id", "count", "artificial_key"
        })

        local written = 0
        local _, status = iterate_table("career_playerawards", function(tbl, record)
            local player_id = get_field("career_playerawards", tbl, record, "playerid", 0)
            local team_id = get_field("career_playerawards", tbl, record, "teamid", 0)
            if is_positive_id(player_id) then
                local player = players_by_id[tonumber(player_id)]
                local team = teams_by_id[tonumber(team_id)]
                write_csv_row(file, {
                    player_id,
                    player and player.display_name or safe_player_name(player_id),
                    team_id,
                    team and team.team_name or safe_team_name(team_id),
                    get_field("career_playerawards", tbl, record, "season", ""),
                    get_field("career_playerawards", tbl, record, "typeid", ""),
                    get_field("career_playerawards", tbl, record, "count", ""),
                    get_field("career_playerawards", tbl, record, "artificialkey", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported player awards: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Fixtures and results from Live Editor memory
    -- Based on the official FC 26 Live Editor export_fixtures.lua structure.
    -- ---------------------------------------------------------------------
    do
        local filename = "fixtures.csv"
        local file = open_csv(filename, {
            "fixture_key", "fixture_id", "competition_object_id", "competition_id", "competition_name", "stadium_id",
            "home_team_id", "home_team_name", "away_team_id", "away_team_name",
            "date_raw", "date", "time_raw", "time", "match_group_id",
            "is_completed", "home_score", "away_score", "home_penalties",
            "away_penalties", "managed_team_involved", "managed_team_side",
            "opponent_team_id", "opponent_team_name", "managed_team_result"
        })

        local written = 0
        local status = "ok"
        local note = ""
        local ok_read, result_or_error = pcall(function()
            local standings = read_valid_standings()
            local fixtures = read_valid_fixtures()
            for i = 1, #fixtures do
                local fixture = fixtures[i]
                local home = standings[fixture.home_standing_index]
                local away = standings[fixture.away_standing_index]
                local home_team_id = home and home.team_id or 0
                local away_team_id = away and away.team_id or 0
                local competition_name = safe_competition_name(fixture.competition_object_id)
                local static_competition_id = fixture_competition_id_by_fixture_id[tonumber(fixture.fixture_id)]
                local stadium_id = fixture_stadium_id_by_fixture_id[tonumber(fixture.fixture_id)]
                register_competition(fixture.competition_object_id, "fixtures", competition_name, static_competition_id)

                local managed_involved = tonumber(home_team_id) == tonumber(managed_team_id)
                    or tonumber(away_team_id) == tonumber(managed_team_id)
                local managed_side = ""
                local opponent_team_id = 0
                if tonumber(home_team_id) == tonumber(managed_team_id) then
                    managed_side = "HOME"
                    opponent_team_id = away_team_id
                elseif tonumber(away_team_id) == tonumber(managed_team_id) then
                    managed_side = "AWAY"
                    opponent_team_id = home_team_id
                end

                local item = {
                    fixture_key = make_fixture_key(fixture, home_team_id, away_team_id),
                    fixture_id = fixture.fixture_id,
                    competition_object_id = fixture.competition_object_id,
                    competition_id = static_competition_id,
                    competition_name = competition_name,
                    stadium_id = stadium_id,
                    home_team_id = home_team_id,
                    home_team_name = safe_team_name(home_team_id),
                    away_team_id = away_team_id,
                    away_team_name = safe_team_name(away_team_id),
                    date_raw = fixture.date_raw,
                    date = ea_day_to_iso(fixture.date_raw),
                    time_raw = fixture.time_raw,
                    time = fixture_time_to_text(fixture.time_raw),
                    match_group_id = fixture.match_group_id,
                    is_completed = fixture.completed and 1 or 0,
                    home_score = fixture.completed and fixture.home_score or "",
                    away_score = fixture.completed and fixture.away_score or "",
                    home_penalties = fixture.completed and normalize_penalty_score(fixture.home_penalties) or "",
                    away_penalties = fixture.completed and normalize_penalty_score(fixture.away_penalties) or "",
                    managed_team_involved = managed_involved and 1 or 0,
                    managed_team_side = managed_side,
                    opponent_team_id = managed_involved and opponent_team_id or "",
                    opponent_team_name = managed_involved and safe_team_name(opponent_team_id) or "",
                    managed_team_result = result_from_managed_perspective(
                        fixture.completed, managed_side, fixture.home_score, fixture.away_score
                    )
                }

                if item.is_completed == 1 then
                    global_completed_fixture_count = global_completed_fixture_count + 1
                    if item.managed_team_involved == 1 then
                        managed_completed_fixture_count = managed_completed_fixture_count + 1
                        if tonumber(item.date_raw) and tonumber(item.date_raw) > latest_managed_completed_date_raw then
                            latest_managed_completed_date_raw = tonumber(item.date_raw)
                        end
                    end
                end

                write_csv_row(file, {
                    item.fixture_key, item.fixture_id, item.competition_object_id, item.competition_id,
                    item.competition_name, item.stadium_id or "", item.home_team_id, item.home_team_name,
                    item.away_team_id, item.away_team_name, item.date_raw, item.date,
                    item.time_raw, item.time, item.match_group_id, item.is_completed,
                    item.home_score, item.away_score, item.home_penalties,
                    item.away_penalties, item.managed_team_involved,
                    item.managed_team_side, item.opponent_team_id,
                    item.opponent_team_name, item.managed_team_result
                })
                written = written + 1

                if managed_involved then
                    table.insert(managed_team_fixtures, item)
                    local date_key = tostring(item.date_raw)
                    managed_team_fixtures_by_date[date_key] = managed_team_fixtures_by_date[date_key] or {}
                    table.insert(managed_team_fixtures_by_date[date_key], item)
                end
            end
        end)

        if not ok_read then
            status = "warning"
            note = "Fixture memory export unavailable: " .. tostring(result_or_error)
            log(note)
        end

        file:close()
        add_manifest(filename, written, status, note)
        log("Exported fixtures/results: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Current managed team's fixtures. The team is discovered dynamically
    -- from career_users.clubteamid; no club ID or name is hard-coded.
    -- ---------------------------------------------------------------------
    do
        local filename = "managed_team_matches.csv"
        local file = open_csv(filename, {
            "managed_team_id", "managed_team_name", "fixture_key", "fixture_id",
            "competition_object_id", "competition_name", "date_raw", "date",
            "time_raw", "time", "side", "opponent_team_id", "opponent_team_name",
            "is_completed", "managed_score", "opponent_score", "result",
            "home_team_id", "home_team_name", "away_team_id", "away_team_name",
            "home_penalties", "away_penalties"
        })

        table.sort(managed_team_fixtures, function(a, b)
            if tonumber(a.date_raw) == tonumber(b.date_raw) then
                return tonumber(a.time_raw or 0) < tonumber(b.time_raw or 0)
            end
            return tonumber(a.date_raw or 0) < tonumber(b.date_raw or 0)
        end)

        local managed_team_name = safe_team_name(managed_team_id)
        for i = 1, #managed_team_fixtures do
            local item = managed_team_fixtures[i]
            local managed_score = ""
            local opponent_score = ""
            if item.is_completed == 1 then
                if item.managed_team_side == "HOME" then
                    managed_score = item.home_score
                    opponent_score = item.away_score
                else
                    managed_score = item.away_score
                    opponent_score = item.home_score
                end
            end
            write_csv_row(file, {
                managed_team_id, managed_team_name, item.fixture_key, item.fixture_id,
                item.competition_object_id, item.competition_name, item.date_raw,
                item.date, item.time_raw, item.time, item.managed_team_side,
                item.opponent_team_id, item.opponent_team_name, item.is_completed,
                managed_score, opponent_score, item.managed_team_result,
                item.home_team_id, item.home_team_name, item.away_team_id,
                item.away_team_name, item.home_penalties, item.away_penalties
            })
        end
        file:close()
        add_manifest(filename, #managed_team_fixtures, "ok", "Current user club selected dynamically from career_users.clubteamid")
        log("Exported current managed-team matches: " .. #managed_team_fixtures)
    end

    -- ---------------------------------------------------------------------
    -- Enrich rating history with the current managed team's fixture context.
    -- The source rating table has no fixture/team ID, so joining is by date.
    -- ---------------------------------------------------------------------
    do
        local filename = "managed_team_match_players.csv"
        local file = open_csv(filename, {
            "join_status", "managed_team_id", "managed_team_name", "fixture_key",
            "competition_object_id", "competition_name", "date_raw", "date",
            "side", "opponent_team_id", "opponent_team_name", "home_score",
            "away_score", "result", "player_id", "display_name", "rating",
            "minutes_played", "rating_position_raw", "rating_position_hint",
            "actual_position_id", "actual_position", "actual_position_source",
            "rating_artificial_key"
        })

        local managed_team_name = safe_team_name(managed_team_id)
        local written = 0
        local joined = 0
        local duplicate_rows_skipped = 0
        local seen_fixture_players = {}
        for i = 1, #match_rating_rows do
            local rating = match_rating_rows[i]
            local candidates = managed_team_fixtures_by_date[tostring(rating.date_raw)] or {}
            local fixture = nil
            local join_status = "unmatched_date"
            if #candidates == 1 then
                fixture = candidates[1]
                join_status = "joined_by_date"
            elseif #candidates > 1 then
                join_status = "ambiguous_date"
            end

            local should_write = true
            if fixture then
                local dedupe_key = tostring(fixture.fixture_key or rating.date_raw) .. ":" .. tostring(rating.player_id)
                if seen_fixture_players[dedupe_key] then
                    should_write = false
                    duplicate_rows_skipped = duplicate_rows_skipped + 1
                else
                    seen_fixture_players[dedupe_key] = true
                    joined = joined + 1
                end
            end

            if should_write then
                local actual_position_id = ""
                local actual_position = ""
                local actual_position_source = ""
                if fixture and tonumber(fixture.date_raw) == tonumber(latest_managed_completed_date_raw) then
                    local actual = managed_last_match_positions[tonumber(rating.player_id)]
                    if actual then
                        actual_position_id = actual.position_id or ""
                        actual_position = actual.position or ""
                        actual_position_source = "career_playerlastmatchhistory_latest_match"
                    end
                end

                write_csv_row(file, {
                    join_status,
                    managed_team_id,
                    managed_team_name,
                    fixture and fixture.fixture_key or "",
                    fixture and fixture.competition_object_id or "",
                    fixture and fixture.competition_name or "",
                    rating.date_raw,
                    rating.date,
                    fixture and fixture.managed_team_side or "",
                    fixture and fixture.opponent_team_id or "",
                    fixture and fixture.opponent_team_name or "",
                    fixture and fixture.home_score or "",
                    fixture and fixture.away_score or "",
                    fixture and fixture.managed_team_result or "",
                    rating.player_id,
                    rating.display_name,
                    rating.rating,
                    rating.minutes_played,
                    rating.position_id,
                    rating.position,
                    actual_position_id,
                    actual_position,
                    actual_position_source,
                    rating.artificial_key
                })
                written = written + 1
            end
        end

        file:close()
        add_manifest(filename, written, "ok", tostring(joined) .. " rows joined to the current managed club by match date; " .. tostring(duplicate_rows_skipped) .. " duplicate player/fixture rows suppressed")
        log("Exported enriched managed-team match player rows: " .. written .. "; joined: " .. joined .. "; duplicate rows suppressed: " .. duplicate_rows_skipped)
    end

    -- ---------------------------------------------------------------------
    -- Competition progress
    -- ---------------------------------------------------------------------
    do
        local filename = "competition_progress.csv"
        local file = open_csv(filename, {
            "team_id", "team_name", "season", "competition_object_id",
            "competition_name", "competition_short_name", "stage_id", "cup_objective_result",
            "has_team_won", "artificial_key"
        })

        local written = 0
        local _, status = iterate_table("career_competitionprogress", function(tbl, record)
            local team_id = get_field("career_competitionprogress", tbl, record, "teamid", 0)
            if is_positive_id(team_id) then
                local team = teams_by_id[tonumber(team_id)]
                local comp_object_id = get_field("career_competitionprogress", tbl, record, "compobjid", "")
                local short_name = get_field("career_competitionprogress", tbl, record, "compshortname", "")
                local competition_name = safe_competition_name(comp_object_id)
                if competition_name == "" then
                    competition_name = short_name
                end
                register_competition(comp_object_id, "competition_progress", competition_name)
                write_csv_row(file, {
                    team_id,
                    team and team.team_name or safe_team_name(team_id),
                    get_field("career_competitionprogress", tbl, record, "season", ""),
                    comp_object_id,
                    competition_name,
                    short_name,
                    get_field("career_competitionprogress", tbl, record, "stageid", ""),
                    get_field("career_competitionprogress", tbl, record, "cup_objective_result", ""),
                    get_field("career_competitionprogress", tbl, record, "hasteamwon", ""),
                    get_field("career_competitionprogress", tbl, record, "artificialkey", "")
                })
                written = written + 1
            end
        end)

        file:close()
        add_manifest(filename, written, status)
        log("Exported competition progress: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Current-season statistics through the Live Editor helper API
    -- ---------------------------------------------------------------------
    do
        local filename = "season_stats.csv"
        local file = open_csv(filename, {
            "player_id", "display_name", "represented_team_id", "represented_team_name",
            "current_club_id", "current_club_name", "position",
            "competition_object_id", "competition_name", "appearances",
            "average_rating", "man_of_the_match", "goals", "assists",
            "yellow_cards", "second_yellow_cards", "red_cards", "saves",
            "goals_conceded", "clean_sheets"
        })

        local written = 0
        local manifest_status = "ok"
        local manifest_note = "represented_team_id comes from GetPlayersStats; current_club_id comes from the current career database"
        local ok_stats, stats_or_error = pcall(function()
            return GetPlayersStats()
        end)

        if ok_stats and stats_or_error ~= nil then
            all_player_stats = stats_or_error
            for i = 1, #all_player_stats do
                local stat = all_player_stats[i]
                local player_id = stat.playerid
                local appearances = stat.app or 0
                if is_positive_id(player_id) and tonumber(appearances) and tonumber(appearances) > 0 then
                    local player = players_by_id[tonumber(player_id)]
                    local current_club_id = player and player.team_id or safe_player_team_id(player_id)
                    local current_club = teams_by_id[tonumber(current_club_id)]
                    local represented_team_id = tonumber(stat.teamid) or 0
                    local avg = tonumber(stat.avg) or 0
                    avg = (avg / tonumber(appearances)) / 10
                    local competition_name = stat.compname or safe_competition_name(stat.compobjid)
                    register_competition(stat.compobjid, "season_stats", competition_name)

                    write_csv_row(file, {
                        player_id,
                        player and player.display_name or safe_player_name(player_id),
                        is_positive_id(represented_team_id) and represented_team_id or "",
                        is_positive_id(represented_team_id) and safe_team_name(represented_team_id) or "",
                        current_club_id,
                        current_club and current_club.team_name or safe_team_name(current_club_id),
                        player and player.primary_position or "",
                        stat.compobjid or "",
                        competition_name or "",
                        appearances,
                        string.format("%.2f", avg),
                        stat.motm or 0,
                        stat.goals or 0,
                        stat.assists or 0,
                        stat.yellow or 0,
                        stat.two_yellow or 0,
                        stat.red or 0,
                        stat.saves or 0,
                        stat.goals_conceded or 0,
                        stat.clean_sheets or 0
                    })
                    written = written + 1
                end
            end
        else
            log("GetPlayersStats unavailable: " .. tostring(stats_or_error))
            manifest_status = "warning"
            manifest_note = "GetPlayersStats unavailable"
        end

        -- Close before measuring the file for manifest.json. On Windows a still-open
        -- binary stream may not have flushed its final buffer yet.
        file:close()
        add_manifest(filename, written, manifest_status, manifest_note)
        log("Exported current-season stats: " .. written)
    end

    -- ---------------------------------------------------------------------
    -- Competition reference assembled from every current source
    -- ---------------------------------------------------------------------
    do
        local filename = "competitions.csv"
        local file = open_csv(filename, {
            "competition_object_id", "competition_id", "competition_name", "sources"
        })
        local ids = {}
        for comp_object_id, _ in pairs(competitions_by_object_id) do
            table.insert(ids, comp_object_id)
        end
        table.sort(ids)

        for i = 1, #ids do
            local item = competitions_by_object_id[ids[i]]
            local sources = {}
            for source, _ in pairs(item.sources) do
                table.insert(sources, source)
            end
            table.sort(sources)
            write_csv_row(file, {
                item.competition_object_id,
                item.competition_id or "",
                item.competition_name or safe_competition_name(item.competition_object_id),
                table.concat(sources, ";")
            })
        end
        file:close()
        add_manifest(filename, #ids, "ok")
        log("Exported competition references: " .. #ids)
    end

    -- ---------------------------------------------------------------------
    -- Manifest, log and atomic hot-folder finalization
    -- ---------------------------------------------------------------------
    SNAPSHOT_CONTEXT.managed_completed_fixture_count = managed_completed_fixture_count
    SNAPSHOT_CONTEXT.global_completed_fixture_count = global_completed_fixture_count

    do
        local filename = "manifest.csv"
        local file = open_csv(filename, {"file", "row_count", "status", "note", "byte_size"})
        for i = 1, #MANIFEST_ROWS do
            write_csv_row(file, MANIFEST_ROWS[i])
        end
        file:close()
    end

    do
        local path = output_dir .. "\\manifest.json"
        local file, err = io.open(path, "wb")
        if not file then
            error("Could not create manifest.json: " .. tostring(err))
        end

        file:write("{\r\n")
        file:write('  "schemaVersion": ' .. json_string(SCHEMA_VERSION) .. ",\r\n")
        file:write('  "exporterVersion": ' .. json_string(EXPORTER_VERSION) .. ",\r\n")
        file:write('  "game": "EA SPORTS FC 26",\r\n')
        file:write('  "snapshotId": ' .. json_string(SNAPSHOT_CONTEXT.snapshot_id) .. ",\r\n")
        file:write('  "status": "complete",\r\n')
        file:write('  "exportedAtLocal": ' .. json_string(SNAPSHOT_CONTEXT.exported_at_local) .. ",\r\n")
        file:write('  "exportedAtUtc": ' .. json_string(SNAPSHOT_CONTEXT.exported_at_utc) .. ",\r\n")
        file:write('  "career": {\r\n')
        file:write('    "fingerprintCandidate": ' .. json_string(SNAPSHOT_CONTEXT.career_fingerprint_candidate) .. ",\r\n")
        file:write('    "identityConfidence": ' .. json_string(SNAPSHOT_CONTEXT.career_identity_confidence) .. ",\r\n")
        file:write('    "managerDisplayName": ' .. json_string(SNAPSHOT_CONTEXT.manager_display_name) .. ",\r\n")
        file:write('    "managerNationalityId": ' .. json_number(SNAPSHOT_CONTEXT.manager_nationality_id, 0) .. ",\r\n")
        file:write('    "initialTeamId": ' .. json_number(SNAPSHOT_CONTEXT.initial_team_id, 0) .. ",\r\n")
        file:write('    "initialTeamName": ' .. json_string(SNAPSHOT_CONTEXT.initial_team_name) .. ",\r\n")
        file:write('    "managedTeamId": ' .. json_number(SNAPSHOT_CONTEXT.managed_team_id, 0) .. ",\r\n")
        file:write('    "managedTeamName": ' .. json_string(SNAPSHOT_CONTEXT.managed_team_name) .. ",\r\n")
        file:write('    "seasonIndex": ' .. json_number(SNAPSHOT_CONTEXT.season_index, 0) .. ",\r\n")
        file:write('    "careerDate": ' .. json_string(SNAPSHOT_CONTEXT.career_date_iso) .. ",\r\n")
        file:write('    "careerDateSort": ' .. json_number(SNAPSHOT_CONTEXT.career_date_sort, 0) .. "\r\n")
        file:write("  },\r\n")
        file:write('  "ordering": {\r\n')
        file:write('    "seasonIndex": ' .. json_number(SNAPSHOT_CONTEXT.season_index, 0) .. ",\r\n")
        file:write('    "careerDateSort": ' .. json_number(SNAPSHOT_CONTEXT.career_date_sort, 0) .. ",\r\n")
        file:write('    "managedCompletedFixtureCount": ' .. json_number(managed_completed_fixture_count, 0) .. ",\r\n")
        file:write('    "globalCompletedFixtureCount": ' .. json_number(global_completed_fixture_count, 0) .. ",\r\n")
        file:write('    "exportedAtUtc": ' .. json_string(SNAPSHOT_CONTEXT.exported_at_utc) .. ",\r\n")
        file:write('    "snapshotId": ' .. json_string(SNAPSHOT_CONTEXT.snapshot_id) .. "\r\n")
        file:write("  },\r\n")
        file:write('  "capabilities": {\r\n')
        file:write('    "resolvedPlayerNames": true,\r\n')
        file:write('    "careerAgnosticManagedTeam": true,\r\n')
        file:write('    "fixturesAndResults": true,\r\n')
        file:write('    "seasonStatistics": true,\r\n')
        file:write('    "matchRatings": true,\r\n')
        file:write('    "teamProfitability": ' .. (TEAM_PROFITABILITY_EXPORTED and "true" or "false") .. ',\r\n')
        file:write('    "teamProfitabilitySource": "teams.profitability",\r\n')
        file:write('    "actualMatchPositions": "latest_match_only",\r\n')
        file:write('    "detailedPlayerMatchStats": false,\r\n')
        file:write('    "matchEvents": false\r\n')
        file:write("  },\r\n")
        file:write('  "files": [\r\n')
        for i = 1, #MANIFEST_ROWS do
            local row = MANIFEST_ROWS[i]
            file:write("    {")
            file:write('"name":' .. json_string(row[1]) .. ",")
            file:write('"rowCount":' .. json_number(row[2], 0) .. ",")
            file:write('"status":' .. json_string(row[3]) .. ",")
            file:write('"note":' .. json_string(row[4]) .. ",")
            file:write('"byteSize":' .. json_number(row[5], 0) .. "}")
            if i < #MANIFEST_ROWS then
                file:write(",")
            end
            file:write("\r\n")
        end
        file:write("  ],\r\n")
        file:write('  "readyMarker": "READY"\r\n')
        file:write("}\r\n")
        file:close()
    end

    log("Export completed; preparing ready snapshot")

    do
        local log_file = io.open(output_dir .. "\\export_log.txt", "wb")
        if log_file then
            log_file:write(CSV_BOM)
            for i = 1, #LOG_LINES do
                log_file:write(LOG_LINES[i])
                log_file:write("\r\n")
            end
            log_file:close()
        end
    end

    local moved, move_error = move_directory(PARTIAL_DIR, READY_DIR)
    if not moved then
        error("Snapshot was exported but could not be moved to ready: " .. tostring(move_error))
    end
    output_dir = READY_DIR
    write_ready_marker(READY_DIR)

    local final_message = "FC26 snapshot export is ready:\n" .. READY_DIR
    if #unresolved_names > 0 then
        final_message = final_message .. "\n\nWarning: " .. tostring(#unresolved_names) .. " player names were unresolved."
    end

    rawset(_G, 'FC26_EXPORT_LAST_EXPORT_RESULT', {
        success = true,
        ready_dir = READY_DIR,
        snapshot_id = SNAPSHOT_ID,
        exporter_version = EXPORTER_VERSION
    })

    if not rawget(_G, 'FC26_EXPORT_SUPPRESS_SUCCESS_MESSAGE') then
        pcall(function()
            MessageBox(final_message, "FC26 Snapshot Exporter")
        end)
    end

end

local ok, error_message = xpcall(run_export, debug.traceback)
if not ok then
    rawset(_G, 'FC26_EXPORT_LAST_EXPORT_RESULT', {
        success = false,
        error = tostring(error_message),
        output_dir = output_dir,
        exporter_version = EXPORTER_VERSION
    })
    log("FATAL ERROR: " .. tostring(error_message))

    local log_file = io.open(output_dir .. "\\export_log.txt", "wb")
    if log_file then
        log_file:write(CSV_BOM)
        for i = 1, #LOG_LINES do
            log_file:write(LOG_LINES[i])
            log_file:write("\r\n")
        end
        log_file:close()
    end

    pcall(function()
        MessageBox(
            "Export failed. Please send export_log.txt from:\n" .. output_dir,
            "FC26 Snapshot Exporter - Error"
        )
    end)
end

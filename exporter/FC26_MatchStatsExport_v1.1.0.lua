-- FC26 MatchStatsExport v1.1.0
-- Production community exporter for Project Atlas Tracker.
-- Run once in a loaded Manager Career Hub before a normally played match.
-- The exporter is read-only and writes only the canonical Tracker match package
-- plus compact operational logs. Reverse-engineering probe CSVs/binary dumps are
-- disabled in this production build; validated runtime/build checks remain active.

pcall(function() require 'imports/core/live_editor' end)
pcall(function() require 'imports/career_mode/helpers' end)
pcall(function() require 'imports/services/enums' end)

assert(type(IsInCM) == 'function' and IsInCM(),
    'Load a Manager Career before running this exporter.')
assert(MEMORY and type(MEMORY.ReadBytes) == 'function',
    'MEMORY API is unavailable.')
assert(type(AddEventHandler) == 'function',
    'Live Editor CareerModeEvent API is unavailable.')
assert(type(GetPlugin) == 'function', 'GetPlugin is unavailable.')

local VERSION = '1.1.0'
local CSV_BOM = '\239\187\191'
local EXPORT_DIAGNOSTICS = false
local STATE_KEY = 'FC26_EXPORT_MATCH_STATS_AUTOMATIC_PLAYER_EXPORTER_STATE'

local EVENT_ENTERED_HUB = 26
local EVENT_ABOUT_TO_ENTER_MATCH = 42
local EVENT_RUNTIME_PULSE = 67
local EVENT_SCREEN_LOADED = 68
local EVENT_PREPARE_FOR_SAVE = 28
local FINAL_CANDIDATE_EVENTS = { [137] = true }

local ACCESSOR_RVA = 0x2F58290
local EXPECTED_STATIC_SLOT_RVA = 0xD9ABDC8
local VALUE_GETTER_RVA = 0x6AB23E0
local VALUE_GETTER_BYTES = 0x170
local SLOT37_RVA = 0x6AB25F0
local SLOT50_RVA = 0x6AAC180
local WORKER_CALLSITE_RVA = 0x6AAD865
local HANDLER_CALLSITE_RVA = 0x6AACDB5
local SINGLETON_INTERFACE_OFFSET = 0xAF0
local INTERFACE_STATS_ROOT_OFFSET = 0x38FE0
local TEAM_STRIDE = 0x23800
local TEAM_PLAYER_ARRAY_OFFSET = 0x10
local TEAM_PLAYER_COUNT_OFFSET = 0x30
local TEAM_SELECTOR_BASE_OFFSET = 0x34
local TEAM_TOTALS_OFFSET = 0x226B0
local PLAYER_VALUES_OFFSET = 0xA0
local MAX_GETTER_KEY = 174
local GETTER_VALUE_BYTES = (MAX_GETTER_KEY + 1) * 4
local PLAYER_OBJECT_READ_BYTES = 0x604
local PARALLEL_STATE_POINTER_OFFSET = 0x08
local PARALLEL_STATE_ALLOCATION_STRIDE = 0x5C80
local PARALLEL_STATE_DIRECT_PLAYER_ID_OFFSET = 0x2A14
local DIRECT_PLAYER_ID_BYTES = 4

-- v0.32/v0.33 established the two allocation strides below as safe
-- per-object read bounds when a current same-team forward neighbour proves the
-- exact live spacing. All v0.41-only diagnostics are grouped in one table so
-- the main Lua chunk stays below Lua's 200-active-local-variable limit.
local SPECIAL = {
    PLAYER_OBJECT_ALLOCATION_STRIDE = 0x1160,
    PLAYER_SPECIAL_NPK_XG_OFFSET = 0x5F0,
    PLAYER_SPECIAL_XA_OFFSET = 0x600,
    TEAM_SPECIAL_NPK_XG_OFFSET = 0x22E60,
    TEAM_SPECIAL_XA_OFFSET = 0x22E64,
    PLAYER_OBJECT_WINDOW_BYTES = 0x1160,
    PARALLEL_STATE_WINDOW_BYTES = PARALLEL_STATE_ALLOCATION_STRIDE,
    WORKER_REGION_RVA = 0x6AAC8DE,
    WORKER_REGION_END_RVA = 0x6AAD8D5,
    SERVICE_OBJECT_WINDOW_BYTES = 0x200,
    SERVICE_VTABLE_SLOTS = 40,
    SERVICE_METHOD_WINDOW_BYTES = 0x200,
    CHILD_OBJECT_WINDOW_BYTES = 0x400,
    CHILD_VTABLE_SLOTS = 16,
    GAME_RATINGS_VECTOR_RECORD_BYTES = 0x20,
    GAME_RATINGS_VECTOR_MAX_RECORDS = 64,
    -- v0.38 disassembly proved that MOTM +0x30 is the rating-provider child.
    -- Its +0x08 state owns two code-confirmed 52 x 0x44 team record arrays.
    RATING_CHILD_FIELD_OFFSET = 0x30,
    RATING_CHILD_STATE_OFFSET = 0x08,
    RATING_STATE_WINDOW_BYTES = 0x100,
    RATING_TEAM_RECORD_ARRAY_BASE_OFFSET = 0x28,
    RATING_TEAM_RECORD_POINTER_STRIDE = 0x08,
    RATING_TEAM_RECORD_BYTES = 0x44,
    RATING_TEAM_RECORD_COUNT = 52,
    RATING_METRIC_MATRIX_BASE_OFFSET = 0x10,
    RATING_METRIC_MATRIX_POINTER_STRIDE = 0x08,
    RATING_METRIC_INDEX_STRIDE = 0x10E,
    RATING_METRIC_MATRIX_PREFIX_BYTES = 0x1000,
    RATING_METRIC_MATRIX_FULL_BYTES = 52 * 0x10E * 4,
    RATING_SELECTED_TEAM_OFFSET = 0x04,
    RATING_SELECTED_PLAYER_BASE_OFFSET = 0x08,
    RATING_SELECTOR_RVA = 0x36A1360,
    RATING_GETTER_RVA = 0x36A1B40,
    RATING_RAW_GAMEPLAY_PLAYER_OFFSET = 0x3CC,
    RATING_GLOBAL_POINTER_SLOT_RVA = 0xEBCD2D0,
    RATING_GLOBAL_OBJECT_WINDOW_BYTES = 0x200,
    -- v0.40 offline disassembly of 0x2EAE540 proved that the actual gameplay
    -- rating manager is selected from a second global root, independently of
    -- the +0xFC context ID above.
    RATING_MANAGER_ROOT_SLOT_RVA = 0xD9AB9C0,
    RATING_MANAGER_ACTIVE_INDEX_OFFSET = 0x2B2E60,
    RATING_MANAGER_BUCKET_COUNT = 10,
    RATING_MANAGER_BUCKET_STRIDE = 0x45170,
    RATING_MANAGER_READY_FLAG_OFFSET = 0x45160,
    RATING_GAMEPLAY_RECORD_MAX_COUNT = 128,
    RATING_CONTEXT_ID_OFFSET = 0xFC,
    RATING_CONTEXT_RESOLVER_INNER_RVA = 0x2EAE540,
    RATING_CONTEXT_RESOLVER_CLEANUP_RVA = 0x2EC51F0,
    RATING_GAMEPLAY_ARRAY_BEGIN_OFFSET = 0x14F90,
    RATING_GAMEPLAY_ARRAY_END_OFFSET = 0x14F98,
    RATING_GAMEPLAY_RECORD_BYTES = 0xB80,
    RATING_GAMEPLAY_RECORD_INDEX_OFFSET = 0x00,
    RATING_GAMEPLAY_RECORD_TEAM_OFFSET = 0x04,
    RATING_GAMEPLAY_RECORD_PLAYER_ID_OFFSET = 0x08,
    RATING_SCALE_CONSTANT_RVA = 0xA7C537C,
    RATING_BIAS_CONSTANT_RVA = 0xA7B08BC,
    RATING_STATIC_TARGETS = {
        { label = 'motm_rating_selector_slot1', kind = 'code', rva = 0x36A1360, bytes = 0x400 },
        { label = 'motm_rating_getter_slot2', kind = 'code', rva = 0x36A1B40, bytes = 0x200 },
        { label = 'rating_resolve_helper_1', kind = 'code', rva = 0x89E1C40, bytes = 0x200 },
        { label = 'rating_resolve_helper_2', kind = 'code', rva = 0x89DEDA0, bytes = 0x200 },
        { label = 'rating_resolve_helper_3', kind = 'code', rva = 0x2EC4E80, bytes = 0x200 },
        { label = 'rating_resolve_helper_4', kind = 'code', rva = 0x2EC8C40, bytes = 0x200 },
        { label = 'rating_resolve_helper_5', kind = 'code', rva = 0x2EB44C0, bytes = 0x200 },
        { label = 'rating_resolve_helper_6', kind = 'code', rva = 0x2EB45F0, bytes = 0x200 },
        { label = 'rating_context_resolver_inner', kind = 'code', rva = 0x2EAE540, bytes = 0x800 },
        { label = 'rating_context_resolver_cleanup', kind = 'code', rva = 0x2EC51F0, bytes = 0x200 },
        { label = 'rating_quantize_helper', kind = 'code', rva = 0x6467CB8, bytes = 0x200 },
        { label = 'rating_scale_constant', kind = 'f32_constant', rva = 0xA7C537C, bytes = 0x10 },
        { label = 'rating_bias_constant', kind = 'f32_constant', rva = 0xA7B08BC, bytes = 0x10 }
    },
    MAX_WINDOW_PLAYER_RECORDS = 40,
    handler_windows_exported = 0,
    service_enum_candidates = 0,
    service_snapshots_exported = 0,
    service_vtable_rows_exported = 0,
    player_object_windows_exported = 0,
    parallel_state_windows_exported = 0,
    special_float_rows_exported = 0,
    service_child_snapshots_exported = 0,
    service_child_vtable_rows_exported = 0,
    game_ratings_vectors_exported = 0,
    rating_provider_states_exported = 0,
    rating_team_arrays_exported = 0,
    rating_team_record_rows_exported = 0,
    rating_metric_prefixes_exported = 0,
    rating_metric_full_matrices_exported = 0,
    motm_selection_rows_exported = 0,
    rating_resolver_snapshots_exported = 0,
    game_rating_rows_exported = 0,
    rating_static_targets_exported = 0,
    latest_game_ratings = {},
    latest_motm_team_index = nil,
    latest_motm_player_id = nil,
    service_capture_index = 0,
    MOTM_CHILDREN = {
        { offset = 0x20, label = 'slot6_child' },
        { offset = 0x28, label = 'slot5_child' },
        { offset = 0x30, label = 'slot7_rating_provider_candidate' },
        { offset = 0x38, label = 'slot8_child' },
        { offset = 0x40, label = 'slot9_child' }
    },
    FIELDS = {
        {
            semantic = 'npk_expected_goals', source_label = 'NPK_EXPECTED_GOALS',
            selector = 2, field_id = 3, internal_kind_id = 8,
            transform_id = 1, descriptor_rva = 0xB5AAEA8,
            handler_rva = 0x6AAD1D5, handler_end_rva = 0x6AAD225
        },
        {
            semantic = 'expected_assists', source_label = 'EXPECTED_ASSISTS',
            selector = 3, field_id = 24, internal_kind_id = 2,
            transform_id = 1, descriptor_rva = 0xB5AB188,
            handler_rva = 0x6AAD134, handler_end_rva = 0x6AAD185
        }
    }
}

local MAX_PERIODIC_STATS_SNAPSHOTS = 2
local MAX_STATS_SNAPSHOTS = 3
local MAX_PLAYERS_PER_TEAM = 64
local MAX_LIFECYCLE_SAMPLES = 512
local MAX_TRACKER_OUTER_NODES = 64
local MAX_TRACKER_DEPTH = 32
local MAX_TRACKER_CAPTURES = 2
local MAX_TRACKER_NESTED_PER_PLAYER = 128
local MAX_TRACKER_NESTED_TOTAL = 1024
local TRACKER_OUTER_NODE_BYTES = 0x50
local TRACKER_NESTED_NODE_BYTES = 0x28
local MAX_MEMORY_READ_CALLS = 4096
local MAX_MEMORY_BYTES = 4 * 1024 * 1024
local PERIODIC_CAPTURE_MIN_GAP_SECONDS = 120
local RUNTIME_SAMPLE_MIN_GAP_SECONDS = 5

local SURFACE_PAIRS = {
    { semantic = 'goals', matchanalysis_key = 0, tracker_key = 214,
      evidence_status = 'confirmed' },
    { semantic = 'assists', matchanalysis_key = 3, tracker_key = 11,
      evidence_status = 'confirmed' },
    { semantic = 'completed_passes', matchanalysis_key = 16,
      tracker_key = 215, evidence_status = 'confirmed' },
    { semantic = 'interceptions', matchanalysis_key = 24,
      tracker_key = 6, evidence_status = 'confirmed' },
    { semantic = 'completed_dribbles', matchanalysis_key = 31,
      tracker_key = 174, evidence_status = 'very_high' }
}

-- These 70 counters use the code-confirmed direct int32 getter layout. They
-- are a separate number space from MatchEventTracker keys.
local DIRECT_EXPORT_FIELDS = {
    { key = 1, column = 'npk_goals' },
    { key = 2, column = 'own_goals' },
    { key = 3, column = 'assists' },
    { key = 4, column = 'secondary_assist' },
    { key = 5, column = 'yellow_card_events' },
    { key = 6, column = 'red_dismissals' },
    { key = 7, column = 'minutes_played' },
    { key = 8, column = 'shots' },
    { key = 9, column = 'shots_on_target' },
    { key = 12, column = 'pk_goals' },
    { key = 13, column = 'passes' },
    { key = 16, column = 'passes_completed' },
    { key = 17, column = 'fouls_committed' },
    { key = 18, column = 'saves' },
    { key = 19, column = 'tackles' },
    { key = 24, column = 'interceptions' },
    { key = 25, column = 'goals_conceded' },
    { key = 26, column = 'offsides' },
    { key = 30, column = 'dribbles' },
    { key = 31, column = 'dribbles_completed' },
    { key = 37, column = 'fouls_won' },
    { key = 41, column = 'shootout_goals' },
    { key = 44, column = 'blocks' },
    { key = 49, column = 'clearances' },
    { key = 51, column = 'fk_goals' },
    { key = 54, column = 'crosses_attempted' },
    { key = 55, column = 'crosses_delivered' },
    { key = 56, column = 'crosses_blocked' },
    { key = 66, column = 'punches' },
    { key = 68, column = 'dives_at_feet' },
    { key = 85, column = 'stand_tackles' },
    { key = 88, column = 'slide_tackles' },
    { key = 91, column = 'key_passes' },
    { key = 92, column = 'penalties_committed' },
    { key = 97, column = 'skillmove_beats' },
    { key = 98, column = 'possession_won' },
    { key = 99, column = 'possession_lost' },
    { key = 104, column = 'shots_against' },
    { key = 105, column = 'penalty_saves' },
    { key = 107, column = 'shootout_saves' },
    { key = 112, column = 'stand_tackles_won' },
    { key = 113, column = 'slide_tackles_won' },
    { key = 114, column = 'penalties_won' },
    { key = 115, column = 'beaten_by_opponent' },
    { key = 116, column = 'beaten_in_defensive_third' },
    { key = 117, column = 'beaten_in_box' },
    { key = 119, column = 'saving_shots_on_target' },
    { key = 121, column = 'shootout_goals_conceded' },
    { key = 122, column = 'penalty_goals_conceded' },
    { key = 123, column = 'passes_intercepted' },
    { key = 124, column = 'nutmegs' },
    { key = 125, column = 'knock_ons' },
    { key = 127, column = 'shots_blocked' },
    { key = 128, column = 'offside_passes' },
    { key = 129, column = 'tackled_by_opponent' },
    { key = 137, column = 'beat_with_pass' },
    { key = 143, column = 'offense_duels_attempted' },
    { key = 144, column = 'offense_duels_won' },
    { key = 145, column = 'defense_duels_attempted' },
    { key = 146, column = 'defense_duels_won' },
    { key = 147, column = 'aerial_duels_attempted' },
    { key = 148, column = 'aerial_duels_won' },
    { key = 151, column = 'passes_under_pressure' },
    { key = 152, column = 'passes_completed_under_pressure' },
    { key = 155, column = 'offsides_caused' },
    { key = 156, column = 'corners_won' },
    { key = 159, column = 'assists_from_shots' },
    { key = 160, column = 'assists_from_dummy' },
    { key = 173, column = 'save_punch_to_clearance' },
    { key = 174, column = 'saving_crosses' }
}

-- These are MatchEventTracker keys, not MatchAnalysis storage keys. Their
-- explicit prefix prevents the two number spaces from being confused.
local TRACKER_EXPORT_FIELDS = {
    { key = 152,
      column = 'tracker_completed_through_passes_including_lobbed' },
    { key = 217, column = 'tracker_non_set_piece_shots' }
}

local SPECIAL_FLOAT_EXPORT_FIELDS = {
    { semantic = 'npk_expected_goals', source_label = 'NPK_EXPECTED_GOALS',
      column = 'npk_expected_goals', player_offset = SPECIAL.PLAYER_SPECIAL_NPK_XG_OFFSET,
      team_offset = SPECIAL.TEAM_SPECIAL_NPK_XG_OFFSET },
    { semantic = 'expected_assists', source_label = 'EXPECTED_ASSISTS',
      column = 'expected_assists', player_offset = SPECIAL.PLAYER_SPECIAL_XA_OFFSET,
      team_offset = SPECIAL.TEAM_SPECIAL_XA_OFFSET }
}

local DERIVED_EXPORT_COLUMNS = {
    'goals_derived', 'shots_off_target_derived',
    'passes_incomplete_derived', 'dribbles_failed_derived',
    'pass_accuracy_pct_derived', 'dribble_success_pct_derived',
    'cross_success_pct_derived', 'stand_tackle_success_pct_derived',
    'slide_tackle_success_pct_derived',
    'offense_duel_success_pct_derived',
    'defense_duel_success_pct_derived',
    'aerial_duel_success_pct_derived', 'save_success_pct_derived'
}

local DIRECT_FIELD_BY_KEY = {}
for _, field in ipairs(DIRECT_EXPORT_FIELDS) do
    DIRECT_FIELD_BY_KEY[field.key] = field.column
end

local GETTER_SIGNATURES = {
    { offset = 0x000, bytes = {
        0x48, 0x89, 0x5C, 0x24, 0x20, 0x57, 0x41, 0x56,
        0x41, 0x57, 0x48, 0x83, 0xEC, 0x40
    }, role = 'function_prolog' },
    { offset = 0x00E, bytes = {
        0x48, 0x8B, 0x99, 0xE0, 0x8F, 0x03, 0x00
    }, role = 'interface_stats_root_load' },
    { offset = 0x04A, bytes = {
        0x83, 0xFA, 0xFE, 0x0F, 0x85
    }, role = 'all_teams_selector_minus_2_branch' },
    { offset = 0x05A, bytes = {
        0x48, 0x8D, 0xAB, 0x00, 0x70, 0x04, 0x00
    }, role = 'two_team_total_span' },
    { offset = 0x07D, bytes = {
        0x49, 0x63, 0xC0, 0x8B, 0x8C, 0x83, 0xB0, 0x26,
        0x02, 0x00
    }, role = 'team_total_key_index' },
    { offset = 0x098, bytes = {
        0x48, 0x8B, 0x43, 0x10, 0x49, 0x63, 0xC8, 0x48,
        0x8B, 0x04, 0xD0, 0x8B, 0x8C, 0x88, 0xA0, 0x00,
        0x00, 0x00
    }, role = 'player_pointer_and_key_index' },
    { offset = 0x0CA, bytes = {
        0x48, 0x81, 0xC3, 0x00, 0x38, 0x02, 0x00
    }, role = 'team_stride_loop' },
    { offset = 0x10E, bytes = {
        0x4C, 0x69, 0xC8, 0x00, 0x38, 0x02, 0x00
    }, role = 'selected_team_stride' },
    { offset = 0x11E, bytes = {
        0x43, 0x8B, 0xBC, 0x99, 0xB0, 0x26, 0x02, 0x00
    }, role = 'selected_team_total_key_index' },
    { offset = 0x148, bytes = {
        0x49, 0x8B, 0x41, 0x10, 0x4A, 0x8B, 0x04, 0xC0,
        0x42, 0x8B, 0xBC, 0x98, 0xA0, 0x00, 0x00, 0x00
    }, role = 'selected_player_key_index' },
    { offset = 0x165, bytes = {
        0x41, 0x5E, 0x5F, 0xC3
    }, role = 'function_end' }
}

local existing_state = rawget(_G, STATE_KEY)
if type(existing_state) == 'table' and existing_state.active then
    error('Automatic Player Stats Exporter ' .. tostring(existing_state.version or 'legacy') .. ' is already running.')
end

local function safe_tostring(value)
    local ok, text = pcall(tostring, value)
    if ok then return text end
    return '<tostring_error>'
end

local function scalar(value, max_length)
    if value == nil then return '' end
    local value_type = type(value)
    local text
    if value_type == 'string' then
        text = value
    elseif value_type == 'number' or value_type == 'boolean' then
        text = safe_tostring(value)
    else
        text = '<' .. value_type .. '>'
    end
    max_length = max_length or 16384
    if #text > max_length then
        text = text:sub(1, max_length) .. '<truncated>'
    end
    return text
end

local function stat_value(values, key)
    if type(values) ~= 'table' then return 0 end
    return tonumber(values[key]) or 0
end

local function special_float_value(values, semantic)
    if type(values) ~= 'table' then return '' end
    local entry = values[semantic]
    if type(entry) ~= 'table' or type(entry.value) ~= 'number' then return '' end
    return string.format('%.6f', entry.value)
end

local function nonnegative_difference(total, first, second)
    local result = total - first - (second or 0)
    if result < 0 then return '' end
    return result
end

local function percentage(numerator, denominator)
    if denominator <= 0 then return '' end
    return string.format('%.4f', numerator * 100 / denominator)
end

local function derived_export_values(values)
    local npk_goals = stat_value(values, 1)
    local pk_goals = stat_value(values, 12)
    local shots = stat_value(values, 8)
    local shots_on_target = stat_value(values, 9)
    local shots_blocked = stat_value(values, 127)
    local passes = stat_value(values, 13)
    local passes_completed = stat_value(values, 16)
    local dribbles = stat_value(values, 30)
    local dribbles_completed = stat_value(values, 31)
    local crosses_attempted = stat_value(values, 54)
    local crosses_delivered = stat_value(values, 55)
    local stand_tackles = stat_value(values, 85)
    local stand_tackles_won = stat_value(values, 112)
    local slide_tackles = stat_value(values, 88)
    local slide_tackles_won = stat_value(values, 113)
    local offense_duels = stat_value(values, 143)
    local offense_duels_won = stat_value(values, 144)
    local defense_duels = stat_value(values, 145)
    local defense_duels_won = stat_value(values, 146)
    local aerial_duels = stat_value(values, 147)
    local aerial_duels_won = stat_value(values, 148)
    local saves = stat_value(values, 18)
    local goals_conceded = stat_value(values, 25)
    return {
        npk_goals + pk_goals,
        nonnegative_difference(shots, shots_on_target, shots_blocked),
        nonnegative_difference(passes, passes_completed),
        nonnegative_difference(dribbles, dribbles_completed),
        percentage(passes_completed, passes),
        percentage(dribbles_completed, dribbles),
        percentage(crosses_delivered, crosses_attempted),
        percentage(stand_tackles_won, stand_tackles),
        percentage(slide_tackles_won, slide_tackles),
        percentage(offense_duels_won, offense_duels),
        percentage(defense_duels_won, defense_duels),
        percentage(aerial_duels_won, aerial_duels),
        percentage(saves, saves + goals_conceded)
    }
end

local function append_export_values(row, values, tracker_values, special_values)
    for _, field in ipairs(DIRECT_EXPORT_FIELDS) do
        row[#row + 1] = stat_value(values, field.key)
    end
    for _, field in ipairs(SPECIAL_FLOAT_EXPORT_FIELDS) do
        row[#row + 1] = special_float_value(special_values, field.semantic)
    end
    for _, field in ipairs(TRACKER_EXPORT_FIELDS) do
        row[#row + 1] = stat_value(tracker_values, field.key)
    end
    for _, value in ipairs(derived_export_values(values)) do
        row[#row + 1] = value
    end
end

local function csv_escape(value)
    local text = scalar(value)
    if text:find('[,"\r\n]') then
        text = '"' .. text:gsub('"', '""') .. '"'
    end
    return text
end

local function write_csv_row(file, values)
    local output = {}
    for index = 1, #values do output[index] = csv_escape(values[index]) end
    file:write(table.concat(output, ','), '\r\n')
    file:flush()
end

local function ensure_dir(path)
    pcall(function()
        os.execute('cmd.exe /C if not exist "' .. path .. '" mkdir "' .. path .. '"')
    end)
    local test_path = path .. '\\.__fc26_dir_test.tmp'
    local test_file = io.open(test_path, 'wb')
    if not test_file then
        pcall(function()
            os.execute('if not exist "' .. path .. '" mkdir "' .. path .. '"')
        end)
        test_file = io.open(test_path, 'wb')
    end
    if not test_file then
        error('Could not create or write to folder: ' .. path)
    end
    test_file:write('ok')
    test_file:close()
    pcall(os.remove, test_path)
end

local function open_unbuffered(path, mode)
    local file, err = io.open(path, mode or 'wb')
    if not file then error('Could not open ' .. path .. ': ' .. scalar(err)) end
    pcall(function() file:setvbuf('no') end)
    return file
end

local NULL_FILE = {
    write = function(...) end,
    flush = function(...) end,
    close = function(...) end
}

local function open_diagnostic_csv(output_dir, name, headers)
    return NULL_FILE
end

local function open_csv(output_dir, name, headers)
    local file = open_unbuffered(output_dir .. '\\' .. name, 'wb')
    file:write(CSV_BOM)
    write_csv_row(file, headers)
    return file
end

local function now_text()
    return os.date('%Y-%m-%d %H:%M:%S')
end

local function now_epoch()
    return os.time()
end

local function byte_at(bytes, offset0)
    if type(bytes) ~= 'table' then return nil end
    local value = bytes[offset0 + 1]
    if value == nil then return nil end
    value = tonumber(value) or 0
    if value < 0 then value = value + 256 end
    return value % 256
end

local function le_u32(bytes, offset0)
    local b0 = byte_at(bytes, offset0)
    local b1 = byte_at(bytes, offset0 + 1)
    local b2 = byte_at(bytes, offset0 + 2)
    local b3 = byte_at(bytes, offset0 + 3)
    if b0 == nil or b1 == nil or b2 == nil or b3 == nil then return nil end
    return b0 + b1 * 0x100 + b2 * 0x10000 + b3 * 0x1000000
end

local function le_s32(bytes, offset0)
    local value = le_u32(bytes, offset0)
    if value == nil then return nil end
    if value >= 0x80000000 then return value - 0x100000000 end
    return value
end

local function le_f32(bytes, offset0)
    local raw = le_u32(bytes, offset0)
    if raw == nil then return nil end
    -- Arithmetic IEEE-754 decode avoids depending on Lua bitwise operators.
    local sign = raw >= 0x80000000 and -1 or 1
    local magnitude = raw % 0x80000000
    local exponent = math.floor(magnitude / 0x800000)
    local fraction = magnitude % 0x800000
    if exponent == 0xFF then return nil end
    if exponent == 0 then
        if fraction == 0 then return sign == 1 and 0.0 or -0.0 end
        return sign * (fraction / 8388608.0) * (2.0 ^ -126)
    end
    return sign * (1.0 + fraction / 8388608.0) *
        (2.0 ^ (exponent - 127))
end

local function le_u64_exact(bytes, offset0)
    local lo = le_u32(bytes, offset0)
    local hi = le_u32(bytes, offset0 + 4)
    if lo == nil or hi == nil then return nil end
    if hi >= 0x00200000 then return nil end
    return lo + hi * 0x100000000
end

local function ptr_hex(value)
    value = tonumber(value)
    if value == nil then return '' end
    local integer = math.tointeger and math.tointeger(value) or nil
    if integer == nil then return string.format('%.0f', value) end
    return string.format('0x%016X', integer)
end

local function hex_u32(value)
    value = tonumber(value)
    if value == nil then return '' end
    local integer = math.tointeger and math.tointeger(value) or value
    if integer == nil then return '' end
    return string.format('0x%08X', integer % 0x100000000)
end

local function offset_hex(value)
    return string.format('0x%04X', tonumber(value) or 0)
end

local function is_plausible_pointer(value)
    value = tonumber(value) or 0
    return value >= 0x10000 and value < 0x0000800000000000
end

local function bytes_to_hex(bytes, offset0, length)
    local parts = {}
    for index = 0, length - 1 do
        local value = byte_at(bytes, offset0 + index)
        if value == nil then break end
        parts[#parts + 1] = string.format('%02X', value)
    end
    return table.concat(parts, ' ')
end

function SPECIAL.filename_token(value)
    local text = scalar(value, 160)
    text = text:gsub('[^%w%._%-]+', '_')
    if text == '' then text = 'unnamed' end
    return text
end

function SPECIAL.write_binary_bytes(path, bytes)
    if not EXPORT_DIAGNOSTICS then return true, 'disabled' end
    if type(bytes) ~= 'table' then return false, 'bytes_not_table' end
    local file, err = io.open(path, 'wb')
    if not file then return false, scalar(err) end
    pcall(function() file:setvbuf('no') end)
    local chunk = {}
    for offset0 = 0, #bytes - 1 do
        chunk[#chunk + 1] = string.char(byte_at(bytes, offset0) or 0)
        if #chunk >= 256 then
            file:write(table.concat(chunk))
            chunk = {}
        end
    end
    if #chunk > 0 then file:write(table.concat(chunk)) end
    file:flush()
    file:close()
    return true, 'ok'
end

local function bytes_match(bytes, offset0, expected)
    for index = 1, #expected do
        if byte_at(bytes, offset0 + index - 1) ~= expected[index] then
            return false
        end
    end
    return true
end

local function decode_rel32(bytes, source_pointer, offset0)
    if byte_at(bytes, offset0) ~= 0xE8 then return nil end
    local displacement = le_s32(bytes, offset0 + 1)
    if displacement == nil then return nil end
    return source_pointer + offset0 + 5 + displacement
end

local user_profile = os.getenv('USERPROFILE')
assert(type(user_profile) == 'string' and user_profile ~= '',
    'USERPROFILE environment variable is unavailable.')

-- Standalone community output. No ExportPath.txt and no external program
-- configuration is required. A successful capture is atomically published from
-- MatchStats\incoming to MatchStats\ready.
local PIPELINE_ROOT = user_profile .. '\\Documents\\FC26 Export'
local PIPELINE_CAPTURE_ID = os.date('%Y%m%d_%H%M%S')
local PIPELINE_AUTOMANAGED = true
local PIPELINE_CAREER_FINGERPRINT = ''
local folder_stamp = PIPELINE_CAPTURE_ID
local folder_token = PIPELINE_CAPTURE_ID
folder_token = tostring(folder_token):gsub('[^%w_%-]', '_')
local export_folder_name = 'FC26_MatchStats_' .. folder_token
local output_dir
local ready_output_dir = nil
if type(PIPELINE_ROOT) == 'string' and PIPELINE_ROOT ~= '' then
    local match_stats_root = PIPELINE_ROOT .. '\\MatchStats'
    local incoming_root = match_stats_root .. '\\incoming'
    local ready_root = match_stats_root .. '\\ready'
    ensure_dir(PIPELINE_ROOT)
    ensure_dir(match_stats_root)
    ensure_dir(incoming_root)
    ensure_dir(ready_root)
    output_dir = incoming_root .. '\\' .. export_folder_name .. '.partial'
    ready_output_dir = ready_root .. '\\' .. export_folder_name
end
ensure_dir(output_dir)
SPECIAL.dir = output_dir .. '\\diag'
if EXPORT_DIAGNOSTICS then ensure_dir(SPECIAL.dir) end

local participant_export_headers = {
    'snapshot_id', 'tracker_capture_id', 'trigger', 'team_index',
    'array_index', 'selector_signed', 'player_id', 'player_name',
    'binding_source', 'tracker_participant'
}
local team_export_headers = {
    'snapshot_id', 'trigger', 'team_index'
}
for _, field in ipairs(DIRECT_EXPORT_FIELDS) do
    participant_export_headers[#participant_export_headers + 1] = field.column
    team_export_headers[#team_export_headers + 1] = field.column
end
for _, field in ipairs(SPECIAL_FLOAT_EXPORT_FIELDS) do
    participant_export_headers[#participant_export_headers + 1] = field.column
    team_export_headers[#team_export_headers + 1] = field.column
end
for _, field in ipairs(TRACKER_EXPORT_FIELDS) do
    participant_export_headers[#participant_export_headers + 1] = field.column
    team_export_headers[#team_export_headers + 1] = field.column
end
for _, column in ipairs(DERIVED_EXPORT_COLUMNS) do
    participant_export_headers[#participant_export_headers + 1] = column
    team_export_headers[#team_export_headers + 1] = column
end
participant_export_headers[#participant_export_headers + 1] = 'man_of_the_match'
participant_export_headers[#participant_export_headers + 1] = 'game_rating'

local progress = open_unbuffered(output_dir .. '\\00_progress.log', 'wb')
local validation_csv = open_diagnostic_csv(output_dir, '01_build_validation.csv', {
    'target', 'rva_hex', 'check_offset_hex', 'role', 'expected_hex',
    'actual_hex', 'validation_status'
})
local lifecycle_csv = open_diagnostic_csv(output_dir, '02_lifecycle_samples.csv', {
    'sample_id', 'real_timestamp', 'trigger', 'phase', 'event_id',
    'seconds_since_match_start', 'static_slot_pointer_hex',
    'singleton_pointer_hex', 'interface_pointer_hex', 'snapshot_id',
    'tracker_capture_id', 'tracker_status', 'correlation_status', 'status'
})
local interface_csv = open_diagnostic_csv(output_dir, '03_interface_resolution.csv', {
    'snapshot_id', 'trigger', 'singleton_pointer_hex',
    'interface_pointer_hex', 'vtable_pointer_hex', 'slot37_pointer_hex',
    'slot37_rva_hex', 'slot50_pointer_hex', 'slot50_rva_hex',
    'stats_root_field_pointer_hex', 'stats_root_pointer_hex', 'status'
})
local team_blocks_csv = open_diagnostic_csv(output_dir, '04_team_blocks.csv', {
    'snapshot_id', 'trigger', 'team_index', 'team_block_pointer_hex',
    'player_array_pointer_hex', 'player_count', 'selector_base_signed',
    'team_stride_hex', 'team_totals_offset_hex', 'header_hex', 'status'
})
local player_pointers_csv = open_diagnostic_csv(output_dir, '05_player_pointer_table.csv', {
    'snapshot_id', 'trigger', 'team_index', 'array_index',
    'selector_signed', 'player_pointer_hex', 'status'
})
local team_values_csv = open_diagnostic_csv(output_dir, '06_team_getter_values.csv', {
    'snapshot_id', 'trigger', 'team_index', 'getter_key',
    'value_signed', 'value_raw_hex'
})
local player_values_csv = open_diagnostic_csv(output_dir, '07_player_getter_values.csv', {
    'snapshot_id', 'trigger', 'team_index', 'array_index',
    'selector_signed', 'player_pointer_hex', 'getter_key',
    'value_signed', 'value_raw_hex'
})
local tracker_captures_csv = open_diagnostic_csv(output_dir,
    '08_tracker_capture_summary.csv', {
        'capture_id', 'real_timestamp', 'trigger', 'elapsed_seconds',
        'reported_outer_count', 'enumerated_outer_count',
        'nested_total', 'status'
    })
local tracker_players_csv = open_diagnostic_csv(output_dir,
    '09_tracker_player_summary.csv', {
        'capture_id', 'trigger', 'enumerated_index',
        'outer_node_pointer_hex', 'player_id', 'player_name',
        'outer_depth', 'nested_candidate_count',
        'nested_enumerated_count', 'nested_max_depth', 'count_matches'
    })
local tracker_values_csv = open_diagnostic_csv(output_dir,
    '10_tracker_nested_key_values.csv', {
        'capture_id', 'trigger', 'player_id', 'player_name',
        'key_id', 'value', 'color_flag'
    })
local surface_pairs_csv = open_diagnostic_csv(output_dir,
    '11_surface_pairs.csv', {
        'semantic', 'matchanalysis_storage_key', 'tracker_key',
        'evidence_status'
    })
local correlation_csv = open_diagnostic_csv(output_dir,
    '12_player_correlation_candidates.csv', {
        'snapshot_id', 'tracker_capture_id', 'trigger',
        'team_index', 'array_index', 'selector_signed',
        'player_pointer_hex', 'tracker_player_id', 'tracker_player_name',
        'ma_goals', 'tracker_goals', 'ma_assists', 'tracker_assists',
        'ma_completed_passes', 'tracker_completed_passes',
        'ma_interceptions', 'tracker_interceptions',
        'ma_completed_dribbles', 'tracker_completed_dribbles',
        'matchanalysis_signature_nonzero', 'tracker_signature_nonzero',
        'mismatch_count', 'absolute_difference_sum', 'exact_match'
    })
local bindings_csv = open_diagnostic_csv(output_dir,
    '13_unique_player_bindings.csv', {
        'snapshot_id', 'tracker_capture_id', 'trigger',
        'team_index', 'array_index', 'selector_signed',
        'player_pointer_hex', 'tracker_player_id', 'tracker_player_name',
        'signature', 'binding_status'
    })
local direct_identity_csv = open_diagnostic_csv(output_dir,
    '14_direct_identity_values.csv', {
        'snapshot_id', 'trigger', 'team_index', 'array_index',
        'selector_signed', 'player_pointer_hex',
        'parallel_state_pointer_hex', 'direct_field_pointer_hex',
        'forward_stride_proof', 'backward_stride_proof',
        'direct_player_id', 'direct_player_id_raw_hex', 'status'
    })
local direct_validation_csv = open_diagnostic_csv(output_dir,
    '15_direct_identity_runtime_validation.csv', {
        'snapshot_id', 'tracker_capture_id', 'trigger',
        'snapshot_player_objects', 'direct_reads_successful',
        'structurally_skipped_objects', 'direct_nonzero_ids',
        'unique_direct_ids', 'duplicate_direct_ids',
        'tracker_participants', 'tracker_ids_in_direct_set',
        'tracker_ids_missing_direct', 'direct_ids_in_tracker',
        'direct_ids_not_in_tracker', 'status'
    })
local participants_export_csv = open_csv(output_dir,
    '16_match_participants_wide.csv', participant_export_headers)
local identity_manifest_csv = open_diagnostic_csv(output_dir,
    '17_match_identity_manifest.csv', {
        'snapshot_id', 'tracker_capture_id', 'trigger', 'team_index',
        'array_index', 'selector_signed', 'player_pointer_hex',
        'parallel_state_pointer_hex', 'direct_player_id',
        'resolved_player_id', 'player_name', 'binding_source',
        'direct_identity_status', 'tracker_participant'
    })
local teams_export_csv = open_csv(output_dir,
    '18_match_teams_wide.csv', team_export_headers)
local raw_export_csv = open_diagnostic_csv(output_dir,
    '19_match_values_raw_long.csv', {
        'snapshot_id', 'tracker_capture_id', 'trigger', 'team_index',
        'array_index', 'selector_signed', 'player_id', 'player_name',
        'binding_source', 'tracker_participant', 'getter_key',
        'canonical_direct_label', 'value_signed'
    })
local export_summary_csv = open_csv(output_dir,
    '20_match_export_summary.csv', {
        'snapshot_id', 'tracker_capture_id', 'trigger',
        'matchanalysis_objects', 'tracker_participants',
        'direct_id_bindings', 'set_difference_bindings',
        'unresolved_objects', 'participant_rows', 'nonparticipant_objects',
        'team_rows', 'raw_value_rows', 'named_direct_fields',
        'named_special_float_fields', 'named_tracker_fields', 'derived_fields', 'exporter_version', 'output_profile', 'pipeline_capture_id', 'career_fingerprint_candidate', 'status'
    })
local tracker_headers_csv = open_diagnostic_csv(output_dir,
    '21_tracker_outer_headers.csv', {
        'tracker_capture_id', 'trigger', 'outer_node_pointer_hex',
        'player_id', 'player_name', 'header_bytes', 'header_hex'
    })
SPECIAL.handlers_csv = open_diagnostic_csv(output_dir,
    '22_special_field_handlers.csv', {
        'semantic', 'source_label', 'selector', 'field_id',
        'internal_kind_id', 'transform_id', 'descriptor_rva_hex',
        'handler_rva_hex', 'handler_end_rva_hex', 'handler_bytes',
        'binary_file', 'status'
    })
SPECIAL.service_enums_csv = open_diagnostic_csv(output_dir,
    '23_special_service_enums.csv', {
        'service_family', 'global_name', 'enum_value_hex',
        'resolution_attempted', 'object_pointer_hex', 'status'
    })
SPECIAL.service_snapshots_csv = open_diagnostic_csv(output_dir,
    '24_special_service_snapshots.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'snapshot_id', 'service_family', 'global_name', 'enum_value_hex',
        'object_pointer_hex', 'vtable_pointer_hex', 'object_bytes',
        'binary_file', 'status'
    })
SPECIAL.service_vtable_csv = open_diagnostic_csv(output_dir,
    '25_special_service_vtable.csv', {
        'service_family', 'global_name', 'enum_value_hex', 'slot_index',
        'function_pointer_hex', 'function_rva_hex', 'method_bytes',
        'binary_file', 'status'
    })
SPECIAL.player_windows_csv = open_diagnostic_csv(output_dir,
    '26_special_player_windows.csv', {
        'snapshot_id', 'trigger', 'team_index', 'array_index',
        'selector_signed', 'player_id', 'player_pointer_hex',
        'parallel_state_pointer_hex', 'player_forward_stride_proof',
        'player_backward_stride_proof', 'parallel_forward_stride_proof',
        'parallel_backward_stride_proof', 'player_object_bytes',
        'parallel_state_bytes', 'player_object_file', 'parallel_state_file',
        'status'
    })
SPECIAL.float_values_csv = open_diagnostic_csv(output_dir,
    '27_special_float_values.csv', {
        'snapshot_id', 'trigger', 'scope', 'team_index', 'array_index',
        'selector_signed', 'player_id', 'semantic', 'source_label',
        'base_pointer_hex', 'offset_hex', 'raw_u32_hex', 'value_f32', 'status'
    })
SPECIAL.service_children_csv = open_diagnostic_csv(output_dir,
    '28_special_service_children.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'service_family', 'child_label', 'field_offset_hex',
        'child_pointer_hex', 'child_vtable_pointer_hex', 'object_bytes',
        'binary_file', 'status'
    })
SPECIAL.service_child_vtable_csv = open_diagnostic_csv(output_dir,
    '29_special_service_child_vtable.csv', {
        'service_family', 'child_label', 'field_offset_hex', 'slot_index',
        'function_pointer_hex', 'function_rva_hex', 'method_bytes',
        'binary_file', 'status'
    })
SPECIAL.game_ratings_vector_csv = open_diagnostic_csv(output_dir,
    '30_game_ratings_vector.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'begin_pointer_hex', 'end_pointer_hex', 'capacity_pointer_hex',
        'record_stride_hex', 'record_count', 'capacity_records',
        'vector_bytes', 'binary_file', 'status'
    })
SPECIAL.rating_provider_state_csv = open_diagnostic_csv(output_dir,
    '31_rating_provider_state.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'child_pointer_hex', 'state_pointer_hex', 'team0_records_pointer_hex',
        'team1_records_pointer_hex', 'team0_metric_matrix_pointer_hex',
        'team1_metric_matrix_pointer_hex', 'state_bytes', 'binary_file', 'status'
    })
SPECIAL.rating_team_records_csv = open_diagnostic_csv(output_dir,
    '32_motm_rating_team_records.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'team_index', 'array_pointer_hex', 'record_index', 'record_pointer_hex',
        'gameplay_player_identifier_u32', 'record_bytes', 'array_binary_file',
        'status'
    })
SPECIAL.rating_static_targets_csv = open_diagnostic_csv(output_dir,
    '33_rating_static_targets.csv', {
        'target_label', 'target_kind', 'rva_hex', 'pointer_hex', 'bytes_requested',
        'raw_u32_hex', 'value_f32', 'raw_bytes', 'binary_file', 'status'
    })
SPECIAL.rating_metric_matrix_csv = open_diagnostic_csv(output_dir,
    '34_rating_metric_matrix_prefix.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'team_index', 'matrix_pointer_hex', 'metric_index_stride_hex',
        'prefix_bytes_requested', 'raw_bytes', 'binary_file', 'status'
    })
SPECIAL.rating_metric_matrix_full_csv = open_diagnostic_csv(output_dir,
    '35_rating_metric_matrix_final.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'team_index', 'matrix_pointer_hex', 'player_slots',
        'metrics_per_player', 'bytes_requested', 'binary_file', 'status'
    })
SPECIAL.motm_selection_csv = open_diagnostic_csv(output_dir,
    '36_motm_selection.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'state_pointer_hex', 'selected_team_raw_u32', 'team0_player_id_u32',
        'team1_player_id_u32', 'selected_player_id_u32',
        'accepted_for_current_match', 'status'
    })
SPECIAL.rating_resolver_runtime_csv = open_diagnostic_csv(output_dir,
    '37_rating_resolver_runtime.csv', {
        'capture_index', 'real_timestamp', 'trigger', 'phase', 'event_id',
        'global_slot_pointer_hex', 'global_object_pointer_hex',
        'context_id_u32', 'object_bytes', 'binary_file', 'status'
    })
SPECIAL.game_ratings_csv = open_diagnostic_csv(output_dir,
    '38_game_ratings.csv', {
        'real_timestamp', 'trigger', 'manager_root_slot_pointer_hex',
        'manager_root_pointer_hex', 'active_index_u32', 'bucket_index',
        'manager_pointer_hex', 'ready_flag_u8',
        'gameplay_array_begin_hex', 'gameplay_array_end_hex',
        'record_count', 'record_index', 'team_index', 'player_id',
        'raw_rating_f32', 'quantized_rating_f32', 'status'
    })
local errors_csv = open_csv(output_dir, '98_errors.csv', {
    'real_timestamp', 'stage', 'source', 'error'
})

-- These schemas remain in the runtime package for continuity, but the costly
-- candidate matrix is intentionally performed offline.
for _, deferred_file in ipairs({
    correlation_csv, bindings_csv
}) do
    deferred_file:flush()
    deferred_file:close()
end

local memory_read_calls = 0
local memory_bytes_requested = 0
local error_count = 0
local build_checks_matched = 0
local build_checks_total = 0
local lifecycle_samples = 0
local stats_snapshots = 0
local team_blocks_exported = 0
local player_objects_exported = 0
local team_values_exported = 0
local player_values_exported = 0
local tracker_captures_exported = 0
local tracker_players_exported = 0
local tracker_values_exported = 0
local correlation_rows_exported = 0
local unique_bindings_exported = 0
local direct_identity_reads_attempted = 0
local direct_identity_reads_successful = 0
local direct_identity_structurally_skipped = 0
local direct_identity_nonzero_exported = 0
local tracker_outer_headers_exported = 0
local final_participant_rows_exported = 0
local final_identity_rows_exported = 0
local final_team_rows_exported = 0
local final_raw_rows_exported = 0
local final_export_status = 'not_attempted'

for _, pair in ipairs(SURFACE_PAIRS) do
    write_csv_row(surface_pairs_csv, {
        pair.semantic, pair.matchanalysis_key, pair.tracker_key,
        pair.evidence_status
    })
end

local function log_progress(kind, details)
    progress:write(now_text(), '\t', kind, '\t', scalar(details), '\r\n')
    progress:flush()
end

local function log_error(stage, source, err)
    error_count = error_count + 1
    write_csv_row(errors_csv, { now_text(), stage, source, scalar(err) })
    log_progress('error', stage .. ';' .. source .. ';' .. scalar(err))
end

local function safe_read(stage, source, pointer, length)
    if not is_plausible_pointer(pointer) or not length or length <= 0 then
        return nil, 'invalid_read_request'
    end
    if memory_read_calls + 1 > MAX_MEMORY_READ_CALLS then
        log_error(stage, source, 'memory_read_call_cap_exceeded')
        return nil, 'memory_read_call_cap_exceeded'
    end
    if memory_bytes_requested + length > MAX_MEMORY_BYTES then
        log_error(stage, source, 'memory_byte_cap_exceeded')
        return nil, 'memory_byte_cap_exceeded'
    end
    log_progress('memory_read_begin',
        'stage=' .. stage .. ';source=' .. source ..
        ';ptr=' .. ptr_hex(pointer) .. ';bytes=' .. tostring(length))
    memory_read_calls = memory_read_calls + 1
    memory_bytes_requested = memory_bytes_requested + length
    local ok, result = pcall(function()
        return MEMORY:ReadBytes(pointer, length)
    end)
    if not ok then
        log_error(stage, source, result)
        return nil, 'read_error'
    end
    if type(result) ~= 'table' then
        log_error(stage, source, 'ReadBytes returned ' .. type(result))
        return nil, 'unexpected_result_type'
    end
    return result, 'ok'
end

local game_base = tonumber(LE and LE.game_base) or
    tonumber(LE_GAME_MODULE_BASE) or 0
local game_size = tonumber(LE and LE.game_size) or
    tonumber(LE_GAME_MODULE_SIZE) or 0
assert(game_base > 0 and game_size > 0, 'Game module base/size unavailable.')

local function module_rva(pointer)
    pointer = tonumber(pointer) or 0
    if pointer < game_base or pointer >= game_base + game_size then return nil end
    return pointer - game_base
end

local function module_rva_hex(pointer)
    local value = module_rva(pointer)
    if value == nil then return '' end
    return string.format('0x%X', value)
end

local function record_check(target, rva_value, offset0, role, expected, bytes)
    build_checks_total = build_checks_total + 1
    local matched = bytes_match(bytes, offset0, expected)
    if matched then build_checks_matched = build_checks_matched + 1 end
    write_csv_row(validation_csv, {
        target, string.format('0x%X', rva_value), offset_hex(offset0), role,
        bytes_to_hex(expected, 0, #expected),
        bytes_to_hex(bytes, offset0, #expected),
        matched and 'matched' or 'mismatch'
    })
    return matched
end

function SPECIAL.capture_handler_windows()
    if not SPECIAL.special_float_features_enabled then return end
    for _, spec in ipairs(SPECIAL.FIELDS) do
        local length = spec.handler_end_rva - spec.handler_rva
        local pointer = game_base + spec.handler_rva
        local bytes, status = safe_read('special_handler', spec.semantic,
            pointer, length)
        local file_name = ''
        if bytes then
            file_name = 'handler_' .. SPECIAL.filename_token(spec.semantic) ..
                '_0x' .. string.format('%X', spec.handler_rva) .. '.bin'
            local ok_file, file_status = SPECIAL.write_binary_bytes(
                SPECIAL.dir .. '\\' .. file_name, bytes)
            if not ok_file then
                status = 'binary_write_' .. file_status
                log_error('special_handler_file', file_name, file_status)
            else
                status = 'captured'
                SPECIAL.handler_windows_exported =
                    SPECIAL.handler_windows_exported + 1
            end
        end
        write_csv_row(SPECIAL.handlers_csv, {
            spec.semantic, spec.source_label, spec.selector, spec.field_id,
            spec.internal_kind_id, spec.transform_id,
            string.format('0x%X', spec.descriptor_rva),
            string.format('0x%X', spec.handler_rva),
            string.format('0x%X', spec.handler_end_rva),
            bytes and bytes_to_hex(bytes, 0, length) or '', file_name, status
        })
    end
end

-- v0.41.7: do not use Live Editor's native AOB scan wrappers during startup.
-- A v26.3.6 crash dump showed a native access violation inside FCLiveEditor.DLL
-- while v0.41.5 was resolving relocated code. Lua pcall cannot make that native
-- boundary safe. Instead, relocation is limited to small, already-proven module
-- neighborhoods and searched in Lua over ReadBytes results.
function SPECIAL.pattern_matches(bytes, offset0, pattern)
    if type(bytes) ~= 'table' or type(pattern) ~= 'table' then return false end
    for i = 1, #pattern do
        local want = pattern[i]
        if want ~= -1 and byte_at(bytes, offset0 + i - 1) ~= want then
            return false
        end
    end
    return true
end

function SPECIAL.pattern_hits_near(label, center_pointer, radius, pattern, max_hits)
    center_pointer = tonumber(center_pointer) or 0
    radius = math.floor(tonumber(radius) or 0)
    max_hits = math.max(1, math.floor(tonumber(max_hits) or 16))
    if center_pointer < game_base or center_pointer >= game_base + game_size or
       radius <= 0 or type(pattern) ~= 'table' or #pattern == 0 then
        return {}
    end
    local module_end = game_base + game_size
    local scan_start = math.max(game_base, center_pointer - radius)
    local scan_end = math.min(module_end, center_pointer + radius)
    local chunk_size = 0x10000
    local overlap = math.max(0, #pattern - 1)
    local hits = {}
    local cursor = scan_start
    while cursor < scan_end and #hits < max_hits do
        local read_len = math.min(chunk_size + overlap, scan_end - cursor)
        local bytes = select(1, safe_read('bounded_relocation', label, cursor, read_len))
        if not bytes then break end
        local max_offset = math.max(0, read_len - #pattern)
        for offset0 = 0, max_offset do
            if SPECIAL.pattern_matches(bytes, offset0, pattern) then
                hits[#hits + 1] = cursor + offset0
                if #hits >= max_hits then break end
            end
        end
        cursor = cursor + chunk_size
    end
    return hits
end

-- Optional title-build relocation uses the same bounded ReadBytes-only strategy as
-- the core resolver.  Each candidate must satisfy multiple code-shape checks;
-- this never executes game code and never calls the Live Editor native AOB wrappers.
function SPECIAL.pattern_text(pattern)
    local parts = {}
    for index = 1, #pattern do
        local value = pattern[index]
        parts[#parts + 1] = value == -1 and '??' or
            string.format('%02X', tonumber(value) or 0)
    end
    return table.concat(parts, ' ')
end

function SPECIAL.record_pattern_check(target, rva_value, offset0, role, pattern, bytes)
    build_checks_total = build_checks_total + 1
    local matched = SPECIAL.pattern_matches(bytes, offset0, pattern)
    if matched then build_checks_matched = build_checks_matched + 1 end
    write_csv_row(validation_csv, {
        target, rva_value and string.format('0x%X', rva_value) or '',
        offset_hex(offset0), role, SPECIAL.pattern_text(pattern),
        bytes and bytes_to_hex(bytes, offset0, #pattern) or '',
        matched and 'matched' or 'mismatch'
    })
    return matched
end

function SPECIAL.resolve_shape_near(label, legacy_rva, anchor_offset, anchor_pattern,
                                    window_bytes, checks, radius)
    legacy_rva = tonumber(legacy_rva) or 0
    anchor_offset = tonumber(anchor_offset) or 0
    window_bytes = tonumber(window_bytes) or 0
    radius = tonumber(radius) or 0x20000
    local tried = {}
    local function validate(pointer, source)
        pointer = tonumber(pointer) or 0
        if tried[pointer] then return nil end
        tried[pointer] = true
        if pointer < game_base or pointer + window_bytes > game_base + game_size then
            return nil
        end
        local bytes = select(1, safe_read('optional_build_validation',
            label .. '_' .. tostring(source or 'candidate'), pointer, window_bytes))
        if not bytes then return nil end
        for _, check in ipairs(checks or {}) do
            if not SPECIAL.pattern_matches(bytes, check.offset, check.pattern) then
                return nil
            end
        end
        return bytes
    end

    local legacy_pointer = game_base + legacy_rva
    local bytes = validate(legacy_pointer, 'legacy')
    if bytes then return legacy_pointer, bytes, 'legacy_rva' end

    local getter_delta = 0
    if SPECIAL.getter_pointer and SPECIAL.getter_pointer > 0 then
        getter_delta = (module_rva(SPECIAL.getter_pointer) or VALUE_GETTER_RVA) -
            VALUE_GETTER_RVA
    end
    if getter_delta ~= 0 then
        local shifted_pointer = legacy_pointer + getter_delta
        bytes = validate(shifted_pointer, 'core_delta')
        if bytes then return shifted_pointer, bytes, 'core_delta' end
    end

    local center = legacy_pointer + getter_delta + anchor_offset
    local hits = SPECIAL.pattern_hits_near(label .. '_neighborhood', center, radius,
        anchor_pattern, 16)
    for _, hit in ipairs(hits) do
        local candidate = hit - anchor_offset
        bytes = validate(candidate, 'bounded_search')
        if bytes then return candidate, bytes, 'bounded_readbytes_search' end
    end
    return 0, nil, 'not_resolved'
end

function SPECIAL.decode_rip_target(bytes, function_pointer, instruction_offset,
                                   displacement_offset, instruction_length)
    local displacement = le_s32(bytes, instruction_offset + displacement_offset)
    if displacement == nil then return 0 end
    local target = function_pointer + instruction_offset + instruction_length + displacement
    if target < game_base or target >= game_base + game_size then return 0 end
    return target
end

function SPECIAL.getter_candidate(pointer)
    pointer = tonumber(pointer) or 0
    if pointer < game_base or pointer + VALUE_GETTER_BYTES > game_base + game_size then
        return nil, 'candidate_outside_module'
    end
    local bytes, status = safe_read('build_validation',
        'common_value_getter_candidate', pointer, VALUE_GETTER_BYTES)
    if not bytes then return nil, status end
    for _, spec in ipairs(GETTER_SIGNATURES) do
        if not bytes_match(bytes, spec.offset, spec.bytes) then
            return nil, 'signature_mismatch:' .. tostring(spec.role)
        end
    end
    return bytes, 'matched'
end

function SPECIAL.resolve_getter()
    local legacy_pointer = game_base + VALUE_GETTER_RVA
    local legacy_bytes = select(1, SPECIAL.getter_candidate(legacy_pointer))
    if legacy_bytes then
        return legacy_pointer, legacy_bytes, 'legacy_rva'
    end
    local prolog = {
        0x48,0x89,0x5C,0x24,0x20,0x57,0x41,0x56,0x41,0x57,
        0x48,0x83,0xEC,0x40,0x48,0x8B,0x99,0xE0,0x8F,0x03,0x00
    }
    local hits = SPECIAL.pattern_hits_near('getter_neighborhood',
        legacy_pointer, 0x40000, prolog, 8)
    for _, pointer in ipairs(hits) do
        local bytes = select(1, SPECIAL.getter_candidate(pointer))
        if bytes then return pointer, bytes, 'bounded_readbytes_search' end
    end
    return 0, nil, 'getter_not_resolved'
end

SPECIAL.getter_pointer, SPECIAL.getter_bytes, SPECIAL.getter_resolution =
    SPECIAL.resolve_getter()
SPECIAL.getter_matched = SPECIAL.getter_pointer > 0 and
    type(SPECIAL.getter_bytes) == 'table'
SPECIAL.core_relocation_delta = SPECIAL.getter_matched and
    (module_rva(SPECIAL.getter_pointer) - VALUE_GETTER_RVA) or 0
SPECIAL.expected_slot50_pointer = SPECIAL.getter_matched and
    (game_base + SLOT50_RVA + SPECIAL.core_relocation_delta) or 0
if SPECIAL.getter_matched then
    for _, spec in ipairs(GETTER_SIGNATURES) do
        record_check('common_value_getter', module_rva(SPECIAL.getter_pointer),
            spec.offset, spec.role, spec.bytes, SPECIAL.getter_bytes)
    end
else
    write_csv_row(validation_csv, {
        'common_value_getter', '', '', 'bounded_dynamic_resolution', '', '',
        SPECIAL.getter_resolution or 'not_resolved'
    })
end

SPECIAL.slot37_expected = {
    0x4C, 0x8B, 0xDC, 0x45, 0x89, 0x43, 0x18, 0x55,
    0x56, 0x41, 0x54, 0x41, 0x55, 0x41, 0x57, 0x49
}
SPECIAL.slot37_pointer = SPECIAL.getter_pointer > 0 and
    SPECIAL.getter_pointer + 0x210 or 0
SPECIAL.slot37_bytes = SPECIAL.slot37_pointer > 0 and select(1, safe_read(
    'build_validation', 'slot37_boundary_candidate', SPECIAL.slot37_pointer, 0x10)) or nil
if not SPECIAL.slot37_bytes or
   not bytes_match(SPECIAL.slot37_bytes, 0, SPECIAL.slot37_expected) then
    local center = SPECIAL.getter_pointer > 0 and SPECIAL.getter_pointer + 0x210 or
        game_base + SLOT37_RVA
    local hits = SPECIAL.pattern_hits_near('slot37_neighborhood', center, 0x800,
        SPECIAL.slot37_expected, 4)
    if #hits > 0 then
        SPECIAL.slot37_pointer = hits[1]
        SPECIAL.slot37_bytes = select(1, safe_read('build_validation',
            'slot37_boundary_candidate', SPECIAL.slot37_pointer, 0x10))
    end
end
SPECIAL.slot37_matched = type(SPECIAL.slot37_bytes) == 'table' and
    bytes_match(SPECIAL.slot37_bytes, 0, SPECIAL.slot37_expected)
if SPECIAL.slot37_pointer > 0 and SPECIAL.slot37_bytes then
    record_check('slot37_boundary', module_rva(SPECIAL.slot37_pointer), 0,
        'next_vtable_function_boundary', SPECIAL.slot37_expected,
        SPECIAL.slot37_bytes)
end
write_csv_row(validation_csv, {
    'slot50_expected', module_rva_hex(SPECIAL.expected_slot50_pointer), '0x0000',
    'legacy_slot50_plus_proven_getter_delta',
    string.format('0x%X + getter_delta', SLOT50_RVA),
    module_rva_hex(SPECIAL.expected_slot50_pointer),
    SPECIAL.expected_slot50_pointer > 0 and 'derived' or 'not_resolved'
})

-- Callsite checks remain diagnostic only. Their legacy bytes can move between
-- title builds and therefore do not gate event registration.
SPECIAL.worker_pointer = game_base + WORKER_CALLSITE_RVA
SPECIAL.worker_bytes = select(1, safe_read('build_validation',
    'worker_getter_callsite', SPECIAL.worker_pointer, 0x16))
SPECIAL.worker_matched = type(SPECIAL.worker_bytes) == 'table' and
    decode_rel32(SPECIAL.worker_bytes, SPECIAL.worker_pointer, 0x0E) ==
        SPECIAL.getter_pointer
build_checks_total = build_checks_total + 1
if SPECIAL.worker_matched then build_checks_matched = build_checks_matched + 1 end
write_csv_row(validation_csv, {
    'worker_getter_callsite', module_rva_hex(SPECIAL.worker_pointer), '0x0000',
    'legacy_diagnostic_call_target_to_common_getter', '',
    SPECIAL.worker_bytes and bytes_to_hex(SPECIAL.worker_bytes, 0, 0x16) or '',
    SPECIAL.worker_matched and 'matched' or 'diagnostic_mismatch'
})

SPECIAL.handler_pointer = game_base + HANDLER_CALLSITE_RVA
SPECIAL.handler_bytes = select(1, safe_read('build_validation',
    'handler_getter_callsites', SPECIAL.handler_pointer, 0x2A))
SPECIAL.handler_matched = type(SPECIAL.handler_bytes) == 'table' and
    decode_rel32(SPECIAL.handler_bytes, SPECIAL.handler_pointer, 0x0F) ==
        SPECIAL.getter_pointer and
    decode_rel32(SPECIAL.handler_bytes, SPECIAL.handler_pointer, 0x25) ==
        SPECIAL.getter_pointer
build_checks_total = build_checks_total + 1
if SPECIAL.handler_matched then build_checks_matched = build_checks_matched + 1 end
write_csv_row(validation_csv, {
    'handler_getter_callsites', module_rva_hex(SPECIAL.handler_pointer), '0x0000',
    'legacy_diagnostic_key_0x36_0x37_call_targets', '',
    SPECIAL.handler_bytes and bytes_to_hex(SPECIAL.handler_bytes, 0, 0x2A) or '',
    SPECIAL.handler_matched and 'matched' or 'diagnostic_mismatch'
})

function SPECIAL.resolve_static_slot()
    local legacy_accessor = game_base + ACCESSOR_RVA
    local legacy_slot = game_base + EXPECTED_STATIC_SLOT_RVA
    local expected_slot_min = math.max(game_base, legacy_slot - 0x400000)
    local expected_slot_max = math.min(game_base + game_size - 8, legacy_slot + 0x400000)
    local function decode_accessor(pointer)
        local bytes = select(1, safe_read('build_validation',
            'singleton_accessor_candidate', pointer, 8))
        if not bytes or byte_at(bytes, 0) ~= 0x48 or byte_at(bytes, 1) ~= 0x8B or
           byte_at(bytes, 2) ~= 0x05 or byte_at(bytes, 7) ~= 0xC3 then
            return 0
        end
        local slot = pointer + 7 + (le_s32(bytes, 3) or 0)
        if slot < expected_slot_min or slot > expected_slot_max then return 0 end
        return slot
    end
    local legacy_decoded = decode_accessor(legacy_accessor)
    if legacy_decoded > 0 then
        SPECIAL.accessor_pointer = legacy_accessor
        SPECIAL.static_slot_pointer = legacy_decoded
        return true, legacy_decoded == legacy_slot and
            'legacy_accessor_exact_slot' or 'legacy_accessor_relocated_slot'
    end
    local accessor_pattern = {0x48,0x8B,0x05,-1,-1,-1,-1,0xC3}
    local hits = SPECIAL.pattern_hits_near('accessor_neighborhood',
        legacy_accessor, 0x40000, accessor_pattern, 32)
    for _, pointer in ipairs(hits) do
        local slot = decode_accessor(pointer)
        if slot > 0 then
            SPECIAL.accessor_pointer = pointer
            SPECIAL.static_slot_pointer = slot
            return true, 'bounded_readbytes_accessor'
        end
    end
    return false, 'singleton_static_slot_not_resolved'
end

SPECIAL.static_slot_matched, SPECIAL.static_slot_resolution =
    SPECIAL.resolve_static_slot()
build_checks_total = build_checks_total + 1
if SPECIAL.static_slot_matched then build_checks_matched = build_checks_matched + 1 end
write_csv_row(validation_csv, {
    'singleton_accessor', module_rva_hex(SPECIAL.accessor_pointer), '0x0000',
    'bounded_accessor_to_nearby_static_slot',
    '48 8B 05 ?? ?? ?? ?? C3 -> bounded static slot',
    module_rva_hex(SPECIAL.static_slot_pointer),
    SPECIAL.static_slot_matched and 'matched' or SPECIAL.static_slot_resolution
})

SPECIAL.core_validation_ok = SPECIAL.getter_matched and
    SPECIAL.slot37_matched and SPECIAL.static_slot_matched
SPECIAL.core_validation_status = SPECIAL.core_validation_ok and
    ('validated:' .. tostring(SPECIAL.getter_resolution) .. ':' ..
        tostring(SPECIAL.static_slot_resolution)) or
    ('failed:getter=' .. tostring(SPECIAL.getter_matched) ..
        ';slot37=' .. tostring(SPECIAL.slot37_matched) ..
        ';static_slot=' .. tostring(SPECIAL.static_slot_matched) ..
        ';getter_resolution=' .. tostring(SPECIAL.getter_resolution) ..
        ';slot_resolution=' .. tostring(SPECIAL.static_slot_resolution))

-- The title update that moved the core getter also moved optional handler/code
-- RVAs.  Resolve the already-proven semantic shapes in small local neighborhoods
-- instead of binding optional features to one executable build.
do
    local xg_checks = {
        { offset = 0x05, pattern = { 0xF3,0x41,0x0F,0x10,0x80,0x60,0x2E,0x02,0x00 } },
        { offset = 0x3E, pattern = { 0xF3,0x0F,0x10,0x80,0xF0,0x05,0x00,0x00 } }
    }
    local xa_checks = {
        { offset = 0x05, pattern = { 0xF3,0x41,0x0F,0x10,0x80,0x64,0x2E,0x02,0x00 } },
        { offset = 0x3F, pattern = { 0xF3,0x0F,0x10,0x80,0x00,0x06,0x00,0x00 } }
    }
    local xg_pointer, xg_bytes, xg_resolution = SPECIAL.resolve_shape_near(
        'npk_expected_goals_handler', 0x6AAD1D5, 0x05, xg_checks[1].pattern,
        0x50, xg_checks, 0x20000)
    local xa_pointer, xa_bytes, xa_resolution = SPECIAL.resolve_shape_near(
        'expected_assists_handler', 0x6AAD134, 0x05, xa_checks[1].pattern,
        0x51, xa_checks, 0x20000)
    local xg_rva = module_rva(xg_pointer)
    local xa_rva = module_rva(xa_pointer)
    if xg_rva then
        SPECIAL.FIELDS[1].handler_rva = xg_rva
        SPECIAL.FIELDS[1].handler_end_rva = xg_rva + 0x50
    end
    if xa_rva then
        SPECIAL.FIELDS[2].handler_rva = xa_rva
        SPECIAL.FIELDS[2].handler_end_rva = xa_rva + 0x51
    end
    local xg_team = SPECIAL.record_pattern_check('npk_expected_goals_handler',
        xg_rva, 0x05, 'team_float_load_plus_0x22E60', xg_checks[1].pattern, xg_bytes)
    local xg_player = SPECIAL.record_pattern_check('npk_expected_goals_handler',
        xg_rva, 0x3E, 'player_float_load_plus_0x5F0', xg_checks[2].pattern, xg_bytes)
    local xa_team = SPECIAL.record_pattern_check('expected_assists_handler',
        xa_rva, 0x05, 'team_float_load_plus_0x22E64', xa_checks[1].pattern, xa_bytes)
    local xa_player = SPECIAL.record_pattern_check('expected_assists_handler',
        xa_rva, 0x3F, 'player_float_load_plus_0x600', xa_checks[2].pattern, xa_bytes)
    SPECIAL.special_float_offsets_matched = xg_team and xg_player and xa_team and xa_player
    SPECIAL.special_float_resolution = 'xg=' .. tostring(xg_resolution) .. ':' ..
        tostring(xg_rva and string.format('0x%X', xg_rva) or '') ..
        ';xa=' .. tostring(xa_resolution) .. ':' ..
        tostring(xa_rva and string.format('0x%X', xa_rva) or '')
end

-- Direct FC26 match-rating path.  RIP displacements are intentionally wildcards:
-- recompiles change those bytes even when the proven structure offsets are stable.
do
    local getter_checks = {
        { offset = 0x6C, pattern = { 0xF3,0x0F,0x10,0x80,0xCC,0x03,0x00,0x00 } },
        { offset = 0x74, pattern = { 0xF3,0x0F,0x59,0x05,-1,-1,-1,-1 } },
        { offset = 0x7C, pattern = { 0xF3,0x0F,0x58,0x05,-1,-1,-1,-1 } },
        { offset = 0x8C, pattern = { 0xF3,0x0F,0x5E,0x3D,-1,-1,-1,-1 } }
    }
    local rating_getter_pointer, rating_getter_bytes, getter_resolution =
        SPECIAL.resolve_shape_near('motm_rating_getter_slot2',
            SPECIAL.RATING_GETTER_RVA, 0x6C, getter_checks[1].pattern, 0x94,
            getter_checks, 0x20000)
    local rating_getter_rva = module_rva(rating_getter_pointer)
    if rating_getter_rva then SPECIAL.RATING_GETTER_RVA = rating_getter_rva end
    local raw_field = SPECIAL.record_pattern_check('motm_rating_getter_slot2',
        rating_getter_rva, 0x6C, 'raw_gameplay_rating_float_load_plus_0x3CC',
        getter_checks[1].pattern, rating_getter_bytes)
    local scale_mul = SPECIAL.record_pattern_check('motm_rating_getter_slot2',
        rating_getter_rva, 0x74, 'rating_quantization_scale_mul_rip',
        getter_checks[2].pattern, rating_getter_bytes)
    local bias_add = SPECIAL.record_pattern_check('motm_rating_getter_slot2',
        rating_getter_rva, 0x7C, 'rating_quantization_bias_add_rip',
        getter_checks[3].pattern, rating_getter_bytes)
    local scale_div = SPECIAL.record_pattern_check('motm_rating_getter_slot2',
        rating_getter_rva, 0x8C, 'rating_quantization_scale_div_rip',
        getter_checks[4].pattern, rating_getter_bytes)
    SPECIAL.rating_getter_shape_matched = raw_field and scale_mul and bias_add and scale_div
    if SPECIAL.rating_getter_shape_matched then
        local scale_pointer = SPECIAL.decode_rip_target(rating_getter_bytes,
            rating_getter_pointer, 0x74, 4, 8)
        local bias_pointer = SPECIAL.decode_rip_target(rating_getter_bytes,
            rating_getter_pointer, 0x7C, 4, 8)
        local scale_rva = module_rva(scale_pointer)
        local bias_rva = module_rva(bias_pointer)
        if scale_rva then SPECIAL.RATING_SCALE_CONSTANT_RVA = scale_rva end
        if bias_rva then SPECIAL.RATING_BIAS_CONSTANT_RVA = bias_rva end
    end
    SPECIAL.rating_getter_resolution = getter_resolution .. ':' ..
        tostring(rating_getter_rva and string.format('0x%X', rating_getter_rva) or '')
end

-- MOTM result-state shapes are relocated independently from the direct rating
-- array.  Failure here disables only MOTM selection diagnostics, not ratings.
do
    local selector_checks = {
        { offset = 0xE5, pattern = { 0x89,0x6A,0x04 } },
        { offset = 0xF0, pattern = { 0x44,0x89,0x7C,0x88,0x08 } }
    }
    local metric_checks = {
        { offset = 0x50, pattern = { 0x41,0x69,0xC2,0x0E,0x01,0x00,0x00 } },
        { offset = 0x5C, pattern = { 0x4A,0x8B,0x44,0xDB,0x10,0x8B,0x04,0x88 } }
    }
    local selector_pointer, selector_bytes, selector_resolution =
        SPECIAL.resolve_shape_near('motm_rating_selector_slot1',
            SPECIAL.RATING_SELECTOR_RVA, 0xF0, selector_checks[2].pattern,
            0xF5, selector_checks, 0x20000)
    local metric_pointer, metric_bytes, metric_resolution =
        SPECIAL.resolve_shape_near('motm_rating_metric_getter_slot5',
            0x36A1AB0, 0x50, metric_checks[1].pattern, 0x64, metric_checks, 0x20000)
    local selector_rva = module_rva(selector_pointer)
    local metric_rva = module_rva(metric_pointer)
    if selector_rva then SPECIAL.RATING_SELECTOR_RVA = selector_rva end
    local selected_team = SPECIAL.record_pattern_check('motm_rating_selector_slot1',
        selector_rva, 0xE5, 'selected_team_write_state_plus_0x04',
        selector_checks[1].pattern, selector_bytes)
    local selected_player = SPECIAL.record_pattern_check('motm_rating_selector_slot1',
        selector_rva, 0xF0, 'selected_player_write_state_plus_0x08_team_indexed',
        selector_checks[2].pattern, selector_bytes)
    local metric_stride = SPECIAL.record_pattern_check('motm_rating_metric_getter_slot5',
        metric_rva, 0x50, 'metric_player_index_stride_0x10E',
        metric_checks[1].pattern, metric_bytes)
    local metric_matrix = SPECIAL.record_pattern_check('motm_rating_metric_getter_slot5',
        metric_rva, 0x5C, 'metric_matrix_team_pointer_and_u32_read',
        metric_checks[2].pattern, metric_bytes)
    SPECIAL.rating_state_shape_matched = selected_team and selected_player and
        metric_stride and metric_matrix
    SPECIAL.rating_state_resolution = 'selector=' .. tostring(selector_resolution) ..
        ':' .. tostring(selector_rva and string.format('0x%X', selector_rva) or '') ..
        ';metric=' .. tostring(metric_resolution) .. ':' ..
        tostring(metric_rva and string.format('0x%X', metric_rva) or '')
end

-- Resolve the manager root through the code-proven RIP load and keep the active
-- index / bucket-stride checks exact.  The decoded static slot may move by a
-- much larger amount than the function itself after a title update.
do
    local manager_checks = {
        { offset = 0x04, pattern = { 0x4C,0x8B,0x0D,-1,-1,-1,-1 } },
        { offset = 0x0B, pattern = { 0x41,0x8B,0x89,0x60,0x2E,0x2B,0x00 } },
        { offset = 0x2E, pattern = { 0x4C,0x69,0xC0,0x70,0x51,0x04,0x00 } }
    }
    local manager_pointer, manager_bytes, manager_resolution =
        SPECIAL.resolve_shape_near('rating_context_resolver_inner_manager_selector',
            SPECIAL.RATING_CONTEXT_RESOLVER_INNER_RVA, 0x0B,
            manager_checks[2].pattern, 0x35, manager_checks, 0x20000)
    local manager_rva = module_rva(manager_pointer)
    if manager_rva then SPECIAL.RATING_CONTEXT_RESOLVER_INNER_RVA = manager_rva end
    local manager_root = SPECIAL.record_pattern_check(
        'rating_context_resolver_inner_manager_selector', manager_rva, 0x04,
        'rating_manager_root_slot_rip_load', manager_checks[1].pattern, manager_bytes)
    local manager_index = SPECIAL.record_pattern_check(
        'rating_context_resolver_inner_manager_selector', manager_rva, 0x0B,
        'rating_manager_active_index_load_plus_0x2B2E60',
        manager_checks[2].pattern, manager_bytes)
    local manager_stride = SPECIAL.record_pattern_check(
        'rating_context_resolver_inner_manager_selector', manager_rva, 0x2E,
        'rating_manager_bucket_stride_0x45170', manager_checks[3].pattern, manager_bytes)
    local manager_root_pointer = 0
    if manager_root and manager_bytes then
        manager_root_pointer = SPECIAL.decode_rip_target(manager_bytes, manager_pointer,
            0x04, 3, 7)
        local root_rva = module_rva(manager_root_pointer)
        if root_rva then SPECIAL.RATING_MANAGER_ROOT_SLOT_RVA = root_rva end
    end
    SPECIAL.rating_manager_selector_matched = manager_root and manager_index and
        manager_stride and manager_root_pointer > 0
    SPECIAL.rating_manager_resolution = manager_resolution .. ':' ..
        tostring(manager_rva and string.format('0x%X', manager_rva) or '') ..
        ';root=' .. tostring(module_rva(manager_root_pointer) and
            string.format('0x%X', module_rva(manager_root_pointer)) or '')
end

-- Validate the begin/end pointers of the direct gameplay-rating array.
do
    local array_checks = {
        { offset = 0x00, pattern = { 0x48,0x8B,0x81,0x90,0x4F,0x01,0x00 } },
        { offset = 0x07, pattern = { 0x4C,0x8B,0x89,0x98,0x4F,0x01,0x00 } }
    }
    local array_pointer, array_bytes, array_resolution = SPECIAL.resolve_shape_near(
        'rating_gameplay_array_helper', 0x2EB44C0, 0x00,
        array_checks[1].pattern, 0x0E, array_checks, 0x20000)
    local array_rva = module_rva(array_pointer)
    local gameplay_begin = SPECIAL.record_pattern_check('rating_gameplay_array_helper',
        array_rva, 0x00, 'rating_gameplay_array_begin_plus_0x14F90',
        array_checks[1].pattern, array_bytes)
    local gameplay_end = SPECIAL.record_pattern_check('rating_gameplay_array_helper',
        array_rva, 0x07, 'rating_gameplay_array_end_plus_0x14F98',
        array_checks[2].pattern, array_bytes)
    SPECIAL.rating_gameplay_array_shape_matched = gameplay_begin and gameplay_end
    SPECIAL.rating_gameplay_array_resolution = array_resolution .. ':' ..
        tostring(array_rva and string.format('0x%X', array_rva) or '')
end

-- The old global-context helper is diagnostic only.  Do not gate direct match
-- ratings on it and do not dereference its legacy static slot after a title update.
SPECIAL.rating_resolver_shape_matched = false
SPECIAL.special_float_features_enabled = SPECIAL.special_float_offsets_matched == true
SPECIAL.motm_features_enabled = SPECIAL.rating_state_shape_matched == true
SPECIAL.rating_features_enabled = SPECIAL.rating_getter_shape_matched == true and
    SPECIAL.rating_manager_selector_matched == true and
    SPECIAL.rating_gameplay_array_shape_matched == true
SPECIAL.rating_resolution = 'getter=' .. tostring(SPECIAL.rating_getter_resolution or '') ..
    ';manager=' .. tostring(SPECIAL.rating_manager_resolution or '') ..
    ';array=' .. tostring(SPECIAL.rating_gameplay_array_resolution or '') ..
    ';motm=' .. tostring(SPECIAL.rating_state_resolution or '')

assert(SPECIAL.core_validation_ok,
    'Core build validation failed. No event handlers were registered. ' ..
    tostring(SPECIAL.core_validation_status))

if EXPORT_DIAGNOSTICS then SPECIAL.capture_handler_windows() end
if EXPORT_DIAGNOSTICS then
local getter_binary_name = 'common_value_getter_0x6AB23E0.bin'
local getter_binary_ok, getter_binary_status = SPECIAL.write_binary_bytes(
    SPECIAL.dir .. '\\' .. getter_binary_name, SPECIAL.getter_bytes)
if not getter_binary_ok then
    log_error('special_getter_file', getter_binary_name, getter_binary_status)
end
local special_worker_bytes, special_worker_status = safe_read(
    'special_worker_region', 'validated_dispatch_worker',
    game_base + SPECIAL.WORKER_REGION_RVA,
    SPECIAL.WORKER_REGION_END_RVA - SPECIAL.WORKER_REGION_RVA)
if special_worker_bytes then
    local worker_file = 'matchanalysis_special_dispatch_worker_0x6AAC8DE.bin'
    local worker_file_ok, worker_file_status = SPECIAL.write_binary_bytes(
        SPECIAL.dir .. '\\' .. worker_file, special_worker_bytes)
    write_csv_row(SPECIAL.handlers_csv, {
        'special_dispatch_worker_region', 'validated_worker_region', '', '',
        '', '', string.format('0x%X', SPECIAL.WORKER_REGION_RVA),
        string.format('0x%X', SPECIAL.WORKER_REGION_RVA),
        string.format('0x%X', SPECIAL.WORKER_REGION_END_RVA),
        bytes_to_hex(special_worker_bytes, 0, #special_worker_bytes),
        worker_file, worker_file_ok and 'captured' or
            ('binary_write_' .. worker_file_status)
    })
    if worker_file_ok then
        SPECIAL.handler_windows_exported = SPECIAL.handler_windows_exported + 1
    else
        log_error('special_worker_file', worker_file, worker_file_status)
    end
else
    log_error('special_worker_region', 'validated_dispatch_worker',
        special_worker_status)
end
end

function SPECIAL.capture_rating_static_targets()
    if not SPECIAL.rating_features_enabled then return end
    for _, target in ipairs(SPECIAL.RATING_STATIC_TARGETS) do
        local pointer = game_base + target.rva
        local bytes = nil
        local status = 'rva_outside_module'
        local file_name = ''
        local raw_u32 = nil
        local value_f32 = nil
        if target.rva >= 0 and target.rva + target.bytes <= game_size then
            bytes, status = safe_read('rating_static_target', target.label,
                pointer, target.bytes)
            if bytes then
                raw_u32 = le_u32(bytes, 0)
                if target.kind == 'f32_constant' then
                    value_f32 = le_f32(bytes, 0)
                end
                file_name = 'rating_static_' .. SPECIAL.filename_token(target.label) ..
                    '_rva_0x' .. string.format('%X', target.rva) .. '.bin'
                local ok_file, file_status = SPECIAL.write_binary_bytes(
                    SPECIAL.dir .. '\\' .. file_name, bytes)
                if ok_file then
                    status = 'captured'
                    SPECIAL.rating_static_targets_exported =
                        SPECIAL.rating_static_targets_exported + 1
                else
                    status = 'binary_write_' .. file_status
                    log_error('rating_static_target_file', target.label, file_status)
                end
            end
        end
        write_csv_row(SPECIAL.rating_static_targets_csv, {
            target.label, target.kind, string.format('0x%X', target.rva),
            ptr_hex(pointer), target.bytes, raw_u32 and hex_u32(raw_u32) or '',
            value_f32 ~= nil and string.format('%.9g', value_f32) or '',
            bytes and bytes_to_hex(bytes, 0, #bytes) or '', file_name, status
        })
    end
end

if EXPORT_DIAGNOSTICS then SPECIAL.capture_rating_static_targets() end

local tracker_enum = rawget(_G, 'ENUM_djb2MatchEventTrackerService_CLSS')
local tracker_service_pointer = 0
if type(tracker_enum) == 'number' then
    local ok_tracker, tracker_result = pcall(GetPlugin, tracker_enum)
    if ok_tracker and is_plausible_pointer(tracker_result) then
        tracker_service_pointer = tonumber(tracker_result)
    else
        log_error('plugin_resolution', 'MatchEventTrackerService',
            ok_tracker and 'invalid_pointer' or tracker_result)
    end
else
    log_error('plugin_resolution', 'MatchEventTrackerService',
        'enum_unavailable')
end

function SPECIAL.service_family(global_name)
    if type(global_name) ~= 'string' then return nil end
    local lower_name = global_name:lower()
    if lower_name:find('gameratingsservice', 1, true) then
        return 'GameRatingsService'
    elseif lower_name:find('manofthematchservice', 1, true) then
        return 'ManOfTheMatchService'
    end
    return nil
end

function SPECIAL.discover_services()
    local candidates = {}
    local found_family = {
        GameRatingsService = false,
        ManOfTheMatchService = false
    }
    for global_name, enum_value in pairs(_G) do
        local family = SPECIAL.service_family(global_name)
        if family and type(enum_value) == 'number' and
           global_name:upper():find('_CLSS', 1, true) then
            candidates[#candidates + 1] = {
                service_family = family,
                global_name = global_name,
                enum_value = enum_value
            }
        end
    end
    table.sort(candidates, function(a, b)
        if a.service_family ~= b.service_family then
            return a.service_family < b.service_family
        end
        return a.global_name < b.global_name
    end)
    local resolved = {}
    local seen_pointer_by_family = {}
    for _, candidate in ipairs(candidates) do
        SPECIAL.service_enum_candidates = SPECIAL.service_enum_candidates + 1
        found_family[candidate.service_family] = true
        local ok_resolution, object_pointer = pcall(GetPlugin,
            candidate.enum_value)
        local status = 'resolution_failed'
        local pointer_value = 0
        if ok_resolution and is_plausible_pointer(object_pointer) then
            pointer_value = tonumber(object_pointer)
            status = 'resolved'
            local dedup_key = candidate.service_family .. ':' ..
                ptr_hex(pointer_value)
            if not seen_pointer_by_family[dedup_key] then
                seen_pointer_by_family[dedup_key] = true
                candidate.initial_object_pointer = pointer_value
                candidate.vtable_captured = false
                candidate.child_vtables_captured = {}
                resolved[#resolved + 1] = candidate
            else
                status = 'resolved_duplicate_object'
            end
        elseif ok_resolution then
            status = 'resolved_invalid_pointer'
        end
        write_csv_row(SPECIAL.service_enums_csv, {
            candidate.service_family, candidate.global_name,
            string.format('0x%X', candidate.enum_value), 'true',
            ptr_hex(pointer_value), status
        })
    end
    for family, present in pairs(found_family) do
        if not present then
            write_csv_row(SPECIAL.service_enums_csv, {
                family, '', '', 'false', '', 'no_clss_enum_candidate'
            })
        end
    end
    return resolved
end

SPECIAL.services = SPECIAL.discover_services()

local state = {
    active = true,
    version = VERSION,
    in_sample = false,
    in_capture = false,
    match_started = false,
    match_started_epoch = 0,
    last_runtime_sample_epoch = 0,
    last_periodic_capture_epoch = 0,
    last_snapshot_epoch = 0,
    seen_post_event_ids = {},
    pre_handler = nil,
    post_handler = nil,
    previous_singleton_live = false,
    tracker_capture_attempts = 0,
    final_stats_snapshot_captured = false,
    tracker_service_pointer = tracker_service_pointer,
    special_services = SPECIAL.services,
    stats_snapshot_data = {},
    latest_stats_snapshot_id = nil,
    tracker_snapshot_data = {},
    latest_tracker_capture_id = nil,
    identity_capture_completed = false,
    last_status = 'initialized',
    pipeline_capture_id = PIPELINE_CAPTURE_ID,
    pipeline_automanaged = PIPELINE_AUTOMANAGED,
    core_validation = SPECIAL.core_validation_status,
    core_getter_rva = module_rva_hex(SPECIAL.getter_pointer),
    core_static_slot_rva = module_rva_hex(SPECIAL.static_slot_pointer),
    special_float_features = SPECIAL.special_float_features_enabled,
    special_float_resolution = SPECIAL.special_float_resolution or '',
    rating_features = SPECIAL.rating_features_enabled,
    rating_resolution = SPECIAL.rating_resolution or '',
    motm_features = SPECIAL.motm_features_enabled == true,
    live_editor_version = tostring(LE_VERSION or '')
}
rawset(_G, STATE_KEY, state)

local function elapsed_seconds()
    if not state.match_started or state.match_started_epoch <= 0 then return '' end
    return math.max(0, now_epoch() - state.match_started_epoch)
end

local function read_qword(stage, source, pointer)
    local bytes, status = safe_read(stage, source, pointer, 8)
    if not bytes then return nil, status end
    return le_u64_exact(bytes, 0), 'ok'
end

function SPECIAL.capture_game_ratings_vector(capture_index, trigger, phase,
                                           event_id, object_bytes)
    local begin_pointer = le_u64_exact(object_bytes, 0xE8) or 0
    local end_pointer = le_u64_exact(object_bytes, 0xF0) or 0
    local capacity_pointer = le_u64_exact(object_bytes, 0xF8) or 0
    local stride = SPECIAL.GAME_RATINGS_VECTOR_RECORD_BYTES
    local record_count = 0
    local capacity_records = 0
    local vector_bytes = nil
    local vector_file = ''
    local status = 'empty'

    if begin_pointer == 0 and end_pointer == 0 and capacity_pointer == 0 then
        status = 'empty'
    elseif is_plausible_pointer(begin_pointer) and
           is_plausible_pointer(end_pointer) and
           is_plausible_pointer(capacity_pointer) and
           end_pointer >= begin_pointer and capacity_pointer >= end_pointer and
           ((end_pointer - begin_pointer) % stride) == 0 and
           ((capacity_pointer - begin_pointer) % stride) == 0 then
        record_count = math.floor((end_pointer - begin_pointer) / stride)
        capacity_records = math.floor((capacity_pointer - begin_pointer) / stride)
        if record_count <= SPECIAL.GAME_RATINGS_VECTOR_MAX_RECORDS and
           capacity_records <= SPECIAL.GAME_RATINGS_VECTOR_MAX_RECORDS then
            if record_count == 0 then
                status = 'validated_empty'
            else
                vector_bytes, status = safe_read('game_ratings_vector',
                    'capture_' .. tostring(capture_index), begin_pointer,
                    record_count * stride)
                if vector_bytes then
                    vector_file = 'game_ratings_vector_capture_' ..
                        string.format('%03d', capture_index) .. '.bin'
                    local ok_file, file_status = SPECIAL.write_binary_bytes(
                        SPECIAL.dir .. '\\' .. vector_file, vector_bytes)
                    if ok_file then
                        status = 'captured'
                        SPECIAL.game_ratings_vectors_exported =
                            SPECIAL.game_ratings_vectors_exported + 1
                    else
                        status = 'binary_write_' .. file_status
                        log_error('game_ratings_vector_file', vector_file,
                            file_status)
                    end
                end
            end
        else
            status = 'record_cap_exceeded'
        end
    else
        status = 'invalid_vector_shape'
    end

    write_csv_row(SPECIAL.game_ratings_vector_csv, {
        capture_index, now_text(), trigger, phase or '', event_id or '',
        ptr_hex(begin_pointer), ptr_hex(end_pointer), ptr_hex(capacity_pointer),
        string.format('0x%X', stride), record_count, capacity_records,
        vector_bytes and bytes_to_hex(vector_bytes, 0, #vector_bytes) or '',
        vector_file, status
    })
end

function SPECIAL.capture_rating_resolver_runtime(capture_index, trigger, phase,
                                                 event_id)
    if not SPECIAL.rating_resolver_shape_matched then return end
    local slot_pointer = game_base + SPECIAL.RATING_GLOBAL_POINTER_SLOT_RVA
    local global_pointer, pointer_status = read_qword(
        'rating_resolver_runtime', 'global_pointer_slot', slot_pointer)
    global_pointer = global_pointer or 0
    local object_bytes = nil
    local context_id = nil
    local object_file = ''
    local status = pointer_status
    if is_plausible_pointer(global_pointer) then
        object_bytes, status = safe_read('rating_resolver_runtime',
            'global_context_object_capture_' .. tostring(capture_index),
            global_pointer, SPECIAL.RATING_GLOBAL_OBJECT_WINDOW_BYTES)
        if object_bytes then
            context_id = le_u32(object_bytes, SPECIAL.RATING_CONTEXT_ID_OFFSET)
            object_file = 'rating_global_context_object_capture_' ..
                string.format('%03d', capture_index) .. '.bin'
            local ok_file, file_status = SPECIAL.write_binary_bytes(
                SPECIAL.dir .. '\\' .. object_file, object_bytes)
            if ok_file then
                status = 'captured'
                SPECIAL.rating_resolver_snapshots_exported =
                    SPECIAL.rating_resolver_snapshots_exported + 1
            else
                status = 'binary_write_' .. file_status
                log_error('rating_resolver_runtime_file', object_file, file_status)
            end
        end
    elseif pointer_status == 'ok' then
        status = 'global_pointer_invalid'
    end
    write_csv_row(SPECIAL.rating_resolver_runtime_csv, {
        capture_index, now_text(), trigger, phase or '', event_id or '',
        ptr_hex(slot_pointer), ptr_hex(global_pointer),
        context_id ~= nil and tostring(context_id) or '',
        object_bytes and bytes_to_hex(object_bytes, 0, #object_bytes) or '',
        object_file, status
    })
end

function SPECIAL.capture_rating_provider_state(capture_index, trigger, phase,
                                               event_id, child_pointer,
                                               child_bytes)
    if not SPECIAL.motm_features_enabled then return end
    local state_pointer = le_u64_exact(child_bytes, SPECIAL.RATING_CHILD_STATE_OFFSET) or 0
    local state_bytes = nil
    local state_file = ''
    local status = 'invalid_state_pointer'
    local team_record_pointers = { 0, 0 }
    local metric_matrix_pointers = { 0, 0 }

    if is_plausible_pointer(state_pointer) then
        state_bytes, status = safe_read('rating_provider_state',
            'capture_' .. tostring(capture_index), state_pointer,
            SPECIAL.RATING_STATE_WINDOW_BYTES)
        if state_bytes then
            state_file = 'motm_rating_provider_state_capture_' ..
                string.format('%03d', capture_index) .. '.bin'
            local ok_file, file_status = SPECIAL.write_binary_bytes(
                SPECIAL.dir .. '\\' .. state_file, state_bytes)
            if ok_file then
                status = 'captured'
                SPECIAL.rating_provider_states_exported =
                    SPECIAL.rating_provider_states_exported + 1
            else
                status = 'binary_write_' .. file_status
                log_error('rating_provider_state_file', state_file, file_status)
            end

            for team_index = 0, 1 do
                local records_offset = SPECIAL.RATING_TEAM_RECORD_ARRAY_BASE_OFFSET +
                    team_index * SPECIAL.RATING_TEAM_RECORD_POINTER_STRIDE
                local matrix_offset = SPECIAL.RATING_METRIC_MATRIX_BASE_OFFSET +
                    team_index * SPECIAL.RATING_METRIC_MATRIX_POINTER_STRIDE
                team_record_pointers[team_index + 1] =
                    le_u64_exact(state_bytes, records_offset) or 0
                metric_matrix_pointers[team_index + 1] =
                    le_u64_exact(state_bytes, matrix_offset) or 0
            end
        end
    end

    write_csv_row(SPECIAL.rating_provider_state_csv, {
        capture_index, now_text(), trigger, phase or '', event_id or '',
        ptr_hex(child_pointer), ptr_hex(state_pointer),
        ptr_hex(team_record_pointers[1]), ptr_hex(team_record_pointers[2]),
        ptr_hex(metric_matrix_pointers[1]), ptr_hex(metric_matrix_pointers[2]),
        state_bytes and bytes_to_hex(state_bytes, 0, #state_bytes) or '',
        state_file, status
    })

    local selected_team_raw = state_bytes and
        le_u32(state_bytes, SPECIAL.RATING_SELECTED_TEAM_OFFSET) or nil
    local team0_selected_player = state_bytes and
        le_u32(state_bytes, SPECIAL.RATING_SELECTED_PLAYER_BASE_OFFSET) or nil
    local team1_selected_player = state_bytes and
        le_u32(state_bytes, SPECIAL.RATING_SELECTED_PLAYER_BASE_OFFSET + 4) or nil
    local selected_player = nil
    if selected_team_raw == 0 then
        selected_player = team0_selected_player
    elseif selected_team_raw == 1 then
        selected_player = team1_selected_player
    end
    local current_match_state =
        trigger:find('late_match_candidate_event_137', 1, true) ~= nil or
        (trigger == 'entered_career_hub' and state.match_started)
    local selection_valid = current_match_state and selected_player ~= nil and
        selected_player > 0 and selected_player ~= 0xFFFFFFFF
    if selection_valid then
        SPECIAL.latest_motm_team_index = selected_team_raw
        SPECIAL.latest_motm_player_id = selected_player
    end
    write_csv_row(SPECIAL.motm_selection_csv, {
        capture_index, now_text(), trigger, phase or '', event_id or '',
        ptr_hex(state_pointer),
        selected_team_raw ~= nil and tostring(selected_team_raw) or '',
        team0_selected_player ~= nil and tostring(team0_selected_player) or '',
        team1_selected_player ~= nil and tostring(team1_selected_player) or '',
        selected_player ~= nil and tostring(selected_player) or '',
        selection_valid and 'true' or 'false',
        state_bytes and (selection_valid and 'current_match_selection' or
            'state_decoded_not_current_or_not_selected') or 'state_unavailable'
    })
    SPECIAL.motm_selection_rows_exported =
        SPECIAL.motm_selection_rows_exported + 1

    if not state_bytes then return end

    for team_index = 0, 1 do
        local array_pointer = team_record_pointers[team_index + 1] or 0
        local array_bytes = nil
        local array_status = 'invalid_array_pointer'
        local array_file = ''
        local array_length = SPECIAL.RATING_TEAM_RECORD_COUNT *
            SPECIAL.RATING_TEAM_RECORD_BYTES
        if is_plausible_pointer(array_pointer) then
            array_bytes, array_status = safe_read('rating_team_records',
                'capture_' .. tostring(capture_index) .. '_team_' .. tostring(team_index),
                array_pointer, array_length)
            if array_bytes then
                array_file = 'motm_rating_team_' .. tostring(team_index) ..
                    '_records_capture_' .. string.format('%03d', capture_index) .. '.bin'
                local ok_file, file_status = SPECIAL.write_binary_bytes(
                    SPECIAL.dir .. '\\' .. array_file, array_bytes)
                if ok_file then
                    array_status = 'captured'
                    SPECIAL.rating_team_arrays_exported =
                        SPECIAL.rating_team_arrays_exported + 1
                else
                    array_status = 'binary_write_' .. file_status
                    log_error('rating_team_records_file', array_file, file_status)
                end
            end
        end
        for record_index = 0, SPECIAL.RATING_TEAM_RECORD_COUNT - 1 do
            local record_offset = record_index * SPECIAL.RATING_TEAM_RECORD_BYTES
            local player_identifier = array_bytes and
                le_u32(array_bytes, record_offset) or nil
            SPECIAL.rating_team_record_rows_exported =
                SPECIAL.rating_team_record_rows_exported + 1
            write_csv_row(SPECIAL.rating_team_records_csv, {
                capture_index, now_text(), trigger, phase or '', event_id or '',
                team_index, ptr_hex(array_pointer), record_index,
                is_plausible_pointer(array_pointer) and
                    ptr_hex(array_pointer + record_offset) or '',
                player_identifier ~= nil and tostring(player_identifier) or '',
                array_bytes and bytes_to_hex(array_bytes, record_offset,
                    SPECIAL.RATING_TEAM_RECORD_BYTES) or '',
                array_file, array_status
            })
        end

        local matrix_pointer = metric_matrix_pointers[team_index + 1] or 0
        local matrix_bytes = nil
        local matrix_status = 'invalid_matrix_pointer'
        local matrix_file = ''
        if is_plausible_pointer(matrix_pointer) then
            matrix_bytes, matrix_status = safe_read('rating_metric_matrix_prefix',
                'capture_' .. tostring(capture_index) .. '_team_' .. tostring(team_index),
                matrix_pointer, SPECIAL.RATING_METRIC_MATRIX_PREFIX_BYTES)
            if matrix_bytes then
                matrix_file = 'motm_rating_metric_matrix_team_' .. tostring(team_index) ..
                    '_capture_' .. string.format('%03d', capture_index) .. '.bin'
                local ok_file, file_status = SPECIAL.write_binary_bytes(
                    SPECIAL.dir .. '\\' .. matrix_file, matrix_bytes)
                if ok_file then
                    matrix_status = 'captured'
                    SPECIAL.rating_metric_prefixes_exported =
                        SPECIAL.rating_metric_prefixes_exported + 1
                else
                    matrix_status = 'binary_write_' .. file_status
                    log_error('rating_metric_matrix_file', matrix_file, file_status)
                end
            end
        end
        write_csv_row(SPECIAL.rating_metric_matrix_csv, {
            capture_index, now_text(), trigger, phase or '', event_id or '', team_index,
            ptr_hex(matrix_pointer), string.format('0x%X', SPECIAL.RATING_METRIC_INDEX_STRIDE),
            SPECIAL.RATING_METRIC_MATRIX_PREFIX_BYTES,
            matrix_bytes and bytes_to_hex(matrix_bytes, 0, #matrix_bytes) or '',
            matrix_file, matrix_status
        })

        if trigger:find('late_match_candidate_event_137', 1, true) then
            local full_bytes = nil
            local full_status = 'invalid_matrix_pointer'
            local full_file = ''
            if is_plausible_pointer(matrix_pointer) then
                full_bytes, full_status = safe_read('rating_metric_matrix_final',
                    'capture_' .. tostring(capture_index) .. '_team_' ..
                        tostring(team_index), matrix_pointer,
                    SPECIAL.RATING_METRIC_MATRIX_FULL_BYTES)
                if full_bytes then
                    full_file = 'motm_rating_metric_matrix_team_' ..
                        tostring(team_index) .. '_final_capture_' ..
                        string.format('%03d', capture_index) .. '.bin'
                    local ok_file, file_status = SPECIAL.write_binary_bytes(
                        SPECIAL.dir .. '\\' .. full_file, full_bytes)
                    if ok_file then
                        full_status = 'captured'
                        SPECIAL.rating_metric_full_matrices_exported =
                            SPECIAL.rating_metric_full_matrices_exported + 1
                    else
                        full_status = 'binary_write_' .. file_status
                        log_error('rating_metric_matrix_final_file', full_file,
                            file_status)
                    end
                end
            end
            write_csv_row(SPECIAL.rating_metric_matrix_full_csv, {
                capture_index, now_text(), trigger, phase or '', event_id or '',
                team_index, ptr_hex(matrix_pointer),
                SPECIAL.RATING_TEAM_RECORD_COUNT,
                SPECIAL.RATING_METRIC_INDEX_STRIDE,
                SPECIAL.RATING_METRIC_MATRIX_FULL_BYTES, full_file, full_status
            })
        end
    end
end

function SPECIAL.capture_motm_children(service, capture_index, trigger, phase,
                                     event_id, object_bytes)
    for _, child in ipairs(SPECIAL.MOTM_CHILDREN) do
        local child_pointer = le_u64_exact(object_bytes, child.offset) or 0
        local child_vtable_pointer = 0
        local child_bytes = nil
        local child_file = ''
        local status = 'invalid_pointer'

        if is_plausible_pointer(child_pointer) then
            child_bytes, status = safe_read('special_service_child',
                child.label .. '_capture_' .. tostring(capture_index),
                child_pointer, SPECIAL.CHILD_OBJECT_WINDOW_BYTES)
            if child_bytes then
                child_vtable_pointer = le_u64_exact(child_bytes, 0) or 0
                child_file = 'service_ManOfTheMatchService_child_' ..
                    SPECIAL.filename_token(child.label) .. '_capture_' ..
                    string.format('%03d', capture_index) .. '.bin'
                local ok_file, file_status = SPECIAL.write_binary_bytes(
                    SPECIAL.dir .. '\\' .. child_file, child_bytes)
                if ok_file then
                    status = 'captured'
                    SPECIAL.service_child_snapshots_exported =
                        SPECIAL.service_child_snapshots_exported + 1
                else
                    status = 'binary_write_' .. file_status
                    log_error('special_service_child_file', child_file,
                        file_status)
                end
            end
        end

        write_csv_row(SPECIAL.service_children_csv, {
            capture_index, now_text(), trigger, phase or '', event_id or '',
            service.service_family, child.label, offset_hex(child.offset),
            ptr_hex(child_pointer), ptr_hex(child_vtable_pointer),
            child_bytes and bytes_to_hex(child_bytes, 0,
                SPECIAL.CHILD_OBJECT_WINDOW_BYTES) or '', child_file, status
        })

        if child_bytes and child.offset == SPECIAL.RATING_CHILD_FIELD_OFFSET then
            SPECIAL.capture_rating_provider_state(capture_index, trigger, phase,
                event_id, child_pointer, child_bytes)
        end

        if child_bytes and is_plausible_pointer(child_vtable_pointer) and
           not service.child_vtables_captured[child.label] then
            local vtable_bytes, vtable_status = safe_read(
                'special_service_child_vtable', child.label,
                child_vtable_pointer, SPECIAL.CHILD_VTABLE_SLOTS * 8)
            if vtable_bytes then
                for slot_index = 0, SPECIAL.CHILD_VTABLE_SLOTS - 1 do
                    local function_pointer = le_u64_exact(
                        vtable_bytes, slot_index * 8) or 0
                    local function_rva = module_rva(function_pointer)
                    local method_bytes = nil
                    local method_file = ''
                    local method_status = 'not_module_pointer'
                    if function_rva and
                       function_rva + SPECIAL.SERVICE_METHOD_WINDOW_BYTES <=
                           game_size then
                        method_bytes, method_status = safe_read(
                            'special_service_child_method',
                            child.label .. '_slot_' .. tostring(slot_index),
                            function_pointer,
                            SPECIAL.SERVICE_METHOD_WINDOW_BYTES)
                        if method_bytes then
                            method_file = 'method_ManOfTheMatchService_child_' ..
                                SPECIAL.filename_token(child.label) ..
                                '_slot_' .. string.format('%02d', slot_index) ..
                                '_rva_0x' .. string.format('%X', function_rva) ..
                                '.bin'
                            local ok_file, file_status =
                                SPECIAL.write_binary_bytes(
                                    SPECIAL.dir .. '\\' .. method_file,
                                    method_bytes)
                            if ok_file then
                                method_status = 'captured'
                            else
                                method_status = 'binary_write_' .. file_status
                                log_error('special_service_child_method_file',
                                    method_file, file_status)
                            end
                        end
                    end
                    SPECIAL.service_child_vtable_rows_exported =
                        SPECIAL.service_child_vtable_rows_exported + 1
                    write_csv_row(SPECIAL.service_child_vtable_csv, {
                        service.service_family, child.label,
                        offset_hex(child.offset), slot_index,
                        ptr_hex(function_pointer),
                        function_rva and string.format('0x%X', function_rva) or '',
                        method_bytes and bytes_to_hex(method_bytes, 0,
                            SPECIAL.SERVICE_METHOD_WINDOW_BYTES) or '',
                        method_file, method_status
                    })
                end
                service.child_vtables_captured[child.label] = true
            else
                log_error('special_service_child_vtable', child.label,
                    vtable_status)
            end
        end
    end
end

function SPECIAL.peek_current_motm(trigger)
    if not SPECIAL.motm_features_enabled then return false, 'motm_feature_disabled' end
    if not trigger:find('late_match_candidate_event_137', 1, true) and
       trigger ~= 'entered_career_hub' then
        return false, 'not_final_match_trigger'
    end
    if type(state.special_services) ~= 'table' then
        return false, 'services_unavailable'
    end
    for _, service in ipairs(state.special_services) do
        if service.service_family == 'ManOfTheMatchService' then
            local ok_resolution, object_pointer = pcall(GetPlugin,
                service.enum_value)
            object_pointer = ok_resolution and tonumber(object_pointer) or 0
            if not is_plausible_pointer(object_pointer) then
                return false, 'motm_service_pointer_invalid'
            end
            local object_bytes, object_status = safe_read('motm_peek',
                'service_object_prefix', object_pointer,
                SPECIAL.RATING_CHILD_FIELD_OFFSET + 8)
            if not object_bytes then return false, object_status end
            local child_pointer = le_u64_exact(object_bytes,
                SPECIAL.RATING_CHILD_FIELD_OFFSET) or 0
            if not is_plausible_pointer(child_pointer) then
                return false, 'rating_child_pointer_invalid'
            end
            local child_bytes, child_status = safe_read('motm_peek',
                'rating_child_prefix', child_pointer,
                SPECIAL.RATING_CHILD_STATE_OFFSET + 8)
            if not child_bytes then return false, child_status end
            local state_pointer = le_u64_exact(child_bytes,
                SPECIAL.RATING_CHILD_STATE_OFFSET) or 0
            if not is_plausible_pointer(state_pointer) then
                return false, 'rating_state_pointer_invalid'
            end
            local state_bytes, state_status = safe_read('motm_peek',
                'rating_state_result_prefix', state_pointer, 0x10)
            if not state_bytes then return false, state_status end
            local selected_team = le_u32(state_bytes,
                SPECIAL.RATING_SELECTED_TEAM_OFFSET)
            local selected_player = nil
            if selected_team == 0 or selected_team == 1 then
                selected_player = le_u32(state_bytes,
                    SPECIAL.RATING_SELECTED_PLAYER_BASE_OFFSET +
                    selected_team * 4)
            end
            if selected_player and selected_player > 0 and
               selected_player ~= 0xFFFFFFFF then
                SPECIAL.latest_motm_team_index = selected_team
                SPECIAL.latest_motm_player_id = selected_player
                log_progress('motm_peek_resolved',
                    'team=' .. tostring(selected_team) ..
                    ';player=' .. tostring(selected_player))
                return true, 'resolved'
            end
            return false, 'selection_not_ready'
        end
    end
    return false, 'motm_service_not_found'
end

function SPECIAL.peek_current_game_ratings(trigger)
    if not SPECIAL.rating_features_enabled then return false, 'rating_feature_disabled' end
    if not trigger:find('late_match_candidate_event_137', 1, true) and
       trigger ~= 'entered_career_hub' then
        return false, 'not_final_match_trigger'
    end

    local root_slot_pointer = game_base + SPECIAL.RATING_MANAGER_ROOT_SLOT_RVA
    local root_pointer, root_status = read_qword(
        'rating_peek', 'manager_root_slot', root_slot_pointer)
    root_pointer = root_pointer or 0
    if not is_plausible_pointer(root_pointer) then
        return false, root_status == 'ok' and 'manager_root_invalid' or root_status
    end

    local index_bytes, index_status = safe_read('rating_peek',
        'manager_active_index', root_pointer +
            SPECIAL.RATING_MANAGER_ACTIVE_INDEX_OFFSET, 4)
    if not index_bytes then return false, index_status end
    local active_index = le_u32(index_bytes, 0)
    if not active_index or active_index == 0 then
        return false, 'manager_active_index_zero'
    end

    local bucket_index = active_index % SPECIAL.RATING_MANAGER_BUCKET_COUNT
    local manager_pointer = root_pointer +
        bucket_index * SPECIAL.RATING_MANAGER_BUCKET_STRIDE
    if not is_plausible_pointer(manager_pointer) then
        return false, 'manager_pointer_invalid'
    end

    local ready_bytes, ready_status = safe_read('rating_peek',
        'manager_ready_flag',
        manager_pointer + SPECIAL.RATING_MANAGER_READY_FLAG_OFFSET, 1)
    if not ready_bytes then return false, ready_status end
    local ready_flag = byte_at(ready_bytes, 0) or 0
    if ready_flag == 0 then return false, 'manager_not_ready' end

    local begin_pointer, begin_status = read_qword('rating_peek',
        'gameplay_array_begin',
        manager_pointer + SPECIAL.RATING_GAMEPLAY_ARRAY_BEGIN_OFFSET)
    local end_pointer, end_status = read_qword('rating_peek',
        'gameplay_array_end',
        manager_pointer + SPECIAL.RATING_GAMEPLAY_ARRAY_END_OFFSET)
    begin_pointer = begin_pointer or 0
    end_pointer = end_pointer or 0
    if not is_plausible_pointer(begin_pointer) or
       not is_plausible_pointer(end_pointer) or end_pointer < begin_pointer then
        return false, 'gameplay_array_bounds_invalid:' ..
            tostring(begin_status) .. ':' .. tostring(end_status)
    end

    local byte_count = end_pointer - begin_pointer
    if byte_count % SPECIAL.RATING_GAMEPLAY_RECORD_BYTES ~= 0 then
        return false, 'gameplay_array_stride_mismatch'
    end
    local record_count = math.floor(byte_count /
        SPECIAL.RATING_GAMEPLAY_RECORD_BYTES)
    if record_count <= 0 or
       record_count > SPECIAL.RATING_GAMEPLAY_RECORD_MAX_COUNT then
        return false, 'gameplay_array_record_count_out_of_bounds'
    end

    local array_bytes, array_status = safe_read('rating_peek',
        'gameplay_rating_records', begin_pointer, byte_count)
    if not array_bytes then return false, array_status end

    -- Re-read boundaries after the bulk read. We do not invoke the game's
    -- ref-counting helper, so only accept a stable read-only snapshot.
    local begin_pointer_after = read_qword('rating_peek',
        'gameplay_array_begin_after',
        manager_pointer + SPECIAL.RATING_GAMEPLAY_ARRAY_BEGIN_OFFSET)
    local end_pointer_after = read_qword('rating_peek',
        'gameplay_array_end_after',
        manager_pointer + SPECIAL.RATING_GAMEPLAY_ARRAY_END_OFFSET)
    if begin_pointer_after ~= begin_pointer or end_pointer_after ~= end_pointer then
        return false, 'gameplay_array_changed_during_read'
    end

    SPECIAL.latest_game_ratings = {}
    local accepted = 0
    for record_index = 0, record_count - 1 do
        local record_offset = record_index * SPECIAL.RATING_GAMEPLAY_RECORD_BYTES
        local team_index = le_u32(array_bytes,
            record_offset + SPECIAL.RATING_GAMEPLAY_RECORD_TEAM_OFFSET)
        local player_id = le_u32(array_bytes,
            record_offset + SPECIAL.RATING_GAMEPLAY_RECORD_PLAYER_ID_OFFSET)
        local raw_rating = le_f32(array_bytes,
            record_offset + SPECIAL.RATING_RAW_GAMEPLAY_PLAYER_OFFSET)
        local quantized_rating = nil
        local row_status = 'record_not_current_player'
        if (team_index == 0 or team_index == 1) and player_id and
           player_id > 0 and player_id ~= 0xFFFFFFFF and
           type(raw_rating) == 'number' and raw_rating >= 0 and raw_rating <= 20 then
            -- The confirmed getter performs raw*10 + 0.5, then a float
            -- integer-quantizer, then /10. Ratings are positive, so floor is
            -- equivalent to the observed half-up one-decimal quantization.
            quantized_rating = math.floor(raw_rating * 10.0 + 0.5) / 10.0
            SPECIAL.latest_game_ratings[
                tostring(team_index) .. ':' .. tostring(player_id)
            ] = quantized_rating
            accepted = accepted + 1
            row_status = 'accepted_direct_rating'
        end
        write_csv_row(SPECIAL.game_ratings_csv, {
            now_text(), trigger, ptr_hex(root_slot_pointer),
            ptr_hex(root_pointer), active_index, bucket_index,
            ptr_hex(manager_pointer), ready_flag,
            ptr_hex(begin_pointer), ptr_hex(end_pointer), record_count,
            record_index, team_index or '', player_id or '',
            type(raw_rating) == 'number' and
                string.format('%.9g', raw_rating) or '',
            type(quantized_rating) == 'number' and
                string.format('%.1f', quantized_rating) or '',
            row_status
        })
        SPECIAL.game_rating_rows_exported =
            SPECIAL.game_rating_rows_exported + 1
    end
    SPECIAL.game_ratings_csv:flush()

    log_progress('rating_peek_resolved',
        'root=' .. ptr_hex(root_pointer) ..
        ';active_index=' .. tostring(active_index) ..
        ';bucket=' .. tostring(bucket_index) ..
        ';manager=' .. ptr_hex(manager_pointer) ..
        ';records=' .. tostring(record_count) ..
        ';accepted=' .. tostring(accepted))
    return accepted > 0, accepted > 0 and 'resolved' or 'no_valid_ratings'
end

function SPECIAL.capture_services(trigger, phase, event_id, snapshot_id)
    if type(state.special_services) ~= 'table' or
       #state.special_services == 0 then return end
    SPECIAL.service_capture_index = SPECIAL.service_capture_index + 1
    local capture_index = SPECIAL.service_capture_index
    SPECIAL.capture_rating_resolver_runtime(capture_index, trigger, phase, event_id)
    for _, service in ipairs(state.special_services) do
        local ok_resolution, object_pointer = pcall(GetPlugin,
            service.enum_value)
        object_pointer = ok_resolution and tonumber(object_pointer) or 0
        local status = 'resolution_failed'
        local vtable_pointer = 0
        local object_bytes = nil
        local object_file = ''
        if is_plausible_pointer(object_pointer) then
            object_bytes, status = safe_read('special_service_object',
                service.service_family .. '_' .. tostring(capture_index),
                object_pointer, SPECIAL.SERVICE_OBJECT_WINDOW_BYTES)
            if object_bytes then
                vtable_pointer = le_u64_exact(object_bytes, 0) or 0
                object_file = 'service_' ..
                    SPECIAL.filename_token(service.service_family) .. '_capture_' ..
                    string.format('%03d', capture_index) .. '.bin'
                local ok_file, file_status = SPECIAL.write_binary_bytes(
                    SPECIAL.dir .. '\\' .. object_file,
                    object_bytes)
                if ok_file then
                    status = 'captured'
                    SPECIAL.service_snapshots_exported =
                        SPECIAL.service_snapshots_exported + 1
                else
                    status = 'binary_write_' .. file_status
                    log_error('special_service_file', object_file, file_status)
                end
            end
        elseif ok_resolution then
            status = 'resolved_invalid_pointer'
        end
        write_csv_row(SPECIAL.service_snapshots_csv, {
            capture_index, now_text(), trigger, phase or '', event_id or '',
            snapshot_id or '', service.service_family, service.global_name,
            string.format('0x%X', service.enum_value), ptr_hex(object_pointer),
            ptr_hex(vtable_pointer), object_bytes and
                bytes_to_hex(object_bytes, 0,
                    SPECIAL.SERVICE_OBJECT_WINDOW_BYTES) or '',
            object_file, status
        })

        if object_bytes and service.service_family == 'GameRatingsService' then
            SPECIAL.capture_game_ratings_vector(capture_index, trigger, phase,
                event_id, object_bytes)
        elseif object_bytes and
               service.service_family == 'ManOfTheMatchService' then
            SPECIAL.capture_motm_children(service, capture_index, trigger, phase,
                event_id, object_bytes)
        end

        if not service.vtable_captured and
           is_plausible_pointer(vtable_pointer) then
            local vtable_bytes, vtable_status = safe_read(
                'special_service_vtable', service.service_family,
                vtable_pointer, SPECIAL.SERVICE_VTABLE_SLOTS * 8)
            if vtable_bytes then
                for slot_index = 0, SPECIAL.SERVICE_VTABLE_SLOTS - 1 do
                    local function_pointer = le_u64_exact(
                        vtable_bytes, slot_index * 8) or 0
                    local function_rva = module_rva(function_pointer)
                    local method_bytes = nil
                    local method_file = ''
                    local method_status = 'not_module_pointer'
                    if function_rva and
                       function_rva + SPECIAL.SERVICE_METHOD_WINDOW_BYTES <=
                           game_size then
                        method_bytes, method_status = safe_read(
                            'special_service_method',
                            service.service_family .. '_slot_' ..
                                tostring(slot_index),
                            function_pointer,
                            SPECIAL.SERVICE_METHOD_WINDOW_BYTES)
                        if method_bytes then
                            method_file = 'method_' ..
                                SPECIAL.filename_token(service.service_family) ..
                                '_slot_' .. string.format('%02d', slot_index) ..
                                '_rva_0x' .. string.format('%X', function_rva) ..
                                '.bin'
                            local ok_file, file_status = SPECIAL.write_binary_bytes(
                                SPECIAL.dir .. '\\' ..
                                    method_file, method_bytes)
                            if ok_file then
                                method_status = 'captured'
                            else
                                method_status = 'binary_write_' .. file_status
                                log_error('special_service_method_file',
                                    method_file, file_status)
                            end
                        end
                    end
                    SPECIAL.service_vtable_rows_exported =
                        SPECIAL.service_vtable_rows_exported + 1
                    write_csv_row(SPECIAL.service_vtable_csv, {
                        service.service_family, service.global_name,
                        string.format('0x%X', service.enum_value), slot_index,
                        ptr_hex(function_pointer),
                        function_rva and string.format('0x%X', function_rva) or '',
                        method_bytes and bytes_to_hex(method_bytes, 0,
                            SPECIAL.SERVICE_METHOD_WINDOW_BYTES) or '',
                        method_file, method_status
                    })
                end
                service.vtable_captured = true
            else
                log_error('special_service_vtable', service.service_family,
                    vtable_status)
            end
        end
    end
end

local function validate_live_interface(snapshot_id, trigger,
                                       singleton_pointer, interface_pointer)
    local interface_object, interface_status = safe_read(
        'interface_validation', 'interface_object', interface_pointer, 8)
    if not interface_object then return nil, interface_status end
    local vtable_pointer = le_u64_exact(interface_object, 0) or 0
    if not is_plausible_pointer(vtable_pointer) then
        return nil, 'invalid_vtable_pointer'
    end
    local slot37_live = select(1, read_qword('interface_validation',
        'slot37', vtable_pointer + 0x128)) or 0
    local slot50_live = select(1, read_qword('interface_validation',
        'slot50', vtable_pointer + 0x190)) or 0
    local slots_valid =
        slot37_live == SPECIAL.slot37_pointer and
        slot50_live == SPECIAL.expected_slot50_pointer
    local stats_root_pointer = select(1, read_qword('stats_root',
        'interface_plus_0x38FE0',
        interface_pointer + INTERFACE_STATS_ROOT_OFFSET)) or 0
    local status = slots_valid and is_plausible_pointer(stats_root_pointer) and
        'validated' or 'validation_failed'
    write_csv_row(interface_csv, {
        snapshot_id, trigger, ptr_hex(singleton_pointer),
        ptr_hex(interface_pointer), ptr_hex(vtable_pointer),
        ptr_hex(slot37_live), module_rva_hex(slot37_live),
        ptr_hex(slot50_live), module_rva_hex(slot50_live),
        ptr_hex(interface_pointer + INTERFACE_STATS_ROOT_OFFSET),
        ptr_hex(stats_root_pointer), status
    })
    if status ~= 'validated' then return nil, status end
    return stats_root_pointer, 'validated'
end

function SPECIAL.capture_player_windows(snapshot_id, trigger,
                                        snapshot_data)
    if not trigger:find('late_match_candidate_event_137', 1, true) then
        return
    end
    local by_player_pointer = {}
    local by_parallel_pointer = {}
    for _, player in ipairs(snapshot_data.players) do
        if is_plausible_pointer(player.player_pointer) then
            by_player_pointer[player.player_pointer] = player
        end
        if is_plausible_pointer(player.parallel_state_pointer) then
            by_parallel_pointer[player.parallel_state_pointer] = player
        end
    end
    local special_window_records_seen = 0
    for _, player in ipairs(snapshot_data.players) do
        special_window_records_seen = special_window_records_seen + 1
        local next_player = by_player_pointer[
            (player.player_pointer or 0) + SPECIAL.PLAYER_OBJECT_ALLOCATION_STRIDE]
        local previous_player = by_player_pointer[
            (player.player_pointer or 0) - SPECIAL.PLAYER_OBJECT_ALLOCATION_STRIDE]
        local next_parallel = by_parallel_pointer[
            (player.parallel_state_pointer or 0) +
                PARALLEL_STATE_ALLOCATION_STRIDE]
        local previous_parallel = by_parallel_pointer[
            (player.parallel_state_pointer or 0) -
                PARALLEL_STATE_ALLOCATION_STRIDE]
        local player_forward = next_player and
            next_player.team_index == player.team_index and
            next_player.array_index == player.array_index + 1
        local player_backward = previous_player and
            previous_player.team_index == player.team_index and
            previous_player.array_index == player.array_index - 1
        local parallel_forward = next_parallel and
            next_parallel.team_index == player.team_index and
            next_parallel.array_index == player.array_index + 1
        local parallel_backward = previous_parallel and
            previous_parallel.team_index == player.team_index and
            previous_parallel.array_index == player.array_index - 1

        local player_bytes = nil
        local parallel_bytes = nil
        local player_file = ''
        local parallel_file = ''
        local status_parts = {}
        local player_id = tonumber(player.direct_player_id) or 0
        local base_token = 's' .. tostring(snapshot_id) .. '_t' ..
            tostring(player.team_index) .. '_i' ..
            tostring(player.array_index) .. '_id' .. tostring(player_id)

        -- Full allocation windows intentionally require the same forward proof
        -- used by the successful v0.33 binary-window probe. A backward-only
        -- neighbour is reported but never used to extend the read beyond the
        -- currently proven allocation interval.
        if special_window_records_seen > SPECIAL.MAX_WINDOW_PLAYER_RECORDS then
            status_parts[#status_parts + 1] = 'player_skipped_special_window_cap'
        elseif player_forward then
            player_bytes = select(1, safe_read('special_player_object_window',
                base_token, player.player_pointer,
                SPECIAL.PLAYER_OBJECT_WINDOW_BYTES))
            if player_bytes then
                player_file = 'player_object_' .. base_token .. '.bin'
                local ok_file, file_status = SPECIAL.write_binary_bytes(
                    SPECIAL.dir .. '\\' .. player_file,
                    player_bytes)
                if ok_file then
                    SPECIAL.player_object_windows_exported =
                        SPECIAL.player_object_windows_exported + 1
                    status_parts[#status_parts + 1] = 'player_captured'
                else
                    status_parts[#status_parts + 1] =
                        'player_file_' .. file_status
                end
            else
                status_parts[#status_parts + 1] = 'player_read_failed'
            end
        else
            status_parts[#status_parts + 1] = 'player_skipped_no_forward_stride'
        end

        if special_window_records_seen > SPECIAL.MAX_WINDOW_PLAYER_RECORDS then
            status_parts[#status_parts + 1] = 'parallel_skipped_special_window_cap'
        elseif parallel_forward then
            parallel_bytes = select(1, safe_read(
                'special_parallel_state_window', base_token,
                player.parallel_state_pointer,
                SPECIAL.PARALLEL_STATE_WINDOW_BYTES))
            if parallel_bytes then
                parallel_file = 'parallel_state_' .. base_token .. '.bin'
                local ok_file, file_status = SPECIAL.write_binary_bytes(
                    SPECIAL.dir .. '\\' .. parallel_file,
                    parallel_bytes)
                if ok_file then
                    SPECIAL.parallel_state_windows_exported =
                        SPECIAL.parallel_state_windows_exported + 1
                    status_parts[#status_parts + 1] = 'parallel_captured'
                else
                    status_parts[#status_parts + 1] =
                        'parallel_file_' .. file_status
                end
            else
                status_parts[#status_parts + 1] = 'parallel_read_failed'
            end
        else
            status_parts[#status_parts + 1] =
                'parallel_skipped_no_forward_stride'
        end

        write_csv_row(SPECIAL.player_windows_csv, {
            snapshot_id, trigger, player.team_index, player.array_index,
            player.selector, player_id, ptr_hex(player.player_pointer),
            ptr_hex(player.parallel_state_pointer),
            player_forward and 'true' or 'false',
            player_backward and 'true' or 'false',
            parallel_forward and 'true' or 'false',
            parallel_backward and 'true' or 'false',
            player_bytes and #player_bytes or 0,
            parallel_bytes and #parallel_bytes or 0,
            player_file, parallel_file, table.concat(status_parts, ';')
        })
    end
end

local function capture_stats(trigger, event_id,
                             singleton_pointer, interface_pointer)
    if state.in_capture or stats_snapshots >= MAX_STATS_SNAPSHOTS then
        return nil, 'snapshot_cap_or_reentry'
    end
    state.in_capture = true
    stats_snapshots = stats_snapshots + 1
    local snapshot_id = stats_snapshots
    local snapshot_data = {
        snapshot_id = snapshot_id,
        trigger = trigger,
        event_id = event_id,
        players = {},
        teams = {}
    }
    local ok, result = pcall(function()
        local stats_root_pointer, root_status = validate_live_interface(
            snapshot_id, trigger, singleton_pointer, interface_pointer)
        if not stats_root_pointer then return root_status end

        local valid_teams = 0
        for team_index = 0, 1 do
            local block_pointer = stats_root_pointer + team_index * TEAM_STRIDE
            local header, header_status = safe_read('team_block',
                'team_' .. tostring(team_index) .. '_header',
                block_pointer, 0x40)
            if not header then
                write_csv_row(team_blocks_csv, {
                    snapshot_id, trigger, team_index, ptr_hex(block_pointer),
                    '', '', '', hex_u32(TEAM_STRIDE),
                    hex_u32(TEAM_TOTALS_OFFSET), '', header_status
                })
            else
                local player_array = le_u64_exact(
                    header, TEAM_PLAYER_ARRAY_OFFSET) or 0
                local player_count = le_u32(
                    header, TEAM_PLAYER_COUNT_OFFSET) or 0
                local selector_base = le_s32(
                    header, TEAM_SELECTOR_BASE_OFFSET) or 0
                local count_valid = player_count <= MAX_PLAYERS_PER_TEAM
                local array_valid = player_count == 0 or
                    is_plausible_pointer(player_array)
                local team_status = count_valid and array_valid and
                    'validated' or 'invalid_count_or_array'
                write_csv_row(team_blocks_csv, {
                    snapshot_id, trigger, team_index, ptr_hex(block_pointer),
                    ptr_hex(player_array), player_count, selector_base,
                    hex_u32(TEAM_STRIDE), hex_u32(TEAM_TOTALS_OFFSET),
                    bytes_to_hex(header, 0, 0x40), team_status
                })

                local totals, totals_status = safe_read('team_totals',
                    'team_' .. tostring(team_index) .. '_getter_values',
                    block_pointer + TEAM_TOTALS_OFFSET, GETTER_VALUE_BYTES)
                if totals then
                    local team_values = {}
                    for getter_key = 0, MAX_GETTER_KEY do
                        local raw_value = le_u32(totals, getter_key * 4) or 0
                        local signed_value = le_s32(totals, getter_key * 4) or 0
                        team_values[getter_key] = signed_value
                        team_values_exported = team_values_exported + 1
                        write_csv_row(team_values_csv, {
                            snapshot_id, trigger, team_index, getter_key,
                            signed_value, hex_u32(raw_value)
                        })
                    end
                    local team_special_values = {}
                    if SPECIAL.special_float_features_enabled then
                        local special_bytes, special_status = safe_read(
                            'team_special_floats',
                            'team_' .. tostring(team_index) .. '_xg_xa',
                            block_pointer + SPECIAL.TEAM_SPECIAL_NPK_XG_OFFSET, 8)
                        if special_bytes then
                            for _, field in ipairs(SPECIAL_FLOAT_EXPORT_FIELDS) do
                                local relative_offset = field.team_offset -
                                    SPECIAL.TEAM_SPECIAL_NPK_XG_OFFSET
                                team_special_values[field.semantic] = {
                                    raw = le_u32(special_bytes, relative_offset),
                                    value = le_f32(special_bytes, relative_offset),
                                    offset = field.team_offset,
                                    source_label = field.source_label
                                }
                            end
                        else
                            log_error('team_special_floats',
                                'team_' .. tostring(team_index), special_status)
                        end
                    end
                    snapshot_data.teams[team_index] = {
                        team_index = team_index,
                        block_pointer = block_pointer,
                        values = team_values,
                        special_values = team_special_values
                    }
                else
                    log_error('team_totals', 'team_' .. tostring(team_index),
                        totals_status)
                end

                if team_status == 'validated' then
                    valid_teams = valid_teams + 1
                    team_blocks_exported = team_blocks_exported + 1
                    if player_count > 0 then
                        local pointer_bytes, pointer_status = safe_read(
                            'player_pointer_array',
                            'team_' .. tostring(team_index),
                            player_array, player_count * 8)
                        if pointer_bytes then
                            for array_index = 0, player_count - 1 do
                                local player_pointer = le_u64_exact(
                                    pointer_bytes, array_index * 8) or 0
                                local selector = selector_base + array_index
                                local pointer_status_text =
                                    is_plausible_pointer(player_pointer) and
                                    'plausible' or 'invalid_pointer'
                                write_csv_row(player_pointers_csv, {
                                    snapshot_id, trigger, team_index,
                                    array_index, selector,
                                    ptr_hex(player_pointer), pointer_status_text
                                })
                                if pointer_status_text == 'plausible' then
                                    local player_bytes, player_status = safe_read(
                                        'player_object',
                                        'snapshot_' .. tostring(snapshot_id) ..
                                        '_team_' .. tostring(team_index) ..
                                        '_selector_' .. tostring(selector),
                                        player_pointer,
                                        PLAYER_OBJECT_READ_BYTES)
                                    if player_bytes then
                                        player_objects_exported =
                                            player_objects_exported + 1
                                        local parallel_state_pointer =
                                            le_u64_exact(player_bytes,
                                                PARALLEL_STATE_POINTER_OFFSET)
                                            or 0
                                        local player_entry = {
                                            team_index = team_index,
                                            array_index = array_index,
                                            selector = selector,
                                            player_pointer = player_pointer,
                                            parallel_state_pointer =
                                                parallel_state_pointer,
                                            direct_player_id = 0,
                                            direct_identity_status =
                                                'pending_structural_proof',
                                            values = {},
                                            special_values = {}
                                        }
                                        snapshot_data.players[#snapshot_data.players + 1] =
                                            player_entry
                                        for getter_key = 0, MAX_GETTER_KEY do
                                            local value_offset =
                                                PLAYER_VALUES_OFFSET +
                                                getter_key * 4
                                            local raw_value = le_u32(
                                                player_bytes, value_offset) or 0
                                            local signed_value = le_s32(
                                                player_bytes, value_offset) or 0
                                            player_entry.values[getter_key] =
                                                signed_value
                                            player_values_exported =
                                                player_values_exported + 1
                                            write_csv_row(player_values_csv, {
                                                snapshot_id, trigger, team_index,
                                                array_index, selector,
                                                ptr_hex(player_pointer),
                                                getter_key, signed_value,
                                                hex_u32(raw_value)
                                            })
                                        end
                                        if SPECIAL.special_float_features_enabled then
                                            for _, field in ipairs(SPECIAL_FLOAT_EXPORT_FIELDS) do
                                                local raw_value = le_u32(player_bytes,
                                                    field.player_offset)
                                                local float_value = le_f32(player_bytes,
                                                    field.player_offset)
                                                player_entry.special_values[field.semantic] = {
                                                    raw = raw_value, value = float_value,
                                                    offset = field.player_offset,
                                                    source_label = field.source_label
                                                }
                                            end
                                        end
                                    else
                                        log_error('player_object',
                                            ptr_hex(player_pointer), player_status)
                                    end
                                end
                            end
                        else
                            log_error('player_pointer_array',
                                'team_' .. tostring(team_index), pointer_status)
                        end
                    end
                end
            end
        end
        local players_by_parallel_pointer = {}
        for _, player in ipairs(snapshot_data.players) do
            if is_plausible_pointer(player.parallel_state_pointer) then
                players_by_parallel_pointer[player.parallel_state_pointer] =
                    player
            end
        end
        for _, player in ipairs(snapshot_data.players) do
            local target_pointer = player.parallel_state_pointer or 0
            local forward_player = players_by_parallel_pointer[
                target_pointer + PARALLEL_STATE_ALLOCATION_STRIDE]
            local backward_player = players_by_parallel_pointer[
                target_pointer - PARALLEL_STATE_ALLOCATION_STRIDE]
            local forward_proof = forward_player and
                forward_player.team_index == player.team_index and
                forward_player.array_index == player.array_index + 1
            local backward_proof = backward_player and
                backward_player.team_index == player.team_index and
                backward_player.array_index == player.array_index - 1
            local direct_field_pointer = 0
            local direct_player_id = 0
            local direct_player_id_raw = 0
            local direct_status = 'parallel_state_pointer_invalid'
            if is_plausible_pointer(target_pointer) then
                direct_field_pointer = target_pointer +
                    PARALLEL_STATE_DIRECT_PLAYER_ID_OFFSET
                if forward_proof or backward_proof then
                    direct_identity_reads_attempted =
                        direct_identity_reads_attempted + 1
                    local direct_bytes, direct_read_status = safe_read(
                        'direct_player_id',
                        'snapshot_' .. tostring(snapshot_id) ..
                        '_team_' .. tostring(player.team_index) ..
                        '_selector_' .. tostring(player.selector),
                        direct_field_pointer, DIRECT_PLAYER_ID_BYTES)
                    if direct_bytes then
                        direct_identity_reads_successful =
                            direct_identity_reads_successful + 1
                        direct_player_id_raw = le_u32(direct_bytes, 0) or 0
                        direct_player_id = direct_player_id_raw
                        if direct_player_id > 0 then
                            direct_identity_nonzero_exported =
                                direct_identity_nonzero_exported + 1
                            direct_status = 'read_nonzero_u32'
                        else
                            direct_status = 'read_zero_u32'
                        end
                    else
                        direct_status = direct_read_status
                        log_error('direct_player_id',
                            ptr_hex(direct_field_pointer), direct_read_status)
                    end
                else
                    direct_identity_structurally_skipped =
                        direct_identity_structurally_skipped + 1
                    direct_status =
                        'skipped_no_adjacent_same_team_0x5C80_proof'
                end
            end
            player.direct_player_id = direct_player_id
            player.direct_identity_status = direct_status
            write_csv_row(direct_identity_csv, {
                snapshot_id, trigger, player.team_index,
                player.array_index, player.selector,
                ptr_hex(player.player_pointer), ptr_hex(target_pointer),
                ptr_hex(direct_field_pointer),
                forward_proof and 'true' or 'false',
                backward_proof and 'true' or 'false',
                direct_player_id, hex_u32(direct_player_id_raw),
                direct_status
            })
        end
        if EXPORT_DIAGNOSTICS then
            SPECIAL.capture_player_windows(snapshot_id, trigger, snapshot_data)
        end
        state.last_snapshot_epoch = now_epoch()
        -- Only the latest compact pointer manifest is needed online. All value
        -- history is already durable in CSV and is correlated offline.
        state.stats_snapshot_data = { [snapshot_id] = snapshot_data }
        state.latest_stats_snapshot_id = snapshot_id
        return valid_teams == 2 and 'captured_two_teams' or
            'captured_partial_team_layout'
    end)
    state.in_capture = false
    if not ok then
        log_error('capture_stats', trigger, result)
        return snapshot_id, 'capture_exception'
    end
    log_progress('stats_snapshot_completed',
        'snapshot=' .. tostring(snapshot_id) ..
        ';trigger=' .. trigger .. ';status=' .. scalar(result))
    return snapshot_id, result
end

local function player_name_for_id(player_id)
    -- Name helper calls are not required for identity discovery. IDs remain the
    -- durable join key and names are resolved offline after upload.
    return ''
end

local function collect_tracker_snapshot(trigger)
    if state.tracker_capture_attempts >= MAX_TRACKER_CAPTURES or
       not is_plausible_pointer(state.tracker_service_pointer) then
        return nil, 'unavailable_or_capped'
    end
    state.tracker_capture_attempts = state.tracker_capture_attempts + 1
    local capture_id = state.tracker_capture_attempts
    local snapshot = {
        capture_id = capture_id,
        trigger = trigger,
        reported_outer_count = 0,
        enumerated_outer_count = 0,
        nested_total = 0,
        players = {}
    }
    local status = 'ok'
    local service_bytes, service_status = safe_read('tracker_outer',
        'MatchEventTrackerService', state.tracker_service_pointer, 0x28)
    if not service_bytes then
        status = service_status
    else
        local head_pointer = le_u64_exact(service_bytes, 0x20) or 0
        if not is_plausible_pointer(head_pointer) then
            status = 'outer_head_missing'
        else
            local head_bytes, head_status = safe_read('tracker_outer',
                'outer_head', head_pointer, 0x30)
            if not head_bytes then
                status = head_status
            else
                local outer_sentinel = head_pointer + 0x08
                local root_pointer = le_u64_exact(head_bytes, 0x18) or 0
                local reported_count = le_u32(head_bytes, 0x28) or 0
                snapshot.reported_outer_count = reported_count
                if reported_count == 0 or root_pointer == 0 or
                   root_pointer == outer_sentinel then
                    status = 'empty'
                elseif reported_count > MAX_TRACKER_OUTER_NODES then
                    status = 'outer_count_over_cap'
                    log_error('tracker_outer', 'reported_count',
                        status .. '_' .. tostring(reported_count))
                else
                    local stack = { { pointer = root_pointer, depth = 0 } }
                    local visited = {}
                    local all_nested_counts_match = true
                    while #stack > 0 and status == 'ok' do
                        local item = table.remove(stack)
                        local node_pointer = item.pointer
                        if not visited[node_pointer] then
                            if item.depth > MAX_TRACKER_DEPTH or
                               snapshot.enumerated_outer_count >=
                                   MAX_TRACKER_OUTER_NODES then
                                status = 'outer_depth_or_node_cap'
                                log_error('tracker_outer', ptr_hex(node_pointer),
                                    status)
                                break
                            end
                            local node_bytes, node_status = safe_read(
                                'tracker_outer', 'outer_player_node',
                                node_pointer, TRACKER_OUTER_NODE_BYTES)
                            if not node_bytes then
                                status = node_status
                                break
                            end
                            visited[node_pointer] = true
                            snapshot.enumerated_outer_count =
                                snapshot.enumerated_outer_count + 1
                            local enumerated_index =
                                snapshot.enumerated_outer_count
                            local left = le_u64_exact(node_bytes, 0x00) or 0
                            local right = le_u64_exact(node_bytes, 0x08) or 0
                            local player_id = le_u32(node_bytes, 0x20) or 0
                            local player_name = player_name_for_id(player_id)
                            local nested_sentinel = node_pointer + 0x28
                            local nested_root =
                                le_u64_exact(node_bytes, 0x38) or 0
                            local nested_candidate_count =
                                le_u32(node_bytes, 0x48) or 0
                            local player_entry = {
                                player_id = player_id,
                                player_name = player_name,
                                outer_pointer = node_pointer,
                                outer_depth = item.depth,
                                candidate_count = nested_candidate_count,
                                enumerated_count = 0,
                                max_depth = 0,
                                values = {}
                            }
                            snapshot.players[#snapshot.players + 1] =
                                player_entry
                            tracker_outer_headers_exported =
                                tracker_outer_headers_exported + 1
                            write_csv_row(tracker_headers_csv, {
                                capture_id, trigger, ptr_hex(node_pointer),
                                player_id, player_name,
                                TRACKER_OUTER_NODE_BYTES,
                                bytes_to_hex(node_bytes, 0,
                                    TRACKER_OUTER_NODE_BYTES)
                            })
                            if nested_candidate_count >
                               MAX_TRACKER_NESTED_PER_PLAYER then
                                status = 'nested_player_count_over_cap'
                                log_error('tracker_nested', tostring(player_id),
                                    status .. '_' ..
                                    tostring(nested_candidate_count))
                                break
                            elseif nested_candidate_count > 0 and
                                   nested_root ~= 0 and
                                   nested_root ~= nested_sentinel then
                                local nested_stack = {
                                    { pointer = nested_root, depth = 0 }
                                }
                                local nested_visited = {}
                                while #nested_stack > 0 and status == 'ok' do
                                    local nested_item =
                                        table.remove(nested_stack)
                                    local nested_pointer = nested_item.pointer
                                    if not nested_visited[nested_pointer] then
                                        if nested_item.depth >
                                           MAX_TRACKER_DEPTH then
                                            status = 'nested_depth_over_cap'
                                            break
                                        end
                                        if player_entry.enumerated_count >=
                                           MAX_TRACKER_NESTED_PER_PLAYER or
                                           snapshot.nested_total >=
                                           MAX_TRACKER_NESTED_TOTAL then
                                            status = 'nested_node_cap'
                                            break
                                        end
                                        local nested_bytes, nested_status =
                                            safe_read('tracker_nested',
                                                'player_' ..
                                                tostring(player_id) ..
                                                '_node', nested_pointer,
                                                TRACKER_NESTED_NODE_BYTES)
                                        if not nested_bytes then
                                            status = nested_status
                                            break
                                        end
                                        nested_visited[nested_pointer] = true
                                        player_entry.enumerated_count =
                                            player_entry.enumerated_count + 1
                                        snapshot.nested_total =
                                            snapshot.nested_total + 1
                                        if nested_item.depth >
                                           player_entry.max_depth then
                                            player_entry.max_depth =
                                                nested_item.depth
                                        end
                                        local nested_left = le_u64_exact(
                                            nested_bytes, 0x00) or 0
                                        local nested_right = le_u64_exact(
                                            nested_bytes, 0x08) or 0
                                        local key_id =
                                            le_u32(nested_bytes, 0x20) or 0
                                        local value =
                                            le_u32(nested_bytes, 0x24) or 0
                                        local color_flag =
                                            byte_at(nested_bytes, 0x18) or 0
                                        player_entry.values[key_id] = value
                                        tracker_values_exported =
                                            tracker_values_exported + 1
                                        write_csv_row(tracker_values_csv, {
                                            capture_id, trigger, player_id,
                                            player_name, key_id, value,
                                            color_flag
                                        })
                                        if is_plausible_pointer(nested_right) and
                                           nested_right ~= nested_sentinel and
                                           not nested_visited[nested_right] then
                                            nested_stack[#nested_stack + 1] = {
                                                pointer = nested_right,
                                                depth = nested_item.depth + 1
                                            }
                                        end
                                        if is_plausible_pointer(nested_left) and
                                           nested_left ~= nested_sentinel and
                                           not nested_visited[nested_left] then
                                            nested_stack[#nested_stack + 1] = {
                                                pointer = nested_left,
                                                depth = nested_item.depth + 1
                                            }
                                        end
                                    end
                                end
                            end
                            local count_matches =
                                player_entry.enumerated_count ==
                                player_entry.candidate_count
                            if not count_matches then
                                all_nested_counts_match = false
                            end
                            write_csv_row(tracker_players_csv, {
                                capture_id, trigger, enumerated_index,
                                ptr_hex(node_pointer), player_id, player_name,
                                item.depth, nested_candidate_count,
                                player_entry.enumerated_count,
                                player_entry.max_depth,
                                count_matches and 'true' or 'false'
                            })
                            if is_plausible_pointer(right) and
                               right ~= outer_sentinel and
                               not visited[right] then
                                stack[#stack + 1] = {
                                    pointer = right,
                                    depth = item.depth + 1
                                }
                            end
                            if is_plausible_pointer(left) and
                               left ~= outer_sentinel and
                               not visited[left] then
                                stack[#stack + 1] = {
                                    pointer = left,
                                    depth = item.depth + 1
                                }
                            end
                        end
                    end
                    if status == 'ok' and
                       snapshot.enumerated_outer_count ~= reported_count then
                        status = 'outer_count_mismatch'
                    elseif status == 'ok' and
                           not all_nested_counts_match then
                        status = 'nested_count_mismatch'
                    end
                end
            end
        end
    end

    tracker_captures_exported = tracker_captures_exported + 1
    tracker_players_exported = tracker_players_exported +
        snapshot.enumerated_outer_count
    write_csv_row(tracker_captures_csv, {
        capture_id, now_text(), trigger, elapsed_seconds(),
        snapshot.reported_outer_count, snapshot.enumerated_outer_count,
        snapshot.nested_total, status
    })
    snapshot.status = status
    state.tracker_snapshot_data[capture_id] = snapshot
    state.latest_tracker_capture_id = capture_id
    log_progress('tracker_snapshot_completed',
        'capture=' .. tostring(capture_id) ..
        ';trigger=' .. trigger ..
        ';outer=' .. tostring(snapshot.enumerated_outer_count) ..
        ';nested=' .. tostring(snapshot.nested_total) ..
        ';status=' .. status)
    return capture_id, status
end

local function validate_direct_identity_join(snapshot_id, capture_id, trigger)
    local stats_snapshot = state.stats_snapshot_data[snapshot_id]
    local tracker_snapshot = state.tracker_snapshot_data[capture_id]
    if not stats_snapshot then return 'missing_identity_snapshot' end
    if not tracker_snapshot then return 'missing_tracker_snapshot' end

    local direct_counts = {}
    local direct_success = 0
    local structurally_skipped = 0
    local direct_nonzero = 0
    for _, player in ipairs(stats_snapshot.players) do
        if player.direct_identity_status == 'read_nonzero_u32' or
           player.direct_identity_status == 'read_zero_u32' then
            direct_success = direct_success + 1
        end
        if player.direct_identity_status ==
           'skipped_no_adjacent_same_team_0x5C80_proof' then
            structurally_skipped = structurally_skipped + 1
        end
        local player_id = player.direct_player_id or 0
        if player_id > 0 then
            direct_nonzero = direct_nonzero + 1
            direct_counts[player_id] = (direct_counts[player_id] or 0) + 1
        end
    end

    local unique_direct_ids = 0
    local duplicate_direct_ids = 0
    for _, count in pairs(direct_counts) do
        unique_direct_ids = unique_direct_ids + 1
        if count > 1 then
            duplicate_direct_ids = duplicate_direct_ids + 1
        end
    end

    local tracker_ids = {}
    local tracker_ids_in_direct_set = 0
    local tracker_ids_missing_direct = 0
    for _, player in ipairs(tracker_snapshot.players or {}) do
        local player_id = player.player_id or 0
        if player_id > 0 and not tracker_ids[player_id] then
            tracker_ids[player_id] = true
            if direct_counts[player_id] then
                tracker_ids_in_direct_set = tracker_ids_in_direct_set + 1
            else
                tracker_ids_missing_direct = tracker_ids_missing_direct + 1
            end
        end
    end

    local tracker_participants = 0
    for _ in pairs(tracker_ids) do tracker_participants =
        tracker_participants + 1 end
    local direct_ids_in_tracker = 0
    local direct_ids_not_in_tracker = 0
    for player_id in pairs(direct_counts) do
        if tracker_ids[player_id] then
            direct_ids_in_tracker = direct_ids_in_tracker + 1
        else
            direct_ids_not_in_tracker = direct_ids_not_in_tracker + 1
        end
    end

    local status = 'validated'
    if duplicate_direct_ids > 0 then
        status = 'duplicate_direct_ids'
    elseif tracker_ids_missing_direct > structurally_skipped then
        status = 'tracker_ids_missing_from_direct_set'
    elseif direct_success + structurally_skipped ~= #stats_snapshot.players then
        status = 'incomplete_direct_reads'
    elseif tracker_ids_missing_direct > 0 or structurally_skipped > 0 then
        status = 'validated_with_structural_skips'
    end
    write_csv_row(direct_validation_csv, {
        snapshot_id, capture_id, trigger, #stats_snapshot.players,
        direct_success, structurally_skipped, direct_nonzero, unique_direct_ids,
        duplicate_direct_ids, tracker_participants,
        tracker_ids_in_direct_set, tracker_ids_missing_direct,
        direct_ids_in_tracker, direct_ids_not_in_tracker, status
    })
    log_progress('direct_identity_join_completed',
        'snapshot=' .. tostring(snapshot_id) ..
        ';tracker=' .. tostring(capture_id) ..
        ';unique_direct=' .. tostring(unique_direct_ids) ..
        ';tracker_matched=' .. tostring(tracker_ids_in_direct_set) ..
        ';tracker_missing=' .. tostring(tracker_ids_missing_direct) ..
        ';status=' .. status)
    return status
end

local function export_final_match(snapshot_id, capture_id, trigger)
    local stats_snapshot = state.stats_snapshot_data[snapshot_id]
    local tracker_snapshot = state.tracker_snapshot_data[capture_id]
    if not stats_snapshot then return 'missing_stats_snapshot' end
    if not tracker_snapshot then return 'missing_tracker_snapshot' end

    local tracker_ids = {}
    local tracker_names = {}
    local tracker_players_by_id = {}
    local tracker_count = 0
    for _, tracker_player in ipairs(tracker_snapshot.players or {}) do
        local player_id = tracker_player.player_id or 0
        if player_id > 0 and not tracker_ids[player_id] then
            tracker_ids[player_id] = true
            tracker_names[player_id] = tracker_player.player_name or ''
            tracker_players_by_id[player_id] = tracker_player
            tracker_count = tracker_count + 1
        end
    end

    local direct_counts = {}
    local structurally_skipped = {}
    local direct_bindings = 0
    for _, player in ipairs(stats_snapshot.players) do
        local player_id = player.direct_player_id or 0
        if player_id > 0 then
            direct_counts[player_id] = (direct_counts[player_id] or 0) + 1
        elseif player.direct_identity_status ==
               'skipped_no_adjacent_same_team_0x5C80_proof' then
            structurally_skipped[#structurally_skipped + 1] = player
        end
    end

    local missing_tracker_ids = {}
    for player_id in pairs(tracker_ids) do
        if not direct_counts[player_id] then
            missing_tracker_ids[#missing_tracker_ids + 1] = player_id
        end
    end

    local set_difference_bindings = 0
    local set_difference_player = nil
    local set_difference_id = nil
    if #structurally_skipped == 1 and #missing_tracker_ids == 1 then
        set_difference_player = structurally_skipped[1]
        set_difference_id = missing_tracker_ids[1]
        set_difference_bindings = 1
    end

    local participant_rows = 0
    local nonparticipant_objects = 0
    local unresolved_objects = 0
    local represented_tracker_ids = {}
    local tracker_team_totals = { [0] = {}, [1] = {} }
    for _, player in ipairs(stats_snapshot.players) do
        local direct_id = player.direct_player_id or 0
        local resolved_id = direct_id
        local binding_source = 'direct_parallel_state_0x2A14'
        if direct_id <= 0 then
            if player == set_difference_player then
                resolved_id = set_difference_id
                binding_source =
                    'tracker_set_difference_single_structural_skip'
            else
                resolved_id = 0
                binding_source = 'unresolved_structural_skip'
                unresolved_objects = unresolved_objects + 1
            end
        else
            direct_bindings = direct_bindings + 1
        end
        local is_participant = resolved_id > 0 and tracker_ids[resolved_id] or
            false
        if is_participant then
            represented_tracker_ids[resolved_id] = true
        else
            nonparticipant_objects = nonparticipant_objects + 1
        end
        local player_name = resolved_id > 0 and
            (tracker_names[resolved_id] or '') or ''
        player.resolved_player_id = resolved_id
        player.binding_source = binding_source
        player.tracker_participant = is_participant
        player.player_name = player_name

        for _, field in ipairs(SPECIAL_FLOAT_EXPORT_FIELDS) do
            local entry = (player.special_values or {})[field.semantic] or {}
            write_csv_row(SPECIAL.float_values_csv, {
                snapshot_id, trigger, 'player', player.team_index,
                player.array_index, player.selector, resolved_id,
                field.semantic, field.source_label, ptr_hex(player.player_pointer),
                offset_hex(field.player_offset),
                entry.raw and hex_u32(entry.raw) or '',
                type(entry.value) == 'number' and
                    string.format('%.6f', entry.value) or '',
                type(entry.value) == 'number' and 'handler_offset_confirmed' or
                    'unreadable_float'
            })
            SPECIAL.special_float_rows_exported =
                SPECIAL.special_float_rows_exported + 1
        end

        write_csv_row(identity_manifest_csv, {
            snapshot_id, capture_id, trigger, player.team_index,
            player.array_index, player.selector, ptr_hex(player.player_pointer),
            ptr_hex(player.parallel_state_pointer), direct_id, resolved_id,
            player_name, binding_source, player.direct_identity_status,
            is_participant and 'true' or 'false'
        })
        final_identity_rows_exported = final_identity_rows_exported + 1

        if EXPORT_DIAGNOSTICS then
            for getter_key = 0, MAX_GETTER_KEY do
                write_csv_row(raw_export_csv, {
                    snapshot_id, capture_id, trigger, player.team_index,
                    player.array_index, player.selector, resolved_id, player_name,
                    binding_source, is_participant and 'true' or 'false',
                    getter_key, DIRECT_FIELD_BY_KEY[getter_key] or '',
                    stat_value(player.values, getter_key)
                })
                final_raw_rows_exported = final_raw_rows_exported + 1
            end
        end

        if is_participant then
            local tracker_values =
                (tracker_players_by_id[resolved_id] or {}).values or {}
            local row = {
                snapshot_id, capture_id, trigger, player.team_index,
                player.array_index, player.selector, resolved_id, player_name,
                binding_source, 'true'
            }
            append_export_values(row, player.values, tracker_values,
                player.special_values)
            if SPECIAL.latest_motm_player_id then
                row[#row + 1] = resolved_id == SPECIAL.latest_motm_player_id and
                    'true' or 'false'
            else
                row[#row + 1] = ''
            end
            local rating_key = tostring(player.team_index) .. ':' ..
                tostring(resolved_id)
            local game_rating = SPECIAL.latest_game_ratings[rating_key]
            row[#row + 1] = type(game_rating) == 'number' and
                string.format('%.1f', game_rating) or ''
            write_csv_row(participants_export_csv, row)
            for _, field in ipairs(TRACKER_EXPORT_FIELDS) do
                local totals = tracker_team_totals[player.team_index]
                totals[field.key] = stat_value(totals, field.key) +
                    stat_value(tracker_values, field.key)
            end
            participant_rows = participant_rows + 1
            final_participant_rows_exported =
                final_participant_rows_exported + 1
        end
    end

    local team_rows = 0
    for team_index = 0, 1 do
        local team = stats_snapshot.teams[team_index]
        if team and type(team.values) == 'table' then
            for _, field in ipairs(SPECIAL_FLOAT_EXPORT_FIELDS) do
                local entry = (team.special_values or {})[field.semantic] or {}
                write_csv_row(SPECIAL.float_values_csv, {
                    snapshot_id, trigger, 'team', team_index, '', '', '',
                    field.semantic, field.source_label,
                    ptr_hex(team.block_pointer or 0), offset_hex(field.team_offset),
                    entry.raw and hex_u32(entry.raw) or '',
                    type(entry.value) == 'number' and
                        string.format('%.6f', entry.value) or '',
                    type(entry.value) == 'number' and 'handler_offset_confirmed' or
                        'unreadable_float'
                })
                SPECIAL.special_float_rows_exported =
                    SPECIAL.special_float_rows_exported + 1
            end
            local row = { snapshot_id, trigger, team_index }
            append_export_values(row, team.values,
                tracker_team_totals[team_index], team.special_values)
            write_csv_row(teams_export_csv, row)
            team_rows = team_rows + 1
            final_team_rows_exported = final_team_rows_exported + 1
        end
    end

    local represented_count = 0
    for _ in pairs(represented_tracker_ids) do
        represented_count = represented_count + 1
    end
    local status = 'complete_participant_export'
    if represented_count ~= tracker_count or participant_rows ~= tracker_count then
        status = 'incomplete_participant_export'
    elseif team_rows ~= 2 then
        status = 'participant_export_complete_team_export_partial'
    elseif unresolved_objects > 0 then
        status = 'participant_export_complete_with_unresolved_nonparticipant'
    end
    final_export_status = status
    write_csv_row(export_summary_csv, {
        snapshot_id, capture_id, trigger, #stats_snapshot.players,
        tracker_count, direct_bindings, set_difference_bindings,
        unresolved_objects, participant_rows, nonparticipant_objects,
        team_rows, EXPORT_DIAGNOSTICS and final_raw_rows_exported or 0, #DIRECT_EXPORT_FIELDS,
        #SPECIAL_FLOAT_EXPORT_FIELDS, #TRACKER_EXPORT_FIELDS,
        #DERIVED_EXPORT_COLUMNS, VERSION, 'production_clean', PIPELINE_CAPTURE_ID, PIPELINE_CAREER_FINGERPRINT, status
    })
    log_progress('final_match_export_completed',
        'snapshot=' .. tostring(snapshot_id) ..
        ';tracker=' .. tostring(capture_id) ..
        ';participants=' .. tostring(participant_rows) ..
        ';tracker_count=' .. tostring(tracker_count) ..
        ';direct=' .. tostring(direct_bindings) ..
        ';set_difference=' .. tostring(set_difference_bindings) ..
        ';raw_rows=' .. tostring(final_raw_rows_exported) ..
        ';status=' .. status)
    return status
end

local function should_take_periodic_snapshot(current_epoch)
    if stats_snapshots >= MAX_PERIODIC_STATS_SNAPSHOTS then return false end
    if stats_snapshots == 0 then return true end
    return current_epoch - state.last_periodic_capture_epoch >=
        PERIODIC_CAPTURE_MIN_GAP_SECONDS
end

local function sample_lifecycle(trigger, phase, event_id, capture_mode)
    if not state.active or state.in_sample or
       lifecycle_samples >= MAX_LIFECYCLE_SAMPLES then return end
    state.in_sample = true
    local ok, err = pcall(function()
        lifecycle_samples = lifecycle_samples + 1
        local sample_id = lifecycle_samples
        local singleton_pointer, singleton_status = read_qword(
            'lifecycle', 'singleton_static_slot', SPECIAL.static_slot_pointer)
        singleton_pointer = singleton_pointer or 0
        local interface_pointer = 0
        local snapshot_id = ''
        local tracker_capture_id = ''
        local tracker_status = ''
        local correlation_status = ''
        local status = singleton_status
        if singleton_status == 'ok' then
            if singleton_pointer == 0 then
                status = 'singleton_null'
            elseif not is_plausible_pointer(singleton_pointer) then
                status = 'singleton_invalid'
            else
                interface_pointer = select(1, read_qword('lifecycle',
                    'singleton_plus_0xAF0',
                    singleton_pointer + SINGLETON_INTERFACE_OFFSET)) or 0
                if not is_plausible_pointer(interface_pointer) then
                    status = 'interface_invalid'
                else
                    status = 'interface_live'
                    local current_epoch = now_epoch()
                    local take_snapshot = false
                    if stats_snapshots == 0 then
                        take_snapshot = true
                    elseif capture_mode == 'forced' and
                           not state.final_stats_snapshot_captured and
                           stats_snapshots < MAX_STATS_SNAPSHOTS then
                        take_snapshot = true
                    elseif capture_mode == 'periodic' and
                           should_take_periodic_snapshot(current_epoch) then
                        take_snapshot = true
                    end
                    if take_snapshot then
                        local captured_id, capture_status = capture_stats(
                            trigger, event_id, singleton_pointer,
                            interface_pointer)
                        snapshot_id = captured_id or ''
                        status = capture_status or status
                        if capture_mode == 'forced' and captured_id then
                            state.final_stats_snapshot_captured = true
                        end
                        if capture_mode == 'periodic' then
                            state.last_periodic_capture_epoch = current_epoch
                        end
                    end
                end
            end
        end
        local special_service_trigger =
            trigger == 'startup_hub' or
            trigger == 'about_to_enter_match_pre' or
            trigger:find('late_match_candidate_event_137', 1, true) or
            trigger == 'entered_career_hub'
        local final_peek_trigger =
            trigger:find('late_match_candidate_event_137', 1, true) or
            trigger == 'entered_career_hub'
        if capture_mode == 'forced' and final_peek_trigger and
           special_service_trigger then
            -- Resolve only the three code-proven pointers and the 0x10-byte
            -- result prefix before the final wide export. The heavier service,
            -- matrix and resolver diagnostics remain after the participant
            -- export, preserving the v0.39 timing as closely as possible.
            SPECIAL.peek_current_motm(trigger)
            SPECIAL.peek_current_game_ratings(trigger)
        end
        if capture_mode == 'forced' and
           (snapshot_id ~= '' or not state.latest_tracker_capture_id) then
            local captured_tracker_id, captured_tracker_status =
                collect_tracker_snapshot(trigger)
            tracker_capture_id = captured_tracker_id or ''
            tracker_status = captured_tracker_status or ''
            if snapshot_id ~= '' and captured_tracker_id then
                local identity_status = validate_direct_identity_join(
                    tonumber(snapshot_id), captured_tracker_id, trigger)
                local export_status = export_final_match(
                    tonumber(snapshot_id), captured_tracker_id, trigger)
                correlation_status = 'direct_identity;' .. identity_status ..
                    ';player_export;' .. export_status ..
                    ';full_vectors_deferred_offline'
            elseif snapshot_id == '' then
                correlation_status =
                    'direct_identity;missing_fresh_final_snapshot'
            else
                correlation_status =
                    'direct_identity;missing_tracker_snapshot'
            end
        end
        if special_service_trigger then
            if EXPORT_DIAGNOSTICS then
                SPECIAL.capture_services(trigger, phase, event_id, snapshot_id)
            end
        end
        state.previous_singleton_live = singleton_pointer ~= 0
        state.last_status = status
        write_csv_row(lifecycle_csv, {
            sample_id, now_text(), trigger, phase or '', event_id or '',
            elapsed_seconds(), ptr_hex(SPECIAL.static_slot_pointer),
            ptr_hex(singleton_pointer), ptr_hex(interface_pointer),
            snapshot_id, tracker_capture_id, tracker_status,
            correlation_status, status
        })
    end)
    state.in_sample = false
    if not ok then
        log_error('lifecycle_sample', trigger, err)
        state.last_status = 'lifecycle_sample_exception'
    end
end

local function close_files()
    for _, file in ipairs({
        validation_csv, lifecycle_csv, interface_csv, team_blocks_csv,
        player_pointers_csv, team_values_csv, player_values_csv,
        tracker_captures_csv, tracker_players_csv, tracker_values_csv,
        surface_pairs_csv, correlation_csv, bindings_csv,
        direct_identity_csv, direct_validation_csv,
        participants_export_csv, identity_manifest_csv, teams_export_csv,
        raw_export_csv, export_summary_csv, tracker_headers_csv,
        SPECIAL.handlers_csv, SPECIAL.service_enums_csv, SPECIAL.service_snapshots_csv,
        SPECIAL.service_vtable_csv, SPECIAL.player_windows_csv,
        SPECIAL.float_values_csv, SPECIAL.service_children_csv,
        SPECIAL.service_child_vtable_csv, SPECIAL.game_ratings_vector_csv,
        SPECIAL.rating_provider_state_csv, SPECIAL.rating_team_records_csv,
        SPECIAL.rating_static_targets_csv, SPECIAL.rating_metric_matrix_csv,
        SPECIAL.rating_metric_matrix_full_csv, SPECIAL.motm_selection_csv,
        SPECIAL.rating_resolver_runtime_csv, SPECIAL.game_ratings_csv, errors_csv, progress
    }) do
        pcall(function()
            file:flush()
            file:close()
        end)
    end
end

local function stop_probe(reason)
    if not state.active then return end
    state.active = false
    log_progress('stopping', reason or '')
    if state.pre_handler and type(RemoveEventHandler) == 'function' then
        pcall(RemoveEventHandler, state.pre_handler)
    end
    if state.post_handler and type(RemoveEventHandler) == 'function' then
        pcall(RemoveEventHandler, state.post_handler)
    end
    local latest_tracker = state.latest_tracker_capture_id and
        state.tracker_snapshot_data[state.latest_tracker_capture_id] or nil
    local summary = open_unbuffered(output_dir .. '\\99_summary.txt', 'wb')
    summary:write('FC26 MatchStatsExport v', VERSION, '\r\n')
    summary:write('Output profile: production_clean\r\n')
    summary:write('Completed: ', now_text(), '\r\n')
    summary:write('Reason: ', scalar(reason), '\r\n')
    summary:write('Pipeline capture ID: ', PIPELINE_CAPTURE_ID, '\r\n')
    summary:write('Build validation: ', tostring(build_checks_matched), '/',
        tostring(build_checks_total), '\r\n')
    summary:write('Participant rows: ', tostring(final_participant_rows_exported), '\r\n')
    summary:write('Team rows: ', tostring(final_team_rows_exported), '\r\n')
    summary:write('Direct player IDs: ', tostring(direct_identity_nonzero_exported), '\r\n')
    summary:write('Match rating rows resolved: ', tostring(SPECIAL.game_rating_rows_exported), '\r\n')
    summary:write('MOTM player ID: ', SPECIAL.latest_motm_player_id and
        tostring(SPECIAL.latest_motm_player_id) or 'unresolved', '\r\n')
    summary:write('Export status: ', tostring(final_export_status), '\r\n')
    summary:write('Memory read calls: ', tostring(memory_read_calls), '/',
        tostring(MAX_MEMORY_READ_CALLS), '\r\n')
    summary:write('Errors: ', tostring(error_count), '\r\n')
    summary:write('Read-only: database writes=0; memory writes=0; game methods invoked=0\r\n')
    summary:close()

    log_progress('completed',
        'reason=' .. scalar(reason) ..
        ';snapshots=' .. tostring(stats_snapshots) ..
        ';players=' .. tostring(player_objects_exported) ..
        ';tracker_players=' .. tostring(tracker_players_exported) ..
        ';participant_rows=' .. tostring(final_participant_rows_exported) ..
        ';export_status=' .. tostring(final_export_status) ..
        ';direct_ids=' .. tostring(direct_identity_nonzero_exported) ..
        ';errors=' .. tostring(error_count))
    local participant_complete =
        final_export_status == 'complete_participant_export' or
        final_export_status == 'participant_export_complete_with_unresolved_nonparticipant'
    local marker_name = participant_complete and
        (PIPELINE_AUTOMANAGED and 'MATCH_READY' or 'READY_FOR_MANUAL_ZIP_AND_UPLOAD.txt') or
        'MATCH_INCOMPLETE'
    local marker = open_unbuffered(output_dir .. '\\' .. marker_name, 'wb')
    marker:write(participant_complete and 'Player-stats export finished.\r\n' or
        'Player-stats export is incomplete and must not be imported.\r\n')
    marker:write('Export status: ' .. tostring(final_export_status) .. '\r\n')
    marker:write('Participant rows: ' .. tostring(final_participant_rows_exported) .. '\r\n')
    marker:write('Pipeline capture ID: ' .. PIPELINE_CAPTURE_ID .. '\r\n')
    if participant_complete then
        marker:write('Use 16_match_participants_wide.csv as the canonical participant export.\r\n')
        if not PIPELINE_AUTOMANAGED then
        end
    end
    marker:write('The lifecycle monitor has stopped and removed its handlers.\r\n')
    marker:close()
    close_files()

    local final_dir = output_dir
    local publish_ok = participant_complete
    local publish_error = participant_complete and '' or
        ('incomplete_matchstats_export:' .. tostring(final_export_status))
    if participant_complete and PIPELINE_AUTOMANAGED and ready_output_dir then
        local ok, err = os.rename(output_dir, ready_output_dir)
        publish_ok = ok == true
        publish_error = publish_ok and '' or tostring(err or '')
        if publish_ok then final_dir = ready_output_dir end
    end
    rawset(_G, 'FC26_EXPORT_MATCH_STATS_LAST_EXPORT_RESULT', {
        success = publish_ok,
        ready_dir = final_dir,
        capture_id = PIPELINE_CAPTURE_ID,
        status = final_export_status,
        participant_rows = final_participant_rows_exported,
        error = publish_error
    })

    pcall(function()
        if publish_ok then
            MessageBox(
                'MatchStats export complete.\n\n' .. final_dir,
                'FC26 MatchStatsExport v' .. VERSION
            )
        else
            MessageBox(
                'MatchStats export was incomplete. Export logs were kept in:\n\n' .. final_dir ..
                '\n\nStatus: ' .. tostring(final_export_status),
                'FC26 MatchStatsExport v' .. VERSION
            )
        end
    end)
end

state.stop = stop_probe

local function on_event(phase, _, event_id, _)
    if not state.active then return end
    event_id = tonumber(event_id) or -1
    if phase == 'post' and event_id == EVENT_ABOUT_TO_ENTER_MATCH and
       not state.match_started then
        state.match_started = true
        state.match_started_epoch = now_epoch()
    end

    local should_sample = false
    local trigger = 'career_mode_event'
    local capture_mode = nil
    if phase == 'pre' and event_id == EVENT_ABOUT_TO_ENTER_MATCH then
        should_sample = true
        trigger = 'about_to_enter_match_pre'
    elseif phase == 'post' and state.match_started then
        if not state.seen_post_event_ids[event_id] then
            state.seen_post_event_ids[event_id] = true
            should_sample = true
            trigger = 'first_post_event_id'
        end
        if event_id == EVENT_RUNTIME_PULSE then
            local current_epoch = now_epoch()
            if current_epoch - state.last_runtime_sample_epoch >=
               RUNTIME_SAMPLE_MIN_GAP_SECONDS then
                state.last_runtime_sample_epoch = current_epoch
                should_sample = true
                trigger = 'periodic_runtime_pulse'
                capture_mode = 'periodic'
            end
        elseif FINAL_CANDIDATE_EVENTS[event_id] then
            should_sample = true
            trigger = 'late_match_candidate_event_' .. tostring(event_id)
            capture_mode = 'forced'
        elseif event_id == EVENT_PREPARE_FOR_SAVE then
            should_sample = true
            trigger = 'prepare_for_save'
        elseif event_id == EVENT_ENTERED_HUB then
            should_sample = true
            trigger = 'entered_career_hub'
            -- Some match types (observed especially around pre-season flows) can
            -- return to the Career Hub without emitting late candidate event 137.
            -- In that case the old exporter stopped with final_export_status still
            -- not_attempted and published an unusable package. Treat the hub return
            -- as a guarded last-chance final capture. If a prior forced capture was
            -- incomplete, allow one fresh retry while capacity remains.
            if final_export_status == 'not_attempted' or
               final_export_status == 'incomplete_participant_export' then
                if final_export_status == 'incomplete_participant_export' and
                   stats_snapshots < MAX_STATS_SNAPSHOTS then
                    state.final_stats_snapshot_captured = false
                end
                capture_mode = 'forced'
            end
        end
    end

    if should_sample then
        sample_lifecycle(trigger, phase, event_id, capture_mode)
    end
    if state.match_started and phase == 'post' and
       event_id == EVENT_ENTERED_HUB then
        stop_probe('entered_career_hub_after_match')
    end
end

sample_lifecycle('startup_hub', 'startup', nil, nil)

-- Keep registration temporaries on the persistent state table instead of declaring
-- more top-level locals. Live Editor's Lua runtime caps active locals in the main
-- chunk at 200; v0.41.2/v0.41.3 crossed that limit before either handler could arm.
state._register_ok, state._register_result = pcall(
    AddEventHandler, 'pre__CareerModeEvent',
    function(a, b, c) on_event('pre', a, b, c) end)
if state._register_ok then
    state.pre_handler = state._register_result
else
    log_error('event_registration', 'pre__CareerModeEvent', state._register_result)
    state.pre_handler = nil
end
state._register_ok, state._register_result = pcall(
    AddEventHandler, 'post__CareerModeEvent',
    function(a, b, c) on_event('post', a, b, c) end)
if state._register_ok then
    state.post_handler = state._register_result
else
    log_error('event_registration', 'post__CareerModeEvent', state._register_result)
    state.post_handler = nil
end
state._register_ok = nil
state._register_result = nil
if not state.pre_handler or not state.post_handler then
    if state.pre_handler and type(RemoveEventHandler) == 'function' then
        pcall(RemoveEventHandler, state.pre_handler)
    end
    if state.post_handler and type(RemoveEventHandler) == 'function' then
        pcall(RemoveEventHandler, state.post_handler)
    end
    state.active = false
    close_files()
    error('Could not register both CareerModeEvent handlers.')
end

log_progress('monitor_started',
    'version=' .. VERSION ..
    ';pre_handler=' .. scalar(state.pre_handler) ..
    ';post_handler=' .. scalar(state.post_handler) ..
    ';snapshot_cap=' .. tostring(MAX_STATS_SNAPSHOTS) ..
    ';player_cap_per_team=' .. tostring(MAX_PLAYERS_PER_TEAM) ..
    ';core_validation=' .. tostring(SPECIAL.core_validation_status) ..
    ';special_float_features=' .. tostring(SPECIAL.special_float_features_enabled) ..
    ';rating_features=' .. tostring(SPECIAL.rating_features_enabled) ..
    ';le_version=' .. tostring(LE_VERSION or '') ..
    ';event_payload_deref=0')

pcall(function()
    MessageBox(
        'MatchStatsExport is armed.\n\nPlay one match normally and return to the Career Hub. The completed export will be written to:\n' .. PIPELINE_ROOT .. '\\MatchStats\\ready',
        'FC26 MatchStatsExport v' .. VERSION
    )
end)

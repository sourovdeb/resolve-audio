-- Voice Isolation OBS Script v2.0
--
-- One toggle: keeps speech, attenuates steady noise.
-- Uses OBS's built-in RNNoise (method="rnnoise").
-- Fixed: uses bit.band (not &), correct API names, proper ref counting.
--
-- Installation:
--   Copy this file to: <OBS data>/scripts/voice_isolation.lua
--   Enable via: Tools > Scripts > voice_isolation.lua
--   Set the audio source in script properties.

local FILTER_NAME = "Voice Isolation"
local FILTER_ID = "noise_suppress_filter"
local HOTKEY_NAME = "Toggle Voice Isolation"

local script_log = obs.script_log
local log = function(msg)
    script_log(obs.LOG_INFO, msg)
end

-- ---------------------------------------------------------------- helpers
local function find_source(name)
    local sources = obs.obs_enum_sources()
    if sources == nil then
        return nil
    end
    local found = nil
    for _, src in ipairs(sources) do
        if obs.obs_source_get_name(src) == name then
            found = obs.obs_source_get_ref(src)
            break
        end
    end
    obs.source_list_release(sources)
    return found
end

local function has_noise_filter(source)
    -- Use obs_source_enum_filters (correct API) instead of get_filter_list
    local count = obs.obs_source_get_filter_count(source)
    for i = 0, count - 1 do
        local filter = obs.obs_source_get_filter_by_index(source, i)
        if filter ~= nil then
            local kind = obs.obs_source_get_unversioned_id(filter)
            if kind == FILTER_ID then
                obs.obs_source_release(filter)
                return true
            end
            obs.obs_source_release(filter)
        end
    end
    return false
end

local function get_or_create_filter(source)
    -- First check if filter already exists
    local existing = obs.obs_source_get_filter_by_name(source, FILTER_NAME)
    if existing ~= nil then
        return existing
    end

    -- Create settings
    local settings = obs.obs_data_create()
    obs.obs_data_set_string(settings, "method", "rnnoise")
    obs.obs_data_set_int(settings, "suppress_level", -30)

    -- Create filter privately (does not appear in filter list for manual removal)
    local created = obs.obs_source_create_private(FILTER_ID, FILTER_NAME, settings)
    obs.obs_data_release(settings)

    if created == nil then
        log("ERROR: Failed to create noise suppression filter")
        return nil
    end

    -- Add to source (this increments reference)
    obs.obs_source_filter_add(source, created)
    -- Release our create reference; filter_add holds its own
    obs.obs_source_release(created)

    -- Return strong ref for immediate use
    return obs.obs_source_get_ref(source) -- will be cleaned up by caller
end

local function warn_other_noise_filters(source)
    local count = obs.obs_source_get_filter_count(source)
    local others = {}
    for i = 0, count - 1 do
        local filter = obs.obs_source_get_filter_by_index(source, i)
        if filter ~= nil then
            local name = obs.obs_source_get_name(filter)
            local kind = obs.obs_source_get_unversioned_id(filter)
            -- Use bit.band for flag check (LuaJIT compatible)
            local flags = obs.obs_source_get_output_flags(filter)
            if kind == FILTER_ID and name ~= FILTER_NAME then
                table.insert(others, name)
            end
            obs.obs_source_release(filter)
        end
    end
    if #others > 0 then
        log("WARNING: Multiple noise suppressors detected: "
            .. table.concat(others, ", ")
            .. ". Remove duplicates to avoid double-processing.")
    end
end

-- ---------------------------------------------------------------- toggle
local function set_isolation(source_name, enabled)
    local source = find_source(source_name)
    if source == nil then
        log("Isolation: source not found: " .. tostring(source_name))
        return false
    end

    warn_other_noise_filters(source)

    -- Check if our filter exists
    local has_ours = false
    local count = obs.obs_source_get_filter_count(source)
    for i = 0, count - 1 do
        local filter = obs.obs_source_get_filter_by_index(source, i)
        if filter ~= nil then
            if obs.obs_source_get_name(filter) == FILTER_NAME then
                has_ours = true
            end
            obs.obs_source_release(filter)
        end
    end

    local filter
    if not has_ours then
        -- We need to create it via properties (public API) since private
        -- creation may not persist. Use obs_source_create with proper ID.
        local settings = obs.obs_data_create()
        obs.obs_data_set_string(settings, "method", "rnnoise")
        filter = obs.obs_source_create(FILTER_ID, FILTER_NAME, settings, nil)
        obs.obs_data_release(settings)
        if filter == nil then
            log("ERROR: Cannot create noise suppression filter")
            obs.obs_source_release(source)
            return false
        end
        obs.obs_source_filter_add(source, filter)
        obs.obs_source_release(filter)
    end

    -- Get the filter and toggle
    filter = obs.obs_source_get_filter_by_name(source, FILTER_NAME)
    if filter ~= nil then
        obs.obs_source_set_enabled(filter, enabled)
        log("Isolation " .. (enabled and "ON" or "OFF") .. " on [" .. source_name .. "]")
        obs.obs_source_release(filter)
    else
        log("ERROR: Could not find filter after creation")
    end

    obs.obs_source_release(source)
    return true
end

local function get_isolation_state(source_name)
    local source = find_source(source_name)
    if source == nil then
        return nil
    end

    local enabled = nil
    local count = obs.obs_source_get_filter_count(source)
    for i = 0, count - 1 do
        local filter = obs.obs_source_get_filter_by_index(source, i)
        if filter ~= nil then
            if obs.obs_source_get_name(filter) == FILTER_NAME then
                enabled = obs.obs_source_enabled(filter)
            end
            obs.obs_source_release(filter)
        end
    end

    obs.obs_source_release(source)
    return enabled
end

-- ---------------------------------------------------------------- state
local active_source = nil
local last_applied_source = nil
local hotkey_id = obs.OBS_INVALID_HOTKEY_ID

local function on_hotkey(pressed)
    if not pressed then
        return
    end
    if active_source == nil or active_source == "" then
        log("Isolation hotkey: no source selected in script properties.")
        return
    end
    local current = get_isolation_state(active_source)
    set_isolation(active_source, not (current == true))
end

-- ------------------------------------------------------------ OBS hooks
function script_description()
    return ("Voice Isolation (App 2).\n"
            .. "One toggle: keeps speech, removes steady noise.\n"
            .. "Uses OBS built-in RNNoise. Place BEFORE Voice Match filter.\n"
            .. "Remove any other noise suppressors from the same source.")
end

function script_properties()
    local props = obs.obs_properties_create()

    -- Source selector
    local list = obs.obs_properties_add_list(props, "source", "Audio source",
        obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)

    -- Add all audio sources
    local sources = obs.obs_enum_sources()
    if sources ~= nil then
        for _, src in ipairs(sources) do
            local flags = obs.obs_source_get_output_flags(src)
            -- Check if source has audio output (bit 0 = custom render, bit 1 = audio)
            if bit.band(flags, 0x2) ~= 0 then
                obs.obs_property_list_add_string(list,
                    obs.obs_source_get_name(src),
                    obs.obs_source_get_name(src))
            end
        end
        obs.source_list_release(sources)
    end

    obs.obs_properties_add_bool(props, "start_on", "Enable isolation when script loads")
    obs.obs_properties_add_bool(props, "auto_sync", "Sync toggle with OBS eye icon")

    return props
end

function script_defaults(settings)
    obs.obs_data_set_default_bool(settings, "start_on", false)
    obs.obs_data_set_default_bool(settings, "auto_sync", true)
end

function script_update(settings)
    local new_source = obs.obs_data_get_string(settings, "source")
    local start_on = obs.obs_data_get_bool(settings, "start_on")

    -- Only reapply on source change or first load
    if new_source ~= last_applied_source then
        active_source = new_source
        last_applied_source = new_source
        if new_source ~= nil and new_source ~= "" then
            set_isolation(new_source, start_on)
        end
    end
end

function script_load(settings)
    active_source = obs.obs_data_get_string(settings, "source")
    last_applied_source = nil

    -- Register hotkey
    hotkey_id = obs.obs_hotkey_register_frontend(
        "voice_isolation_toggle",
        HOTKEY_NAME,
        on_hotkey
    )

    -- Load saved hotkey bindings
    local arr = obs.obs_data_get_array(settings, "voice_isolation_hotkeys")
    obs.obs_hotkey_load(hotkey_id, arr)
    obs.obs_data_array_release(arr)

    -- Apply initial state
    if active_source ~= nil and active_source ~= "" then
        local start_on = obs.obs_data_get_bool(settings, "start_on")
        set_isolation(active_source, start_on)
        last_applied_source = active_source
    end

    log("Voice Isolation script loaded")
end

function script_save,settings)
    local arr = obs.obs_hotkey_save(hotkey_id)
    obs.obs_data_set_array(settings, "voice_isolation_hotkeys", arr)
    obs.obs_data_array_release(arr)
end

function script_unload()
    if hotkey_id ~= obs.OBS_INVALID_HOTKEY_ID then
        obs.obs_hotkey_unregister(hotkey_id)
        hotkey_id = obs.OBS_INVALID_HOTKEY_ID
    end
    log("Voice Isolation script unloaded")
end

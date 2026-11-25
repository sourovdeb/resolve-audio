-- Voice Isolation for OBS (App 2) — one toggle, no sliders.
--
-- What it does
--   ON:  keeps speech, turns down steady noise (fan, hum, hiss, most
--        keyboard) using OBS's built-in RNNoise suppression.
--   OFF: the microphone is untouched.
--
-- The toggle is the filter's own eye icon in the Filters window, plus a
-- hotkey ("Toggle voice isolation") and a checkbox in this script's
-- properties. Chain order with App 1: Isolation ABOVE Voice Match, and
-- nothing else that changes gain on that source.
--
-- Why a script: OBS scripts cannot process live samples (verified against
-- the scripting docs: lifecycle/properties/tick/hotkeys only). So the
-- script drives OBS's own noise-suppression filter, whose kind id
-- ("noise_suppress_filter"), method key ("method" = "rnnoise"/"speex") and
-- suppression-level key ("suppress_level") were verified in the
-- obs-studio source (plugins/obs-filters/noise-suppress-filter.c).
--
-- Lua, not Python: no maths here, no numpy needed, and Lua ships inside
-- OBS (no Python setup step).

local FILTER_NAME = "Voice Isolation (RNNoise)"

local hotkey_id = obs.OBS_INVALID_HOTKEY_ID

-- ---------------------------------------------------------------- helpers
local function log(msg)
	obs.script_log(obs.LOG_INFO, msg)
end

local function find_source(name)
	local sources = obs.obs_enum_sources()
	if sources == nil then
		return nil
	end
	local found = nil
	for _, src in ipairs(sources) do
		if obs.obs_source_get_name(src) == name then
			found = src
			break
		end
	end
	obs.source_list_release(sources)
	return found
end

local function get_or_create_filter(source)
	local existing = obs.obs_source_get_filter_by_name(source, FILTER_NAME)
	if existing ~= nil then
		return existing
	end
	local settings = obs.obs_data_create()
	obs.obs_data_set_string(settings, "method", "rnnoise")
	-- suppress_level applies to the speex method only; rnnoise has a fixed
	-- strength. Setting it is harmless and documents the intent.
	obs.obs_data_set_int(settings, "suppress_level", -30)
	local created = obs.obs_source_create_private("noise_suppress_filter",
						      FILTER_NAME, settings)
	obs.obs_data_release(settings)
	if created == nil then
		return nil
	end
	obs.obs_source_filter_add(source, created)
	obs.obs_source_release(created) -- filter_add holds its own reference
	return obs.obs_source_get_filter_by_name(source, FILTER_NAME)
end

local function warn_other_noise_filters(source)
	local others = {}
	local filters = obs.obs_source_get_filter_list(source)
	if filters ~= nil then
		for _, f in ipairs(filters) do
			local name = obs.obs_source_get_name(f)
			local kind = obs.obs_source_get_unversioned_id(f)
			if kind == "noise_suppress_filter" and name ~= FILTER_NAME then
				table.insert(others, name)
			end
		end
		obs.source_list_release(filters)
	end
	if #others > 0 then
		log("WARNING: another noise-suppression filter is already on this source: "
			.. table.concat(others, ", ")
			.. ". Two suppressors will double-process the voice. Remove the old one.")
	end
end

-- ---------------------------------------------------------------- toggle
local function set_isolation(source_name, enabled)
	local source = find_source(source_name)
	if source == nil then
		log("Isolation: source not found: " .. tostring(source_name))
		return
	end
	warn_other_noise_filters(source)
	local filter = get_or_create_filter(source)
	if filter == nil then
		log("Isolation: OBS refused to create the noise-suppression filter. "
			.. "Your OBS build may lack RNNoise; try speex by editing this script.")
		return
	end
	obs.obs_source_set_enabled(filter, enabled)
	obs.obs_source_release(filter)
	log("Isolation " .. (enabled and "ON" or "OFF") .. " on " .. source_name)
end

-- ---------------------------------------------------------------- state
-- The active source name is stored in script settings ("source") and read
-- by the hotkey callback through the module-level variable kept in sync by
-- script_update.
local active_source = nil

local function on_hotkey(pressed)
	if not pressed then
		return
	end
	if active_source == nil then
		log("Isolation hotkey: no source selected in the script properties.")
		return
	end
	local source = find_source(active_source)
	if source == nil then
		return
	end
	local filter = obs.obs_source_get_filter_by_name(source, FILTER_NAME)
	if filter == nil then
		set_isolation(active_source, true)
		return
	end
	local enabled = obs.obs_source_enabled(filter)
	obs.obs_source_release(filter)
	set_isolation(active_source, not enabled)
end

-- ------------------------------------------------------------ OBS hooks
function script_description()
	return ("Voice Isolation (App 2). One toggle: speech stays, steady "
		.. "noise goes. Uses OBS's built-in RNNoise. Put this ABOVE "
		.. "Voice Match on the source, and remove any other noise or "
		.. "dynamics filters from the same source.")
end

function script_properties()
	local props = obs.obs_properties_create()
	local list = obs.obs_properties_add_list(props, "source", "Audio source",
		obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
	local sources = obs.obs_enum_sources()
	if sources ~= nil then
		for _, src in ipairs(sources) do
			local flags = obs.obs_source_get_output_flags(src)
			if (flags & obs.OBS_SOURCE_AUDIO) ~= 0 then
				obs.obs_property_list_add_string(list,
					obs.obs_source_get_name(src),
					obs.obs_source_get_name(src))
			end
		end
		obs.source_list_release(sources)
	end
	obs.obs_properties_add_bool(props, "start_on", "Isolation ON when script loads")
	return props
end

function script_defaults(settings)
	obs.obs_data_set_default_bool(settings, "start_on", false)
end

function script_update(settings)
	active_source = obs.obs_data_get_string(settings, "source")
	if active_source ~= nil and active_source ~= "" then
		local start_on = obs.obs_data_get_bool(settings, "start_on")
		-- Only act on load-time or source change, not every settings touch:
		-- we remember what we applied to avoid re-toggling on each tick.
		if script_applied_to ~= active_source then
			script_applied_to = active_source
			set_isolation(active_source, start_on)
		end
	end
end

script_applied_to = nil

function script_load(settings)
	active_source = obs.obs_data_get_string(settings, "source")
	hotkey_id = obs.obs_hotkey_register_frontend(
		"voice_isolation_toggle", "Toggle voice isolation", on_hotkey)
	local arr = obs.obs_data_get_array(settings, "voice_isolation_toggle")
	obs.obs_hotkey_load(hotkey_id, arr)
	obs.obs_data_array_release(arr)
end

function script_save(settings)
	local arr = obs.obs_hotkey_save(hotkey_id)
	obs.obs_data_set_array(settings, "voice_isolation_toggle", arr)
	obs.obs_data_array_release(arr)
end

function script_unload()
	if hotkey_id ~= obs.OBS_INVALID_HOTKEY_ID then
		obs.obs_hotkey_unregister(hotkey_id)
	end
end

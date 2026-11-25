/* Plugin entry: registers the Voice Match audio filter. */
#include <obs-module.h>
#include <plugin-support.h>

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE(PLUGIN_NAME, "en-US")

void vm_register(void);

bool obs_module_load(void)
{
	vm_register();
	obs_log(LOG_INFO, "resolve voice-match plugin loaded (version %s)", PLUGIN_VERSION);
	return true;
}

void obs_module_unload(void)
{
	obs_log(LOG_INFO, "resolve voice-match plugin unloaded");
}

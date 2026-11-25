-- Per-user fallback launcher for Resolve's Workspace > Scripts menu.
local folder = os.getenv("LOCALAPPDATA")
local exe = folder and io.open(folder .. "\\VoiceMacro\\App\\VoiceMacro.exe", "rb")
if not exe then
    print("Run Install-VoiceMacro.cmd to install VoiceMacro on this Windows account.")
    return
end
exe:close()
os.execute('start "" "%LOCALAPPDATA%\\VoiceMacro\\App\\VoiceMacro.exe"')

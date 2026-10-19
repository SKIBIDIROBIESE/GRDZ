' c:/Users/Kacper/Desktop/skrypt/start_portal_silent.vbs
' Uruchamia serwer portalu i KeyAuth GRDZ_SNIPE w 100% niewidocznym tle (bez okna CMD)
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appDir = scriptDir & "\app"
serverScript = appDir & "\admin_server.py"

pythonPath = "python.exe"
userProfile = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
fullPyPath = userProfile & "\Programs\Python\Python312\python.exe"
If fso.FileExists(fullPyPath) Then
    pythonPath = fullPyPath
End If

WshShell.CurrentDirectory = appDir
WshShell.Run """" & pythonPath & """ """ & serverScript & """", 0, False

WScript.Sleep 1500
WshShell.Run "http://grdzsnipe.com"

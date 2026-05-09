Dim WshShell, dir, bat
Set WshShell = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
bat = dir & "launch.bat"
WshShell.Run Chr(34) & bat & Chr(34), 0, False

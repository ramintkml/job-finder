Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
bat = root & "\launch.bat"
' Wait for network after Windows login
WScript.Sleep 20000
If fso.FileExists(bat) Then
  sh.CurrentDirectory = root
  sh.Run """" & bat & """", 1, False
End If

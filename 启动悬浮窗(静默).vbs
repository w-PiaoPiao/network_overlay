' 静默启动网络悬浮窗，完全无窗口闪现
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pywPath = scriptDir & "\network_overlay.pyw"

' 尝试 pythonw.exe，如果不在 PATH 中则尝试常见安装路径
pythonwPath = "pythonw.exe"
If fso.FileExists("C:\Python313\pythonw.exe") Then
    pythonwPath = "C:\Python313\pythonw.exe"
ElseIf fso.FileExists("C:\Python312\pythonw.exe") Then
    pythonwPath = "C:\Python312\pythonw.exe"
ElseIf fso.FileExists("C:\Python311\pythonw.exe") Then
    pythonwPath = "C:\Python311\pythonw.exe"
ElseIf fso.FileExists("C:\Python310\pythonw.exe") Then
    pythonwPath = "C:\Python310\pythonw.exe"
End If

' 0 = 隐藏窗口, False = 不等待
WshShell.Run """" & pythonwPath & """ """ & pywPath & """", 0, False

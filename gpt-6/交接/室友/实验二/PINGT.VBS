Option Explicit

Dim shell, process
Set shell = CreateObject("WScript.Shell")
WScript.Echo "> ping.exe -t -w 1000 192.168.77.2"
Set process = shell.Exec("ping.exe -t -w 1000 192.168.77.2")
WScript.Sleep 6000
If process.Status = 0 Then
    process.Terminate
    WScript.Echo "[Continuous test stopped after 6 seconds.]"
End If
WScript.StdOut.Write process.StdOut.ReadAll
WScript.StdErr.Write process.StdErr.ReadAll

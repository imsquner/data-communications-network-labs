@echo off
call :lab > A:\LAN2.LOG 2>&1
echo Private LAN test finished. Log at A:\LAN2.LOG
goto :eof

:lab
@echo on
ver
date /t
time /t
netsh interface ip set address name="Local Area Connection" static 192.168.77.3 255.255.255.0 none
if errorlevel 1 goto restore
ipconfig /all
ping 192.168.77.2
ping -a -n 3 -l 56 -w 1000 192.168.77.2
cscript //nologo A:\PINGT.VBS
ping -n 3 -l 5000 -w 1500 192.168.77.2
ping -n 1 -f -l 1472 192.168.77.2
ping -n 1 -f -l 1473 192.168.77.2
netstat -a -b -n

:restore
netsh interface ip set address name="Local Area Connection" source=dhcp
if errorlevel 1 goto restore_failed
ipconfig /all
time /t
@echo off
echo LAN2_DONE
goto :eof

:restore_failed
@echo off
echo LAN2_RESTORE_FAILED
exit /b 1

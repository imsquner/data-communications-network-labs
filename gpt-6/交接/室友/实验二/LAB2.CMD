@echo off
call :lab > A:\LAB2.LOG 2>&1
if errorlevel 1 goto :eof
call A:\LAN.CMD
shutdown -s -t 5
echo Lab 2 finished. Log at A:\LAB2.LOG
goto :eof

:lab
@echo on
ver
date /t
time /t
@set "CAPTURE_NIC="
@for /f "tokens=1,* delims==" %%I in ('wmic nic where "MACAddress='00:50:56:2A:12:02'" get NetConnectionID /value') do @if /i "%%I"=="NetConnectionID" for /f "delims=" %%N in ("%%J") do @set "CAPTURE_NIC=%%N"
@if not defined CAPTURE_NIC exit /b 10
@echo CAPTURE_NIC=%CAPTURE_NIC%
ipconfig /?
ipconfig /all
ipconfig /release "%CAPTURE_NIC%"
ipconfig
ipconfig /renew "%CAPTURE_NIC%"
ipconfig /all
ipconfig /renew "%CAPTURE_NIC%"
ipconfig /all
ipconfig /release "%CAPTURE_NIC%"
ipconfig
ipconfig /renew "%CAPTURE_NIC%"
ipconfig /all
ping -n 1 192.168.37.1
ping 192.168.37.1
ping -a -n 3 -l 64 -w 1200 192.168.37.1
ping -n 3 -l 5000 -w 1500 192.168.37.1
ping -n 1 -f -l 5000 -w 1200 192.168.37.1
netstat /?
netstat -a -n
netstat -e
netstat -s
netstat -b -n
arp -a
time /t
@echo off
echo LAB2_DONE
goto :eof

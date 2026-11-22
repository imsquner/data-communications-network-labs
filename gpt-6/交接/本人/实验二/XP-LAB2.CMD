@echo off
call :lab > A:\LAB2.LOG 2>&1
echo Lab 2 finished. Log at A:\LAB2.LOG
goto :eof

:lab
@echo on
ver
date /t
time /t
ipconfig /?
ipconfig /all
ipconfig /release
ipconfig
ipconfig /renew
ipconfig /all
ipconfig /renew
ipconfig /all
ipconfig /release
ipconfig
ipconfig /renew
ipconfig /all
ping -n 1 192.168.37.1
ping 192.168.37.1
ping -a -n 3 -l 56 -w 1200 192.168.37.1
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

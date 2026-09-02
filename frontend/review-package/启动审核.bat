@echo off
cd /d "%~dp0"
start "" "http://localhost:8008/#/login"
py -m http.server 8008
pause


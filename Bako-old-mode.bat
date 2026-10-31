@echo off
rem Starts Bako in the OLD mode (BAKO_LEAN=0), to compare with the normal lean mode. Double-click this file.
rem To go back to lean mode, just start Bako.bat as usual.
set BAKO_LEAN=0
call "%~dp0Bako.bat"

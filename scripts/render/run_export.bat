@echo off
rem Sets the export_stl.py env config and forwards to the NX batch runner.
rem Usage: run_export.bat <abs .prt in> <abs .stl out> [workdir]
rem All paths resolve relative to this bat (%~dp0), so the chain moves with
rem the skill.  The wrapper exists because Git Bash `\\$var` inside double
rem quotes eats the backslash and the journal sees a literal `$n`
rem (measured 2026-09-23) - env vars must be set on the cmd side.
set "IMG_PART=%~1"
set "IMG_OUT=%~2"
if "%~3"=="" (set "RJ_WORK=%TEMP%\nx_stl_work") else set "RJ_WORK=%~3"
call "%~dp0..\run_journal_batch.bat" "%~dp0export_stl.py" "%RJ_WORK%"

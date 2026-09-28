@echo off
rem ============================================================
rem NX12 batch journal runner (verified 2026-08-05)
rem Usage: run_journal_batch.bat <journal.py> [workdir]
rem   - loads NX command env (ugiicmd.bat) then runs run_journal.exe
rem   - journal print() goes to console; exit code 0 = success
rem   - NOTE: starts a SEPARATE NX process (no GUI); cannot attach
rem     to an already-open UG session
rem ============================================================
if "%~1"=="" (
  echo Usage: run_journal_batch.bat ^<journal.py^> [workdir]
  exit /b 1
)
rem A missing workdir used to make pushd fail WITHOUT an error line, and the
rem journal then ran with the caller's CWD - os.path.abspath() in the journal
rem silently pointed at the wrong directory and artifacts landed next to the
rem invoker (measured 2026-09-22). Create it instead, and print the resolved
rem workdir unconditionally so "did pushd work" is always observable.
set "RJ_WORKDIR="
if "%~2"=="" goto :rj_run
if exist "%~2" goto :rj_push
mkdir "%~2"
:rj_push
pushd "%~2"
set "RJ_WORKDIR=%CD%"
:rj_run
echo === RUN_JOURNAL workdir=%RJ_WORKDIR% ===
rem NX install root: override with  set NX_HOME=<path>  before calling this.
rem Default is the machine this skill was developed and verified on.
if not defined NX_HOME set "NX_HOME=D:\UG-NX12"
if not exist "%NX_HOME%\NXBIN\run_journal.exe" goto :rj_no_nx
echo === RUN_JOURNAL NX_HOME=%NX_HOME% ===
call "%NX_HOME%\UGII\ugiicmd.bat" "%NX_HOME%"
"%NX_HOME%\NXBIN\run_journal.exe" "%~1"
set "RUN_JOURNAL_EXIT=%ERRORLEVEL%"
if not "%RJ_WORKDIR%"=="" popd
echo === RUN_JOURNAL_EXIT=%RUN_JOURNAL_EXIT% ===
exit /b %RUN_JOURNAL_EXIT%

:rj_no_nx
echo ERROR: run_journal.exe not found under NX_HOME=%NX_HOME%
echo Set it to your NX 12 install root, e.g.  set NX_HOME=C:\Siemens\NX12
if not "%RJ_WORKDIR%"=="" popd
exit /b 2
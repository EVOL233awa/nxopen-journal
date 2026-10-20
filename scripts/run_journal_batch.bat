@echo off
rem ============================================================
rem NX12 batch journal runner
rem Usage: run_journal_batch.bat <journal.py> [workdir]
rem   - loads NX command env (ugiicmd.bat) then runs run_journal.exe
rem   - journal print() goes to console; the exit code is NOT a verdict:
rem     only uncaught exceptions make it non-zero, so gate on output tokens
rem   - NOTE: starts a SEPARATE NX process (no GUI); cannot attach
rem     to an already-open UG session
rem ============================================================
if "%~1"=="" (
  echo Usage: run_journal_batch.bat ^<journal.py^> [workdir]
  exit /b 1
)
rem A missing workdir makes pushd fail without an error line, and the journal
rem then runs with the caller's CWD - os.path.abspath() inside the journal
rem silently points at the wrong directory. Create the directory, reject a
rem file passed as workdir, and print the resolved workdir unconditionally so
rem "did pushd work" is always observable.
set "RJ_WORKDIR="
if "%~2"=="" goto :rj_run
if exist "%~2" if not exist "%~2\" (
  echo ERROR: workdir is a file: %~2
  exit /b 2
)
if not exist "%~2" mkdir "%~2"
pushd "%~2"
if errorlevel 1 (
  echo ERROR: cannot enter workdir: %~2
  exit /b 2
)
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
@echo off
rem ============================================================
rem nxopen-journal regression suite (ASCII only - cmd parses GBK)
rem
rem Runs the 35 gated journals in dependency order. 11_api_probe.py,
rem 12_api_probe2.py and 13_api_probe3.py are one-shot API probes: they are
rem kept as evidence of how an API behaves and are not part of the gate.
rem 09 runs NX Nastran and is the slowest case, so it runs last.
rem
rem GATE: run_journal.exe propagates only UNCAUGHT
rem exceptions as a non-zero exit code, and these journals
rem deliberately catch per-stage failures and continue
rem (SKILL.md section 3). So every case is gated on a verdict
rem TOKEN in its output, not on errorlevel:
rem   PASS = expected token present AND no line contains _FAIL
rem   FAIL = token missing, or any _FAIL line present
rem NOTE: test 26 deliberately reproduces the ThreadedHole crash, which
rem makes run_journal exit 1 even though its log says "Execution was
rem successful" - that is exactly why the gate reads tokens, not codes.
rem
rem Environment:
rem   NX_HOME  NX 12 install root, used by run_journal_batch.bat.
rem            Default D:\UG-NX12 (the machine this suite was verified on);
rem            set it before calling this script on any other install.
rem   PYTHON   interpreter for the test 19 PDF value check; must have
rem            pymupdf. Defaults to the first python.exe on PATH.
rem   KEEP_PARTS=1  keep the generated artifacts under .\parts.
rem
rem After the NX cases, test 19's PDF is checked at value level by
rem verify_anno_pdf.py on the host interpreter. It needs pymupdf;
rem without it the step prints SKIP and does not gate.
rem
rem Generated artifacts land in .\parts and are deleted again at
rem the end (they are fully regenerated each run).
rem ============================================================
setlocal
set "SKILL=%~dp0..\.."
set "TESTS=%~dp0"
set "PARTS=%TESTS%parts"
if exist "%PARTS%" rmdir /s /q "%PARTS%"
if not exist "%PARTS%" mkdir "%PARTS%"

call :gate 01_bracket.py TEST01_DONE
if errorlevel 1 exit /b 1
call :gate 02_flange.py TEST02_DONE
if errorlevel 1 exit /b 1
call :gate 03_bracket_sym.py TEST03_DONE
if errorlevel 1 exit /b 1
call :gate 04_assembly.py TEST04_DONE
if errorlevel 1 exit /b 1
call :gate 05_modify_existing.py TEST05_DONE
if errorlevel 1 exit /b 1
call :gate 06_drafting.py TEST06_DONE
if errorlevel 1 exit /b 1
call :gate 07_center_marks.py TEST07_DONE
if errorlevel 1 exit /b 1
call :gate 08_editability_probe.py TEST08_DONE
if errorlevel 1 exit /b 1
call :gate 10_assembly_constraints.py CONSTRAINT_PASS
if errorlevel 1 exit /b 1
call :gate 14_block_boolean.py TEST14_DONE
if errorlevel 1 exit /b 1
call :gate 15_shell_draft.py TEST15_DONE
if errorlevel 1 exit /b 1
call :gate 16_motion_constraints.py BENCH_PASS
if errorlevel 1 exit /b 1
call :gate 17_motion_deadends.py TEST17_DONE
if errorlevel 1 exit /b 1
call :gate 18_motion_sim.py BENCH_PASS
if errorlevel 1 exit /b 1
call :gate 19_drafting_annotation.py TEST19_DONE
if errorlevel 1 exit /b 1
call :gate 20_drafting_views.py TEST20_DONE
if errorlevel 1 exit /b 1
call :gate 21_drafting_section.py TEST21_DONE
if errorlevel 1 exit /b 1
call :gate 22_modeling_extras.py TEST22_DONE
if errorlevel 1 exit /b 1
call :gate 23_motion_connectors.py TEST23_DONE
if errorlevel 1 exit /b 1
call :gate 24_shell_mesh.py TEST24_DONE
if errorlevel 1 exit /b 1
call :gate 25_shell_solve.py TEST25_DONE
if errorlevel 1 exit /b 1
call :gate 26_hole_package.py TEST26_DONE
if errorlevel 1 exit /b 1
call :gate 27_radius_dim.py TEST27_DONE
if errorlevel 1 exit /b 1
call :gate 28_pattern_helix.py TEST28_DONE
if errorlevel 1 exit /b 1
call :gate 29_interference.py TEST29_DONE
if errorlevel 1 exit /b 1
call :gate 30_fea_descriptors.py TEST30_DONE
if errorlevel 1 exit /b 1
call :gate 31_drafting_sections.py TEST31_DONE
if errorlevel 1 exit /b 1
call :gate 32_pattern_enums.py TEST32_DONE
if errorlevel 1 exit /b 1
call :gate 33_gb_sheet.py TEST33_DONE
if errorlevel 1 exit /b 1
call :gate 34_involute_gear.py TEST34_DONE
if errorlevel 1 exit /b 1
call :gate 35_assembly_preload.py TEST35_DONE
if errorlevel 1 exit /b 1
call :gate 36_motion_slider.py BENCH_PASS
if errorlevel 1 exit /b 1
call :gate 37_sketch_autodim_param.py TEST37_DONE
if errorlevel 1 exit /b 1
call :gate 38_measure.py TEST38_DONE
if errorlevel 1 exit /b 1
call :gate 09_fea_static.py BENCH_PASS
if errorlevel 1 exit /b 1

rem host-side selftest of the check_journal rules:
rem counter-examples must HIT, the clean sample must pass
call :ruleselftest
if errorlevel 1 exit /b 1

call :pdfverify
if errorlevel 1 exit /b 1

echo === ALL TESTS PASSED ===
if not "%KEEP_PARTS%"=="1" (
  rem artifacts are regenerated on every run; drop them to keep the skill small
  if exist "%PARTS%" rmdir /s /q "%PARTS%"
)
exit /b 0

rem ------------------------------------------------------------
rem :gate <journal file> <required token>
rem Runs one journal, then requires the token and rejects _FAIL.
rem ------------------------------------------------------------
:gate
set "GATE_FILE=%~1"
set "GATE_TOKEN=%~2"
set "GATE_LOG=%TESTS%_gate_%GATE_FILE%.log"
call "%SKILL%\scripts\run_journal_batch.bat" "%TESTS%%GATE_FILE%" "%PARTS%" > "%GATE_LOG%" 2>&1
findstr /C:"_FAIL" "%GATE_LOG%" >nul
if not errorlevel 1 goto :gate_fail_flag
findstr /C:"%GATE_TOKEN%" "%GATE_LOG%" >nul
if errorlevel 1 goto :gate_missing_token
del "%GATE_LOG%" >nul 2>&1
echo PASS %GATE_FILE%
exit /b 0

:gate_missing_token
echo FAIL %GATE_FILE% - missing token %GATE_TOKEN%
echo ---- output ----
type "%GATE_LOG%"
del "%GATE_LOG%" >nul 2>&1
exit /b 1

:gate_fail_flag
echo FAIL %GATE_FILE% - a _FAIL verdict was printed
echo ---- output ----
type "%GATE_LOG%"
del "%GATE_LOG%" >nul 2>&1
exit /b 1

rem ------------------------------------------------------------
rem :pdfverify - value level check of the PDF exported by test 19
rem Needs a host python with pymupdf; exit code 3 from the script
rem means pymupdf is absent, which is reported as SKIP, not FAIL.
rem NOTE: never put a bare parenthesis inside an echo string that
rem sits in an if-block - it closes the block early and the whole
rem step silently does nothing.
rem ------------------------------------------------------------
rem ------------------------------------------------------------
rem :ruleselftest - host-side selftest of the check_journal rules
rem covers 5.17 enum accessor, 5.18 cylinder enum, 5.19 UFDrf, 5.16 math.
rem Counter-examples must HIT; a clean sample must pass.
rem ------------------------------------------------------------
:ruleselftest
set "PY=%PYTHON%"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY goto :ruleselftest_no_python
echo check_journal rule selftest interpreter: %PY%
"%PY%" "%TESTS%verify_check_rules.py" > "%TESTS%_gate_rules.log" 2>&1
set "RULES_RC=%ERRORLEVEL%"
type "%TESTS%_gate_rules.log"
del "%TESTS%_gate_rules.log" >nul 2>&1
echo check_journal rule selftest rc=%RULES_RC%
if not "%RULES_RC%"=="0" goto :ruleselftest_fail
echo PASS check_journal rule selftest - counter-examples hit, clean passes
exit /b 0

:ruleselftest_no_python
echo SKIP check_journal rule selftest - no python on PATH; set PYTHON
exit /b 0

:ruleselftest_fail
echo FAIL check_journal rule selftest - verify_check_rules.py did not pass
exit /b 1

:pdfverify
set "PY=%PYTHON%"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY goto :pdfverify_no_python
echo pdf value check interpreter: %PY%
"%PY%" "%TESTS%verify_anno_pdf.py" "%PARTS%\anno19.pdf" > "%TESTS%_gate_pdf.log" 2>&1
set "PDF_RC=%ERRORLEVEL%"
type "%TESTS%_gate_pdf.log"
del "%TESTS%_gate_pdf.log" >nul 2>&1
echo pdf value check rc=%PDF_RC%
if "%PDF_RC%"=="3" goto :pdfverify_skip
if not "%PDF_RC%"=="0" goto :pdfverify_fail
echo PASS pdf value check - test 19 annotation values
exit /b 0

:pdfverify_no_python
echo SKIP pdf value check - no python on PATH; set PYTHON to a python.exe with pymupdf
exit /b 0

:pdfverify_skip
echo SKIP pdf value check - pymupdf not installed in the interpreter above
exit /b 0

:pdfverify_fail
echo FAIL pdf value check - anno19.pdf did not pass verify_anno_pdf.py
exit /b 1

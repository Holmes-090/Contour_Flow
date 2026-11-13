@echo off
rem Run the Contour Flow real-QGIS integration tests on Windows.
rem
rem Finds QGIS automatically: uses %QGIS_ROOT% if set, otherwise the newest
rem "QGIS 3.44*" folder under Program Files, otherwise the newest "QGIS 3*".
rem Uses the QGIS Python launcher (python-qgis-ltr.bat or python-qgis.bat),
rem which sets PATH, PYTHONPATH and QGIS_PREFIX_PATH for PyQGIS.
rem
rem Usage:  tests\integration\run_qgis_integration_tests.bat [--only NAME] [--fixtures-only] [--output DIR]
rem Exit code: 0 = all passed, 1 = failures, 2 = QGIS not found.

setlocal
if defined QGIS_ROOT goto have_root
for /d %%D in ("%ProgramFiles%\QGIS 3.44*") do set "QGIS_ROOT=%%~fD"
if defined QGIS_ROOT goto have_root
for /d %%D in ("%ProgramFiles%\QGIS 3*") do set "QGIS_ROOT=%%~fD"
if not defined QGIS_ROOT (
    echo QGIS not found under "%ProgramFiles%". Set QGIS_ROOT to the QGIS installation folder.
    exit /b 2
)

:have_root
set "QGIS_PY=%QGIS_ROOT%\bin\python-qgis-ltr.bat"
if not exist "%QGIS_PY%" set "QGIS_PY=%QGIS_ROOT%\bin\python-qgis.bat"
if not exist "%QGIS_PY%" (
    echo No QGIS Python launcher found in "%QGIS_ROOT%\bin".
    exit /b 2
)
echo Using QGIS at %QGIS_ROOT%
set QT_QPA_PLATFORM=offscreen
call "%QGIS_PY%" "%~dp0run_qgis_integration_tests.py" %*
exit /b %ERRORLEVEL%

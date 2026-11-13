@echo off
rem Run a Python script with QGIS's own Python (PyQGIS, GDAL available).
rem Finds QGIS like tests\integration\run_qgis_integration_tests.bat:
rem %QGIS_ROOT%, else the newest "QGIS 3.44*", else the newest "QGIS 3*" under Program Files.
rem
rem Usage:  scripts\run_with_qgis.bat path\to\script.py [arguments]

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
if not defined QT_QPA_PLATFORM set QT_QPA_PLATFORM=offscreen
call "%QGIS_PY%" %*
exit /b %ERRORLEVEL%

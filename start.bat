@echo off
rem AutoCAD MCP server launcher (stdio).
rem
rem What this is: the MCP server speaks JSON-RPC over stdin/stdout. The MCP
rem client (OpenCode, Claude Code, ...) starts this file itself and talks to
rem it through pipes. So the config points at this file:
rem
rem   "autocad": { "type": "local", "command": ["cmd", "/c", "<path>\start.bat"] }
rem
rem Running it by hand only leaves a window that waits for stdin; nothing is
rem served until a client connects. Everything this file prints goes to
rem stderr, because stdout carries the protocol and must stay clean.
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "REPO=%CD%"
set "SERVER=%REPO%\src\server.py"

if not exist "%SERVER%" (
  1>&2 echo [start.bat] server.py not found: "%SERVER%"
  exit /b 1
)

rem --- pick a Python that can import the MCP SDK ---
rem Candidates in order: AUTOCAD_MCP_PYTHON, .venv in this folder, the py
rem launcher, python on PATH. The first one that imports mcp wins, so a
rem half-built .venv does not block a working interpreter.
set "CAND="
if defined AUTOCAD_MCP_PYTHON set "CAND=%AUTOCAD_MCP_PYTHON%;"
if exist "%REPO%\.venv\Scripts\python.exe" set "CAND=%CAND%%REPO%\.venv\Scripts\python.exe;"
for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "CAND=!CAND!%%I;"
for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "CAND=!CAND!%%I;"

set "PY="
for %%C in ("%CAND:;=" "%") do (
  if not defined PY if not "%%~C"=="" (
    "%%~C" -c "import mcp" >nul 2>&1
    if not errorlevel 1 set "PY=%%~C"
  )
)
if not defined PY (
  1>&2 echo [start.bat] no Python here can import mcp. Candidates tried:
  for %%C in ("%CAND:;=" "%") do if not "%%~C"=="" 1>&2 echo [start.bat]   "%%~C"
  1>&2 echo [start.bat] install with: "%REPO%\.venv\Scripts\python.exe" -m pip install -r "%REPO%\requirements.txt"
  exit /b 1
)

"%PY%" "%SERVER%" %*
exit /b %ERRORLEVEL%

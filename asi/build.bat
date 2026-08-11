@echo off
rem Build umvc3_cssslots.asi (an ordinary x64 DLL with an .asi extension).
setlocal
set VC=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat
if not exist "%VC%" (
  echo ERROR: vcvars64.bat not found at "%VC%"
  exit /b 1
)
call "%VC%" >nul
if errorlevel 1 exit /b 1

pushd "%~dp0"
if not exist build mkdir build
cl /nologo /LD /O2 /EHsc /W4 /DNDEBUG /std:c++17 ^
   umvc3_cssslots.cpp ^
   /Fo:build\ /Fd:build\ ^
   /link /OUT:build\umvc3_cssslots.asi kernel32.lib
set RC=%errorlevel%
popd
if %RC% neq 0 ( echo BUILD FAILED & exit /b %RC% )
echo.
echo Built: %~dp0build\umvc3_cssslots.asi
exit /b 0

@echo off
REM 在仓库根目录双击或: build_catalog.cmd
REM Windows 上请用 py/python，不要用商店占位的 python3.exe
cd /d "%~dp0"
where py >nul 2>&1 && (
  py -3 "%~dp0build_catalog.py" %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>&1 && (
  python "%~dp0build_catalog.py" %*
  exit /b %ERRORLEVEL%
)
echo ERROR: 未找到 Python。请安装 Python 3 并确保 "python" 在 PATH 中。
echo 不要使用 WindowsApps\python3.exe（商店占位，不会真正执行脚本）。
exit /b 1

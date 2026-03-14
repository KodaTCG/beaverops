@echo off
echo.
echo  Building BeaverOps Agent .exe...
echo.

pip install pyinstaller websocket-client >nul 2>&1

pyinstaller --onefile --name BeaverOpsAgent --icon=beaver.ico --noconsole agent.py

echo.
echo  Done! Find your .exe at: dist\BeaverOpsAgent.exe
echo  Upload that to your GitHub releases page.
echo.
pause

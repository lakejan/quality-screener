@echo off
chcp 65001 > nul
echo ========================================================
echo   Quality Stock Screener (Streamlit UI) Starting...
echo ========================================================
cd /d "%~dp0"
"C:\Users\kyho0\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app.py --server.headless false
pause

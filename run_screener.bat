@echo off
chcp 65001 > nul
echo ========================================================
echo   🎯 한·미 퀄리티 기업 스크리너 (Streamlit UI) 실행 중...
echo ========================================================
cd /d "%~dp0"
"C:\Users\kyho0\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app.py
pause

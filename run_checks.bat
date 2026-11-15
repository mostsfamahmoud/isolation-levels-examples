@echo off
cd /d "%~dp0"
python -m pip install --quiet "psycopg[binary]" pymysql pymssql oracledb
python run_checks.py > results.txt 2>&1
type results.txt
echo.
echo Saved to results.txt
pause

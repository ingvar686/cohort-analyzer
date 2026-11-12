@echo off
cd /d "%~dp0"
echo.
echo === Altegio User Token ===
echo Enter your Altegio login and password below.
echo.
python scripts\auth_user_token.py
echo.
pause

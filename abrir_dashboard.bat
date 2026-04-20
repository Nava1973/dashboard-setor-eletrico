@echo off
title Dashboard Setor Eletrico
cd /d "%~dp0"

echo.
echo =========================================
echo  Dashboard Setor Eletrico
echo =========================================
echo.
echo [1/2] Ativando ambiente virtual...
call .\venv\Scripts\activate.bat

if errorlevel 1 (
    echo.
    echo ERRO: Nao foi possivel ativar o venv.
    echo Verifique se a pasta venv existe.
    pause
    exit /b 1
)

echo [2/2] Iniciando Streamlit em http://localhost:8501
echo.
echo Para parar o servidor, feche esta janela ou aperte Ctrl+C.
echo.

python -m streamlit run app.py

pause
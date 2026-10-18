@echo off
REM Prepara o ambiente (so na primeira vez) e inicia o ISS Pass Notifier.
REM Uso (Windows): clique duas vezes em iniciar.bat
cd /d "%~dp0"

where python >nul 2>nul || (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ ^(3.10+^) e marque "Add to PATH".
  pause & exit /b 1
)

if not exist .venv (
  echo Criando ambiente virtual ^(.venv^)...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Instalando dependencias...
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt

if not exist .env (
  copy .env.example .env >nul
  echo Arquivo .env criado. Edite SMTP_USER e SMTP_PASSWORD para enviar e-mails reais.
)

echo.
echo Abra http://127.0.0.1:8000 no navegador  ^(Ctrl+C para parar^)
echo.
python run.py
pause

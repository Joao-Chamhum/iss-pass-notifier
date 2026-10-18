#!/usr/bin/env bash
# Prepara o ambiente (só na primeira vez) e inicia o ISS Pass Notifier.
# Uso (macOS/Linux):  ./iniciar.sh
set -e
cd "$(dirname "$0")"

PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "❌ Python não encontrado. Instale em https://www.python.org/downloads/ (3.10+)."
  exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "❌ É necessário Python 3.10 ou superior. Versão atual: $("$PY" --version)"
  exit 1
}

if [ ! -d .venv ]; then
  echo "📦 Criando ambiente virtual (.venv)..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "📥 Instalando dependências..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "📝 Arquivo .env criado. Edite SMTP_USER e SMTP_PASSWORD para enviar e-mails reais."
fi

echo ""
echo "🛰️  Abra http://127.0.0.1:8000 no navegador  (Ctrl+C para parar)"
echo ""
python run.py

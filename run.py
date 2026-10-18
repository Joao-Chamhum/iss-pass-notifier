"""
Ponto de entrada da aplicação.

    python run.py                 # servidor de desenvolvimento em http://127.0.0.1:8000
    flask --app run init-db       # (opcional) cria as tabelas manualmente
    flask --app run check         # executa uma verificação de passagens agora
    flask --app run send-test-email
"""

import os

import click

from iss_tracker import create_app
from iss_tracker import notifier
from iss_tracker.scheduler import run_check

app = create_app()


@app.cli.command("check")
def check_command():
    """Executa uma rodada de verificação de passagens/notificações."""
    click.echo(run_check(app))


@app.cli.command("send-test-email")
@click.option("--to", "to_addr", default=None, help="Destinatário (padrão: NOTIFY_EMAIL).")
def send_test_email_command(to_addr):
    """Envia um e-mail de teste para validar a configuração SMTP."""
    to_addr = to_addr or app.config["NOTIFY_EMAIL"]
    notifier.send_test_email(to_addr)
    click.echo(f"E-mail de teste enviado para {to_addr}.")


if __name__ == "__main__":
    # use_reloader=False evita que o agendador rode em dois processos.
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        use_reloader=False,
    )

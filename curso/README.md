# Solução de referência do curso

`main_original.py` é o script disponibilizado no curso **100 Days of Code: The Complete Python
Pro Bootcamp** (Udemy) para o projeto *ISS Overhead Notifier*. Ele foi mantido aqui sem
alterações, como ponto de partida e registro do que foi aprendido.

O que o script faz:

1. Consulta a posição da ISS na API Open Notify (`iss-now.json`).
2. Verifica se a ISS está a até ±5° da latitude/longitude do usuário.
3. Consulta o nascer/pôr do sol na API sunrise-sunset.org para saber se é noite.
4. A cada 60 s, se as duas condições forem verdadeiras, envia o e-mail *"Look Up 👆"* via `smtplib`.

## Como essa lógica evoluiu na aplicação

| Script do curso | Aplicação (`iss_tracker/`) |
|---|---|
| Credenciais escritas no código | Lidas do `.env` (fora do Git) — `config.py` |
| Uma única localização fixa | Vários usuários salvos em SQLite — `database.py` |
| `is_iss_overhead()` / `is_night()` globais | Mesmas regras, parametrizadas e testadas — `api/iss_client.py` |
| `is_night()` comparava hora UTC com hora local | Comparação com datetimes completos em UTC |
| Só avisa quando a ISS **já está** acima | Também prevê passagens futuras (SGP4) e avisa com antecedência — `api/orbit.py` |
| Laço `while True` com `sleep(60)` | Agendador APScheduler a cada 10 min — `scheduler.py` |
| E-mail em texto puro | E-mail texto + HTML, com histórico anti-duplicidade — `notifier.py` |
| Sem interface | Dashboard web com mapa, tabela e gráficos — `templates/`, `static/` |

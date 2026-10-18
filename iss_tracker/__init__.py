"""
ISS Pass Notifier — aplicação Flask que avisa por e-mail quando a Estação
Espacial Internacional (ISS) vai passar sobre a localização do usuário.

Uso da *application factory*:

    from iss_tracker import create_app
    app = create_app()
"""

from __future__ import annotations

import logging

from flask import Flask

from .config import Config

__version__ = "1.0.0"


def create_app(config_object: type[Config] | None = None, **overrides) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    app.config.update(overrides)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from . import database
    from .routes import bp
    from .scheduler import start_scheduler

    database.init_app(app)
    app.register_blueprint(bp)
    start_scheduler(app)

    @app.context_processor
    def inject_version():
        return {"app_version": __version__}

    return app

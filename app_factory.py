"""Flask app singleton + factory. Kept tiny so :mod:`main` (and tests) can spin
up the app without worrying about route module import order.

Usage::

    from app_factory import create_app
    app = create_app()

or, when routes have already been registered elsewhere::

    from app_factory import app
"""

from flask import Flask
from flask_cors import CORS


# Module-level singleton so @app.route decorators in routes.py have something
# to attach to at import time (mirroring the original monolithic main.py).
#
# `static_url_path=''` serves everything under webroot/ at root URLs so that
# `webroot/js/scripts.js` maps to `/js/scripts.js`, `webroot/css/styles.css`
# maps to `/css/styles.css`, etc. This keeps the service-worker shell cache
# list (`/`, `/js/scripts.js`, `/css/*`) in sync with what the HTML actually
# fetches. Explicit @app.route handlers still take priority (e.g. `/`, `/sw.js`,
# `/manifest.webmanifest`, `/icons/<filename>`).
app = Flask(
    __name__,
    template_folder='webroot',
    static_folder='webroot',
    static_url_path='',
)
CORS(app)


def create_app():
    """Return the configured Flask app, ensuring routes are registered."""
    # Side-effect import: registers every @app.route on the singleton above.
    import routes  # noqa: F401
    return app

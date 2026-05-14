import os

# Worker count: 2 is right for a 1-shared-vCPU container (basic-xs).
# Override via WEB_CONCURRENCY env var if scaling up.
workers = int(os.environ.get('WEB_CONCURRENCY', 2))
worker_class = 'sync'
timeout = 60
preload_app = True

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

accesslog = '-'
errorlog = '-'
loglevel = 'info'


def post_fork(server, worker):
    """Reset the SQLAlchemy connection pool in each worker after forking.

    With preload_app=True the engine is created in the master process and
    inherited by workers via os.fork(). Without disposing, workers share
    file descriptors for the same underlying connections, which causes
    intermittent 'SSL connection has been closed unexpectedly' and
    'connection already closed' errors under concurrent load.
    """
    try:
        from wsgi import app
        with app.app_context():
            from app.extensions import db
            db.engine.dispose()
    except Exception:
        pass

import time
from app import create_app
from sqlalchemy.exc import OperationalError

app = create_app()

# Promote any SUPERADMIN_EMAILS accounts that already exist in the database.
# Migrations run before gunicorn starts (entrypoint.sh), so the schema is
# guaranteed to exist by the time this code runs.
with app.app_context():
    for attempt in range(15):
        try:
            from app.schema import ensure_runtime_schema, promote_superadmins
            ensure_runtime_schema()
            promote_superadmins()
            break
        except OperationalError:
            if attempt == 14:
                raise
            time.sleep(2)

if __name__ == '__main__':
    app.run()

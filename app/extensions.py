from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from flask_babel import Babel
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.refresh_view = 'auth.login'
login_manager.login_message_category = 'info'
login_manager.needs_refresh_message = 'Please sign in again to continue.'
login_manager.needs_refresh_message_category = 'info'
csrf = CSRFProtect()
mail = Mail()
babel = Babel()
# In-memory storage is per-worker; with 4 gunicorn workers each tracks
# independently (effective limit is N * rate). Acceptable for current scale.
# Upgrade to Redis storage if brute-force protection needs to be exact.
limiter = Limiter(key_func=get_remote_address, default_limits=[])

import warnings
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
# Storage is configured through RATELIMIT_STORAGE_URI. Local/test defaults to
# memory://; production should use Redis so limits apply across all workers.
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    limiter = Limiter(key_func=get_remote_address, default_limits=[])

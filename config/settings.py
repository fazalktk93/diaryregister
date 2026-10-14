from pathlib import Path
import os

from .instance import read_config, credential, database_config
import secrets

BASE_DIR = Path(__file__).resolve().parent.parent

def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)

INSTANCE = read_config()
SECRET_KEY = credential('DJANGO_SECRET_KEY', INSTANCE) or secrets.token_urlsafe(64)
DEBUG = env("DJANGO_DEBUG", "0") == "1"

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "diary.apps.DiaryConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "diary" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "diary.access.branding",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {'default': database_config(INSTANCE)}

# Shared by local worker processes; no extra service or database queries needed.
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'diary_data': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': BASE_DIR / '.cache' / 'diary-data',
        'TIMEOUT': 60,
        'OPTIONS': {'MAX_ENTRIES': 2000},
    },
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Karachi")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Session timeout configuration (Auto logout after 30 minutes of inactivity)
SESSION_COOKIE_AGE = 1800   # 30 minutes in seconds
SESSION_SAVE_EVERY_REQUEST = True   # reset timer on each request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Django app-level constants
DEFAULT_OFFICE_NAME = "Registry"
DEFAULT_PAGE_SIZE = 50

# Email Configuration for Password Reset
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.dummy.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env("EMAIL_USE_TLS", "True") == "True"
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "noreply@diaryregister.com")

# Password reset link validity (in seconds)
PASSWORD_RESET_TIMEOUT = 3600  # 1 hour

# Basic production hardening (safe defaults; tune as needed)
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
if not DEBUG:
    SESSION_COOKIE_SECURE = env('DJANGO_HTTPS', '0') == '1'
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SECURE_SSL_REDIRECT = SESSION_COOKIE_SECURE
    SECURE_HSTS_SECONDS = int(env('DJANGO_HSTS_SECONDS', '0'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env('DJANGO_HSTS_SUBDOMAINS', '0') == '1'
    SECURE_HSTS_PRELOAD = env('DJANGO_HSTS_PRELOAD', '0') == '1'
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    if env('DJANGO_TRUST_PROXY', '0') == '1':
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

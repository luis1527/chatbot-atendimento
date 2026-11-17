"""
Configurações do projeto Chatbot de Atendimento.

Tudo que é segredo ou muda entre ambientes vem de variáveis de ambiente
(arquivo .env em desenvolvimento, painel da Vercel em produção).
Veja .env.example.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(nome, padrao=False):
    return os.getenv(nome, str(padrao)).strip().lower() in ("1", "true", "sim", "yes", "on")


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-inseguro-troque-em-producao")
DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,.vercel.app").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "https://*.vercel.app").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # apps do projeto
    "core",      # banco de dados (modelos) + regras de negócio compartilhadas
    "bot",       # cérebro do bot: Telegram, Gemini, FAQ
    "painel",    # site dos funcionários: fila, conversas, tickets, dashboard
    "webchat",   # chat público no site ("Chat teste")
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
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco: PostgreSQL via DATABASE_URL. Sem DATABASE_URL, cai para SQLite
# (assim dá para rodar local sem instalar nada).
# A integração Neon da Vercel injeta DATABASE_URL (pooled) e também as
# variáveis legadas POSTGRES_* — aceitamos POSTGRES_URL como alternativa.
EM_PRODUCAO = bool(os.getenv("VERCEL")) or not DEBUG
_url_banco = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "").strip()
if _url_banco:
    DATABASES = {
        "default": dj_database_url.parse(
            _url_banco,
            # Serverless: sem conexão persistente (o pooler do Neon cuida disso).
            conn_max_age=0 if os.getenv("VERCEL") else 60,
            # Em produção exige SSL (sslmode=require); local não precisa.
            ssl_require=EM_PRODUCAO and not _url_banco.startswith("sqlite"),
        )
    }
    # O pooler do Neon (PgBouncer, modo transação) não suporta cursores do lado do servidor.
    if "-pooler" in _url_banco:
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {"default": dj_database_url.parse(f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

AUTH_USER_MODEL = "core.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LOGIN_URL = "painel:login"
LOGIN_REDIRECT_URL = "painel:fila"
LOGOUT_REDIRECT_URL = "painel:login"

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Serve os estáticos direto das pastas dos apps (não precisa de collectstatic,
# importante na Vercel, que é serverless).
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ---- Integrações ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "felipeprojeto_bot")
# Segredo que o Telegram manda no header de cada webhook (protege a URL).
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "troque-este-segredo")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

NOME_EMPRESA = os.getenv("NOME_EMPRESA", "Empresa Teste")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

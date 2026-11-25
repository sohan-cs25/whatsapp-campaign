"""
Settings for the local end-to-end test (e2e/run.sh). Everything lives under e2e/.data/:
a SQLite database, uploaded/processed files and a filesystem Celery broker, so the real
MySQL database and RabbitMQ are never touched. WhatsApp sends go to e2e/fake_whatsapp.py
unless E2E_REAL_WHATSAPP=1, and then only to the numbers in E2E_SEND_TO.
"""

import os

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR, config

E2E_MODE = True
DEBUG = True

E2E_DATA = os.path.join(BASE_DIR, 'e2e', '.data')

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                         'NAME': os.path.join(E2E_DATA, 'db.sqlite3'),
                         'OPTIONS': {'timeout': 30}}}

MEDIA_ROOT = os.path.join(E2E_DATA, 'media')
ORDERS_MEDIA_ROOT = os.path.join(E2E_DATA, 'orders_media')
for _sub in ('chatfile', 'processedchatfile', 'validatedchatfile'):
    os.makedirs(os.path.join(ORDERS_MEDIA_ROOT, _sub), exist_ok=True)

CELERY_BROKER_URL = 'filesystem://'
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'data_folder_in': os.path.join(E2E_DATA, 'broker'),
    'data_folder_out': os.path.join(E2E_DATA, 'broker'),
    'processed_folder': os.path.join(E2E_DATA, 'broker_processed'),
    'store_processed': False,
    'control_folder': os.path.join(E2E_DATA, 'control'),
}
for _d in ('broker', 'broker_processed', 'control', 'logs'):
    os.makedirs(os.path.join(E2E_DATA, _d), exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {'django.db.backends': {'level': 'WARNING'}},
}

# The extractor's LLM SDKs read their keys from the process environment; .env is read by decouple only.
for _key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY'):
    _val = config(_key, default='')
    if _val:
        os.environ.setdefault(_key, _val)
LLM_PROVIDER = config('LLM_PROVIDER', default=globals().get('LLM_PROVIDER') or 'anthropic')
LLM_MODEL = config('LLM_MODEL', default='') or globals().get('LLM_MODEL')

if os.getenv('E2E_REAL_WHATSAPP') == '1':
    ORDERS_SEND_ALLOWLIST = [n.strip() for n in os.getenv('E2E_SEND_TO', '').split(',') if n.strip()]
else:
    ORDERS_SEND_ALLOWLIST = None  # every send goes to the fake server

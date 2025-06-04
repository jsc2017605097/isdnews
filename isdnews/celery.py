from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'isdnews.settings')

app = Celery('isdnews')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Cấu hình Celery Beat
app.conf.beat_schedule = {
    'run-crawl-job': {
        'task': 'collector.tasks.collect_data_from_all_sources',
        'schedule': crontab(minute='*/5'),  # Chạy mỗi 5 phút
    },
    'run-openrouter-job': {
        'task': 'collector.tasks.process_openrouter_job',
        'schedule': crontab(minute='*/5'),  # Chạy mỗi 5 phút
    },
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}') 
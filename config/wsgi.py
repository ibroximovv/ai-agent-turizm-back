import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

# The pipeline queue is in-process, so anything a restart interrupted has to be
# picked up again by the new process (one gunicorn worker — see DEPLOY.md).
from apps.pipeline.recovery import resume_in_background  # noqa: E402

resume_in_background()

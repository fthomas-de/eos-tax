from celery import shared_task

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

# Create your tasks here


# Example Task
@shared_task
def update_taxes():
    pass

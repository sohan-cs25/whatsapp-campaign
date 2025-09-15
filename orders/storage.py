from django.core.files.storage import FileSystemStorage
from django.conf import settings
import os

class OrdersFileStorage(FileSystemStorage):
    """
    Custom file storage for Orders app that saves files to ORDERS_MEDIA_ROOT
    instead of the default MEDIA_ROOT
    """

    def __init__(self, location=None, base_url=None):
        if location is None:
            location = settings.ORDERS_MEDIA_ROOT
        if base_url is None:
            base_url = settings.ORDERS_MEDIA_URL
        super().__init__(location, base_url)
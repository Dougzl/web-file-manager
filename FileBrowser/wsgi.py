import os
from django.core.wsgi import get_wsgi_application
from socketio import Middleware
from app.views import sio

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FileBrowser.settings')

django_app = get_wsgi_application()
application = Middleware(sio, django_app)

import eventlet
import eventlet.wsgi

# 创建 Eventlet 服务器
eventlet.wsgi.server(eventlet.listen(('', 8008)), application)

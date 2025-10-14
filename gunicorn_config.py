import multiprocessing
import os

port = os.environ.get('PORT', '8080')
bind = f"0.0.0.0:{port}"
backlog = 2048

workers = 5
worker_class = 'sync'
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 120
keepalive = 5

accesslog = '-'
errorlog = '-'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

proc_name = 'portfolio_api'

daemon = False
pidfile = None 
umask = 0
user = None
group = None
tmp_upload_dir = None

limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

def on_starting(server):
    """Called just before the master process is initialized."""
    print(f"Starting Gunicorn server on port {port}...")
    print(f"Using {workers} workers")



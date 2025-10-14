import multiprocessing
import os

# Server socket - Railway uses PORT environment variable
port = os.environ.get('PORT', '8080')
bind = f"0.0.0.0:{port}"
backlog = 2048

# Worker processes
workers = 5
worker_class = 'sync'  # Use sync for Railway
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 120
keepalive = 5

# Logging - Railway captures stdout/stderr
accesslog = '-'
errorlog = '-'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'portfolio_api'

# Server mechanics
daemon = False
pidfile = None  # Don't use pidfile on Railway
umask = 0
user = None
group = None
tmp_upload_dir = None

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Hooks
def on_starting(server):
    """Called just before the master process is initialized."""
    print(f"Starting Gunicorn server on port {port}...")
    print(f"Using {workers} workers")


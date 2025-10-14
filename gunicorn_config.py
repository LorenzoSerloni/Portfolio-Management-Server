import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = 5
worker_class = 'gevent'  # Use gevent for async I/O
worker_connections = 1000
max_requests = 1000  # Restart workers after this many requests
max_requests_jitter = 50  # Add randomness to avoid all workers restarting at once
timeout = 120  # Worker timeout in seconds
keepalive = 5

# Logging
accesslog = 'logs/access.log'
errorlog = 'logs/error.log'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'portfolio_api'

# Server mechanics
daemon = False
pidfile = '/tmp/gunicorn.pid'
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
    print("Starting Gunicorn server...")
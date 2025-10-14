import multiprocessing

# Server socket
bind = "0.0.0.0:5000"
backlog = 2048

# Worker processes
workers = 5
worker_class = 'sync'
timeout = 120
keepalive = 5

# Logging - stdout/stderr for WSL
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Process naming
proc_name = 'portfolio_api'

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

def on_starting(server):
    print("Starting Gunicorn server...")
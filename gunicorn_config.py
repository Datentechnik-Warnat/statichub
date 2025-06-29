# Gunicorn configuration file
import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8080"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100

# Timeout settings
timeout = 300  # Increased for long-running Docker operations
keepalive = 2
graceful_timeout = 30

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Logging
loglevel = "info"
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "flask-hugo-deployer"

# Worker management
preload_app = True
worker_tmp_dir = "/dev/shm"

# SSL (if needed)
# keyfile = "/path/to/keyfile"
# certfile = "/path/to/certfile"

# Security headers (can also be handled by reverse proxy)
def when_ready(server):
    server.log.info("Server is ready. Spawning workers")

def worker_int(worker):
    worker.log.info("worker received INT or QUIT signal")

def pre_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

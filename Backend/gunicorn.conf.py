"""Gunicorn configuration.

gunicorn was already a pinned dependency but nothing ever invoked it - the app had no
production entrypoint at all. Settings live here rather than as command-line flags so the
reasoning travels with them.
"""

import multiprocessing
import os

# Bind to all interfaces: inside a container the only reachable address is the one the platform
# maps, and binding to localhost would make the service unreachable from outside the container.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Sync workers, sized from the CPU count. The app is ordinary blocking Django - no async views,
# no long-polling - so the usual (2 * cores) + 1 applies. Overridable because the formula
# assumes the container actually gets the cores it can see, which is not true on a CPU-limited
# platform plan.
workers = int(os.environ.get('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))

# NOTE this is why REDIS_URL matters (see api/checks.py, api.W001): with more than one worker,
# the default per-process cache makes every rate limit count independently per worker.

# Threads per worker. Kept >1 because several endpoints spend their time waiting on outbound
# HTTP - Microsoft Graph for email, Azure Blob for evidence upload - and a thread parked on a
# socket shouldn't occupy a whole worker.
threads = int(os.environ.get('WEB_THREADS', '4'))

# Longer than the default 30s: the candidate spreadsheet upload validates and imports up to a
# few thousand rows in one request, and evidence upload pushes photos to Azure inline. Still
# finite, so a genuinely stuck worker is recycled rather than hanging forever.
timeout = int(os.environ.get('WEB_TIMEOUT', '120'))

# Must exceed the load balancer's own idle timeout, or the balancer reuses a connection gunicorn
# has just closed and the client sees a spurious 502.
keepalive = 75

# Recycle workers periodically. This app sends email on background threads inside the worker
# process (see services/invites.py), so a slow leak there is contained rather than accumulating
# for the life of the deployment. The jitter stops all workers restarting in lockstep.
max_requests = 1000
max_requests_jitter = 100

# Logs to stdout/stderr for the platform to collect, matching the Django LOGGING config.
accesslog = '-'
errorlog = '-'
# %({x-forwarded-for}i)s is logged instead of the raw peer address because behind a proxy every
# request otherwise appears to come from the proxy. Only meaningful when the proxy is trusted -
# the same caveat as TRUST_X_FORWARDED_FOR in settings.py.
access_log_format = '%({x-forwarded-for}i)s %(m)s %(U)s %(s)s %(M)sms'
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')

# Preload the app so workers share the parsed code, and so an import-time error kills startup
# loudly instead of crash-looping each worker individually.
preload_app = True

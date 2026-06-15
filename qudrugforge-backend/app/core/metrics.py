from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Request metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total number of HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# Job metrics
ACTIVE_JOBS = Gauge(
    'active_jobs',
    'Number of currently active/running jobs'
)

QUEUE_DEPTH = Gauge(
    'queue_depth',
    'Number of jobs waiting in queue'
)

COMPLETED_JOB_COUNT = Counter(
    'completed_job_count',
    'Total number of completed jobs',
    ['job_type']
)

FAILED_JOB_COUNT = Counter(
    'failed_job_count',
    'Total number of failed jobs',
    ['job_type']
)

"""Security-bound S3 namespaces for human conflict adjudication records."""

# Production runtime and workflow roles may read these namespaces to audit a
# run, but only an operator/admin identity may create, replace, or delete their
# objects. Keep this tuple as the single source of truth for IAM generation and
# deployment audits.
RESULT_CONFLICT_RESOLUTION_ROOT = "result-conflict-resolutions"
RESULT_CONFLICT_RESOLUTION_PATH = f"{RESULT_CONFLICT_RESOLUTION_ROOT}/v1"
TERMINAL_DECISION_RESOLUTION_PATH = "terminal-decision-resolutions/v1"
HUMAN_REVIEW_RESOLUTION_PATHS = (
    RESULT_CONFLICT_RESOLUTION_PATH,
    TERMINAL_DECISION_RESOLUTION_PATH,
)

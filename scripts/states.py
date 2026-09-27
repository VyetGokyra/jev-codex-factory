# Canonical task/run states.

PENDING = "PENDING"
RUNNING = "RUNNING"
VERIFYING = "VERIFYING"
READY_TO_MERGE = "READY_TO_MERGE"
MERGED = "MERGED"

BLOCKED_RESOURCE = "BLOCKED_RESOURCE"
BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"

FAILED = "FAILED"
CONFLICTED = "CONFLICTED"
NEEDS_HUMAN = "NEEDS_HUMAN"
COMPLETED = "COMPLETED"


# Legacy compatibility.
LEGACY_BLOCKED = "BLOCKED"


BLOCKING_STATES = {
    BLOCKED_RESOURCE,
    BLOCKED_DEPENDENCY,
    NEEDS_HUMAN,
    LEGACY_BLOCKED,
}

TERMINAL_FAILURE_STATES = {
    FAILED,
    CONFLICTED,
    NEEDS_HUMAN,
    BLOCKED_RESOURCE,
    BLOCKED_DEPENDENCY,
    LEGACY_BLOCKED,
}

SUCCESS_STATES = {
    MERGED,
    COMPLETED,
}


def is_blocked(status):
    return status in BLOCKING_STATES


def is_success(status):
    return status in SUCCESS_STATES


def normalize(status):
    # Preserve old state files without breaking resume/status.
    if status == LEGACY_BLOCKED:
        return BLOCKED_RESOURCE

    return status

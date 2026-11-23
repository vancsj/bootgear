# Bound a setup command and stop its process group on timeout.
setup_with_deadline() (
    limit="$1"
    shift
    set -m
    "$@" &
    child=$!
    (
        /bin/sleep "$limit"
        kill -KILL -- "-$child" 2>/dev/null || :
    ) >/dev/null 2>&1 &
    timer=$!
    if wait "$child"; then
        status=0
    else
        status=$?
    fi
    kill -- "-$timer" 2>/dev/null || :
    wait "$timer" 2>/dev/null || :
    if [[ "$status" = 137 ]]; then
        printf '%s\n' "Setup command timed out after $limit seconds. Retry setup." >&2
        exit 124
    fi
    exit "$status"
)

class MariaDBError(Exception):
    pass


class ConfigurationFileError(Exception):
    pass


class HiveReauthRequired(Exception):
    """Raised when Cognito no longer recognizes the remembered device and a
    live SMS 2FA code is needed to recover -- a genuinely unrecoverable
    state for a headless service (see
    .agent-docs/research/hive-api-access-approach.md and ADR-0018). Kept
    distinct from apyhiveapi's own identically-named exception so callers
    (the heating-poll job's failure path, and eventually #509's
    notify_reauth_required()) depend only on this repo's own exception type,
    not an apyhiveapi implementation detail. Every other failure (network
    errors, ordinary API errors) is NOT this type, so generic job-failure
    handling treats it as an ordinary transient failure."""

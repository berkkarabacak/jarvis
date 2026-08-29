"""xAI OAuth / API constants.

Every value cites its source. Do not invent endpoints.
Sources:
  - https://github.com/ysnock404/opencode-grok-auth (src/constants.ts, src/oauth.ts)
  - https://auth.x.ai/.well-known/openid-configuration (live OIDC discovery)
  - https://hermes-agent.nousresearch.com/docs/guides/xai-grok-oauth
"""

# Public desktop OAuth client ID used by Grok CLI / Hermes / opencode-grok-auth.
# Not a secret. Source: opencode-grok-auth src/constants.ts
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"

# Source: opencode-grok-auth src/constants.ts + live OIDC discovery
XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_OAUTH_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"

# Authorize is hardcoded in working clients (not taken solely from discovery).
# Source: opencode-grok-auth src/constants.ts + oauth.ts buildXaiAuthorizeUrl
XAI_OAUTH_AUTHORIZE_URL = f"{XAI_OAUTH_ISSUER}/oauth2/authorize"

# Fallback token URL if discovery fails. Live discovery returns the same.
# Source: OIDC discovery token_endpoint
XAI_OAUTH_TOKEN_URL_FALLBACK = f"{XAI_OAUTH_ISSUER}/oauth2/token"

# Source: opencode-grok-auth src/constants.ts
XAI_OAUTH_SCOPE = "openid profile email offline_access grok-cli:access api:access"

# Borrowed client only permits localhost loopback.
# Source: opencode-grok-auth src/constants.ts
XAI_OAUTH_REDIRECT_HOST = "127.0.0.1"
XAI_OAUTH_REDIRECT_PORT = 56121
XAI_OAUTH_REDIRECT_PATH = "/callback"

# Hermes-compatible authorize extras.
# Source: opencode-grok-auth src/oauth.ts buildXaiAuthorizeUrl
XAI_OAUTH_PLAN = "generic"
XAI_OAUTH_REFERRER = "hermes-agent"

# API surface. Source: opencode-grok-auth src/constants.ts
XAI_API_BASE_URL = "https://api.x.ai/v1"
XAI_CHAT_COMPLETIONS_PATH = "/chat/completions"
XAI_API_HOST_ALLOWLIST = ("api.x.ai",)

# Refresh early margin. Brief requires 5 minutes (plugin used 2 min).
# Source: build brief §4.3 (override of plugin 120_000ms)
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 5 * 60

# Chat models available to this subscription (live GET /v1/models via OAuth, 2026-08-04).
# Image/video models omitted from the task dropdown.
DEFAULT_XAI_MODELS = (
    "grok-4.5",
    "grok-4.3",
    "grok-4.20-0309-reasoning",
    "grok-4.20-0309-non-reasoning",
    "grok-4.20-multi-agent-0309",
    "grok-build-0.1",
)

DEFAULT_MODEL = "grok-4.5"


# Twitter/X API Patterns

Reference for how `twitter_blocker/api.py` talks to X. Verified against the code in `TwitterAPI` and `HeaderEnhancer`.

## Authentication

- Cookies are read from the JSON export by `CookieManager.load_cookies()` (only `.x.com`, `.twitter.com`, `x.com`, `twitter.com` domains are kept).
- `ct0` is sent as `x-csrf-token`; `auth_token` is sent as `x-twitter-auth-token` when present.
- `twid` (format `u%3D<numeric id>`) is used only to derive the login user ID that keys the relationship cache.
  Fallbacks: an md5 prefix of `personalization_id`/`guest_id`, then `"default_user"`.
- `CookieManager` re-reads the file when its mtime changes or after `min(cache_duration, 30)` seconds, so cookies refreshed externally are picked up while the tool runs.

## Endpoints

| Constant | Endpoint |
|---|---|
| `USER_BY_SCREEN_NAME_ENDPOINT` | GraphQL `UserByScreenName` |
| `USER_BY_REST_ID_ENDPOINT` | GraphQL `UserByRestId` |
| `USERS_BY_REST_IDS_ENDPOINT` | GraphQL `UsersByRestIds` (batch lookup, 50 IDs per request by default) |
| `BLOCKS_CREATE_ENDPOINT` | REST `1.1/blocks/create.json` |

- GraphQL query IDs and the feature-flag dict (`_get_graphql_features()`) mirror what the X web client sends and change when X changes its web app.
  When lookups start failing with 4xx errors that are not auth or rate-limit related, compare both against the current web client first.
- Lookups by screen name are sequential (`_fetch_screen_names_batch` sleeps 0.1 s between requests); only user-ID lookups use the real batch endpoint.

## Extra request headers

`HeaderEnhancer` adds `x-client-transaction-id` (incrementing counter), `x-client-uuid` and `x-request-id` to GraphQL and REST requests.
`x-xp-forwarded-for` (a synthetic IP) is added only with forwarded-for enabled.
Without the enhancer, GraphQL requests send `x-client-transaction-id: 0`.

| Setting | Default | CLI flag |
|---|---|---|
| `enable_header_enhancement` | `True` | `--disable-header-enhancement` turns it off |
| `enable_forwarded_for` | `False` | `--enable-forwarded-for` turns it on (experimental) |

`HeaderEnhancer` tracks success rates over the last 10 minutes and reports `use_basic` when the quality score falls below 0.4 (after at least 20 requests).
This is advisory: `get_comprehensive_error_analysis()` surfaces it as a recommendation, and requests keep using the configured headers.

## Rate limits (429)

`_calculate_wait_time()` waits until `x-rate-limit-reset` plus 10 s, clamped to 60-900 s, and falls back to 300 s when the header is missing or unparsable.
Each request method sleeps that long and retries once.

## Auth and account-lock errors

- 401: `_handle_auth_error()` waits for the cookie file's mtime to change (first retry up to 1 hour, later retries up to 30 s), clears the cookie cache, backs off with jitter, then retries.
  After `_max_auth_retries` (10) failed retries it raises `SystemExit`.
- 403 with a "locked account" message (`_is_account_locked()`): `_handle_account_lock_error()`, same retry budget.
- 403 otherwise: classified by `ErrorClassifier` and counted; 20 accumulated 403s force a cookie reload and a 30-minute pause.
  Details are in `error-handling.md`.

## Batching and caching

- Use `get_users_info_batch(user_ids, batch_size=50)` for ID lookups and `get_users_info_by_screen_names()` for screen names; avoid looping over `get_user_info_by_id()`.
- Lookups check the three caches first (see `caching-strategy.md`); only uncached users hit the API.

# Caching Strategy

Implemented in `TwitterAPI` (`twitter_blocker/api.py`). All three caches are JSON files under `--cache-dir` (default `/data/cache`, env `CACHE_DIR`).

| Cache | Directory | Key | Content | Scope |
|---|---|---|---|---|
| Lookup | `lookups/<screen_name>.json` | screen_name | `{screen_name, user_id, cached_at}` | shared |
| Profile | `profiles/<user_id>.json` | user_id | `id`, `screen_name`, `name`, `user_status`, `protected`, `unavailable`, `cached_at` | shared |
| Relationship | `relationships/<login_user_id>/<user_id>.json` | user_id | full user dict including `following`, `followed_by`, `blocking`, `blocked_by` | per login account |

Relationship entries are separated per login account (`_get_login_user_id()`), so switching accounts does not reuse another account's follow/block flags.

## Expiry

- One TTL for all layers: `cache_ttl = 2592000` seconds (30 days), measured from the file's mtime.
- Expiry is lazy: an expired or unreadable file is deleted when it is read.
  There is no background cleanup and no size limit.
- File names are sanitized to alphanumerics, `.`, `_` and `-`.

## Read path

1. `_get_lookup_from_cache(screen_name)` gives the user ID.
2. `_combine_profile_and_relationship(user_id)` merges the profile with the relationship entry.
   It returns `None` when no profile is cached.
   When the profile exists but the relationship entry does not, all four flags default to `False`.
3. A hit returns without an API call; a miss goes to `UserByScreenName` / `UserByRestId` / `UsersByRestIds`.
   Successful API results are written to all three layers (`get_user_info`) or to profile + relationship (batch ID lookups).

`get_users_info_by_screen_names()` additionally fetches relationship data in batches for users that have a lookup entry but no usable profile entry.

## Inspecting the cache

`TwitterAPI.get_cache_stats()` returns total, valid and expired entry counts per layer, the cache directories and `cache_ttl_days`.
To clear the cache manually, delete the files under the three directories; the tool recreates them.

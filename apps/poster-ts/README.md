# poster-ts

TypeScript worker that drains the `scheduled_posts` table and posts to X via API v2.

**Status:** stub. Will be implemented in a later commit. Python workers handle ingest, scoring, story building, and draft generation; this app handles only the final post-to-X step (singles, threads, replies, QTs).

## Why TypeScript here

The X API SDK is healthier in JS/TS, and the poster is a thin wrapper around the SDK plus a queue drain loop. Keeping it separate from the Python workers lets us deploy and scale the poster independently.

## Future structure

```
src/
  index.ts          # main entry point, queue drain loop
  x_client.ts       # OAuth 1.0a user-context wrapper
  post.ts           # single / thread / reply / QT helpers
  rate_limit.ts     # token bucket
```

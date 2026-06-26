# Xdocs — API Specification

**Status:** Draft for implementation · **Date:** 2026-06-25
**Companion docs:** [Design](../design/documentation-control-design.md) · [Development Plan](./development-plan.md) · [Data Model](./data-model-and-migrations.md)

This is the contract between the front-end control and the FastAPI backend. The implementation auto-generates OpenAPI at `/openapi.json` and Swagger UI at `/docs`; this document is the human-authored source of truth that the implementation must satisfy.

---

## 1. Conventions

- **Base path:** `/api/v1`. Breaking changes bump the version prefix.
- **Format:** JSON (`application/json`); UTF-8. Timestamps are ISO-8601 UTC.
- **IDs:** UUIDv4 strings.
- **Auth:** every endpoint except `/health`, `/ready` requires `Authorization: Bearer <JWT>` (host-issued; validated via JWKS). See §3.
- **Localization:** read endpoints accept `locale` (BCP-47) and `version` (product version id/label); default to the space default + pinned default version.
- **Idempotency:** mutating admin endpoints accept an optional `Idempotency-Key` header.
- **Pagination:** cursor-based — `?limit=` (default 50, max 200) + `?cursor=`; responses include `next_cursor`.
- **Caching:** read endpoints return `ETag` + `Cache-Control`; clients should send `If-None-Match`.
- **Rate limits:** per-token buckets; `429` with `Retry-After` when exceeded (search/LLM/export/upload).

### 1.1 Error envelope
All errors share one shape:
```json
{
  "error": {
    "code": "forbidden",
    "message": "You do not have read access to this space.",
    "request_id": "01J…",
    "details": { "space": "platform" }
  }
}
```
| HTTP | `code` examples |
|---|---|
| 400 | `validation_error`, `invalid_scope` |
| 401 | `unauthorized`, `token_expired`, `invalid_signature` |
| 403 | `forbidden`, `insufficient_scope` |
| 404 | `not_found` |
| 409 | `conflict`, `revision_conflict` |
| 413 | `payload_too_large` |
| 422 | `unprocessable_entity` |
| 429 | `rate_limited`, `budget_exceeded` |
| 500/503 | `internal_error`, `dependency_unavailable` |

---

## 2. Health
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness. `{"status":"ok"}` |
| GET | `/ready` | none | Readiness (DB/Redis/storage reachable) |

---

## 3. Authentication & Authorization

- Backend validates the JWT signature against `JWKS_URL`, and checks `iss == JWT_ISSUER`, `aud == JWT_AUDIENCE`, and `exp`.
- **Required claims:** `sub` (user id), `email`, `locale` (optional), and an authorization claim — either roles (`roles: ["reader"|"editor"|"admin"]`) and/or scoped ACLs (`scopes: ["space:sql-server:read","space:platform:write"]`).
- Permission resolution: a request to a space resource requires the matching `read`/`write`/`admin` permission for that space (role-derived or explicit scope). All list/search/LLM endpoints filter results to readable spaces.
- No token-exchange endpoint in v1 (design §16.1). In dev, the test-host mock-IdP issues tokens and serves the JWKS the backend trusts.

---

## 4. Content (read)

### 4.1 List spaces
`GET /spaces?locale=&cursor=&limit=`
```json
{
  "items": [
    { "id":"…", "slug":"sql-server", "title":"SQL Server",
      "default_locale":"en", "default_version":{"id":"…","label":"2022"},
      "visible_versions":[{"id":"…","label":"2019"},{"id":"…","label":"2022"}] }
  ],
  "next_cursor": null
}
```

### 4.2 Space navigation tree
`GET /spaces/{slug}/tree?version=&locale=&depth=`
- Returns the books→pages tree for the resolved version+locale (ACL-filtered). `depth` enables lazy loading of deep subtrees.
```json
{
  "space":"sql-server","version":{"id":"…","label":"2022"},"locale":"en",
  "books":[
    { "id":"…","slug":"t-sql","title":"T-SQL Reference",
      "pages":[
        { "id":"…","slug":"select","title":"SELECT","has_children":true,
          "children":[ { "id":"…","slug":"select-into","title":"SELECT INTO" } ] }
      ] }
  ]
}
```

### 4.3 Get rendered page
`GET /pages/{id}?locale=&version=`
- Returns sanitized HTML, extracted headings (for the right TOC), metadata, and translation status. Supports `If-None-Match`.
```json
{
  "id":"…","slug":"select","title":"SELECT statement",
  "space":"sql-server","book":"t-sql","version":{"id":"…","label":"2022"},
  "locale":"en","translation_status":"approved",
  "html":"<h1 id=\"select\">SELECT…</h1>…",
  "headings":[ {"level":2,"id":"syntax","text":"Syntax"},
               {"level":3,"id":"arguments","text":"Arguments"} ],
  "updated_at":"2026-06-01T10:00:00Z",
  "prev":{"id":"…","title":"…"},"next":{"id":"…","title":"…"},
  "available_locales":["en","fr"],
  "fallback": null
}
```
- If the requested locale is missing, `fallback` describes the served source locale and offers on-the-fly translation:
```json
"fallback": { "served_locale":"en", "requested_locale":"de", "can_auto_translate": true }
```

---

## 5. Search
`GET /search?q=&scope=&locale=&version=&limit=&cursor=`
- `scope` ∈ `corpus` | `space:<slug>` | `book:<id>` | `page:<id>`. Hybrid FTS + vector with RRF fusion; ACL-filtered; grouped by page.
```json
{
  "query":"select into",
  "scope":"space:sql-server",
  "results":[
    { "page_id":"…","title":"SELECT INTO","space":"sql-server","book":"t-sql",
      "best_anchor":"creating-a-table",
      "snippet":"…use <em>SELECT INTO</em> to create…",
      "score":0.83 }
  ],
  "next_cursor": null
}
```
`GET /search/suggest?q=&scope=` → lightweight title/heading prefix suggestions (type-ahead).

---

## 6. LLM (Ask · Summarize · Extract · Translate)

### 6.1 Ask (RAG, streamed)
`POST /llm/ask` → **Server-Sent Events** (`text/event-stream`).
```json
// request
{ "question":"How do I create a table from a query?",
  "scope":"space:sql-server", "locale":"en", "version":"2022",
  "conversation_id": null }
```
SSE events:
```
event: token      data: {"text":"You can use "}
event: token      data: {"text":"SELECT INTO …"}
event: citations  data: {"items":[{"page_id":"…","anchor":"creating-a-table","title":"SELECT INTO"}]}
event: done       data: {"answer_id":"…","tokens":{"in":1820,"out":140}}
```
- If the docs don't cover the question, the model returns a grounded "not covered" answer with empty citations.
- Errors mid-stream emit `event: error  data: {error:{…}}` then close.

### 6.2 Summarize
`POST /llm/summarize`
```json
// request
{ "target": { "type":"page|selection|book", "id":"…", "text": null },
  "style":"concise|bullet|exec", "max_words": 300, "locale":"en" }
// response (ephemeral artifact)
{ "artifact_id":"…","kind":"summary","markdown":"## Summary\n…",
  "download":{ "md":"/api/v1/llm/artifacts/…/md", "pdf":"/api/v1/llm/artifacts/…/pdf" },
  "expires_at":"2026-06-25T13:00:00Z" }
```

### 6.3 Extract
`POST /llm/extract`
```json
// request
{ "instruction":"List all configuration parameters with defaults as a table",
  "scope":"book:…", "locale":"en", "format":"markdown_table|json" }
// response: same ephemeral-artifact shape as summarize
```

### 6.4 Translate (on-the-fly fallback)
`POST /llm/translate`
```json
// request
{ "page_id":"…","target_locale":"de","source_locale":"en" }
// response (ephemeral, cached per page-revision × locale)
{ "page_id":"…","target_locale":"de","html":"…","cached":true,"expires_at":"…" }
```

### 6.5 Feedback
`POST /llm/feedback`
```json
{ "answer_id":"…", "rating":"up|down", "comment": "optional" }
```
→ `204 No Content`.

> All LLM endpoints are subject to per-token rate limits and the monthly budget guard; exceeding returns `429` with `code: rate_limited` or `budget_exceeded`.

---

## 7. Export (PDF)
`POST /export`
```json
{ "scope":{ "type":"page|book|space", "id":"…" }, "locale":"en", "version":"2022",
  "options":{ "cover":true, "toc":true, "page_numbers":true } }
```
→ `202 { "job_id":"…","status":"queued" }`

`GET /export/{job_id}`
```json
{ "job_id":"…","status":"queued|rendering|done|failed",
  "url":"https://…/signed.pdf","expires_at":"…","error":null }
```

---

## 8. Media
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/media` (multipart) | editor | Upload image/file → returns `{id, url, content_type, size}`; images re-encoded; size/type validated |
| GET | `/media/{key}` | reader | Serve asset (or redirect to signed URL) |
| DELETE | `/media/{id}` | editor | Remove (if unreferenced) |

`413 payload_too_large` past the configured limit; disallowed content types → `422`.

---

## 9. Admin / CMS  *(editor/admin only)*

### 9.1 Structure CRUD
| Method | Path | Description |
|---|---|---|
| POST/PUT/DELETE | `/admin/spaces[/{id}]` | Manage spaces (slug, default locale/version, ACLs) |
| POST/PUT/DELETE | `/admin/books[/{id}]` | Manage books |
| POST/PUT/DELETE | `/admin/pages[/{id}]` | Manage pages (parent, slug, order, status) |
| POST | `/admin/{books|pages}/reorder` | Bulk reorder (`[{id, parent_id, sort_order}]`) |

### 9.2 Page content & publishing
| Method | Path | Description |
|---|---|---|
| GET/PUT | `/admin/pages/{id}/translations/{locale}` | Edit markdown for a locale (returns `revision` for optimistic lock) |
| POST | `/admin/pages/{id}/publish` | Publish draft → render + reindex + embed refresh |
| GET | `/admin/pages/{id}/revisions` | List revisions (per translation) |
| POST | `/admin/pages/{id}/revisions/{rev}/restore` | Restore a revision |

PUT translation request carries `base_revision`; mismatched → `409 revision_conflict`.

### 9.3 Versions
| Method | Path | Description |
|---|---|---|
| POST | `/admin/spaces/{id}/versions` | Create version (label, visibility, sort) |
| PUT | `/admin/versions/{id}` | Update visibility (`internal|published`) / set default |
| POST | `/admin/versions/{id}/clone` | Branch a new version from this one |

### 9.4 Translations workflow
| Method | Path | Description |
|---|---|---|
| POST | `/admin/pages/{id}/translations/{locale}/draft` | Generate LLM-assisted draft (`translation_status=llm_draft`) |
| POST | `/admin/pages/{id}/translations/{locale}/approve` | Mark `approved` |

### 9.5 Analytics (read)
| Method | Path | Description |
|---|---|---|
| GET | `/admin/analytics/pageviews?range=&space=` | Popular/most-viewed pages |
| GET | `/admin/analytics/llm-feedback?range=` | 👍/👎 aggregates + comments |

---

## 10. Eventing (front-end ↔ host)

The Web Component emits DOM `CustomEvent`s (not HTTP) the host can listen to:
| Event | `detail` | When |
|---|---|---|
| `xdocs:ready` | `{version}` | Control mounted |
| `xdocs:navigate` | `{path, page_id, space, locale, version}` | Page changed |
| `xdocs:search` | `{query, scope}` | Search performed |
| `xdocs:error` | `{code, message}` | Recoverable error surfaced |

Configuration inputs: attributes (`base-url`, `space`, `locale`, `theme`) + JS properties (`tokenProvider`, `themeTokens`).

---

## 11. Non-Functional Contract

- Read endpoints p95 < 200 ms (cached) / < 500 ms (uncached) at target scale.
- Search p95 < 600 ms. SSE first token < 2 s typical.
- All endpoints honor ACL filtering; no cross-space data leakage.
- SSE/streaming endpoints support client cancellation (close connection → abort upstream LLM call).

---

*End of API specification.*

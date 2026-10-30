# Plain-Text Normalization and HTML Sink Rule

**Status:** Accepted for PHASE-14B Batch 2 (#762).
**Scope:** Every operator, partner, and clinical free-text write boundary.

## Plain-text writes

Free text is normalized by the shared helper in
`apps/backend/app/gateway/plain_text.py` before it reaches a facade. The
normalizer:

- applies Unicode NFKC normalization,
- removes Unicode control characters (whitespace controls become word
  separators),
- removes invisible format characters that could make a blank value look
  non-empty, while keeping the Indic zero-width joiners that carry meaning,
- collapses runs of whitespace to one space and trims the ends,
- truncates to a maximum length, 500 characters by default.

It is a pure function and is idempotent. It does not change clinical meaning
beyond those normalization steps. The operator decision reason, the partner
registration fields, the directory pick source, and the care draft-rejection
reason are wired to it.

## No new HTML sink

The platform does not parse or sanitize HTML. There is no HTML parser and no
blanket sanitizer library. React's default escaping is the display rule for
every free-text value.

A new HTML sink (a raw HTML insertion point such as `dangerouslySetInnerHTML`)
may not be added. This is a standing rule for every new write, read, or display
surface.

## Existing exception

The one existing static chart path is the exception:
`apps/frontend/src/components/ui/chart.tsx` writes scoped CSS custom properties
into a `<style>` element through `dangerouslySetInnerHTML`. Its input is the
chart theme configuration and token colors authored in the application, never
free text or other untrusted input. Any new HTML sink requires a design review
and an update to this note before it may land.

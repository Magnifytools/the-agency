# Findings

- Current generation keeps a transaction-scoped coverage lock while collecting and calling Claude.
- Individual generation intentionally permits multiple versions for one coverage; only cohort rejects an existing version.
- `raw_context` is existing durable JSON and can carry operational generation identity plus a source catalog without schema changes.
- Existing item parsing strips every provider field except title and description, so assertion-level provenance needs schema and parser changes.
# Findings

- The old generator held its transaction while awaiting Anthropic and had no durable request identity.
- The existing JSON `raw_context` can hold operational generation identity without a migration; `_generation` is removed from API responses.
- Tone regeneration must re-read the source with `populate_existing=True`; `Session.get()` can otherwise reuse the pre-provider identity-map value and miss a committed concurrent edit.
- Source keys prove which collected facts were available. Section/class checks prevent basic category mismatches, but do not certify free-form interpretation.
- Recovery `404 generation_not_confirmed` is deliberately non-final: the caller may poll or safely retry the same key.

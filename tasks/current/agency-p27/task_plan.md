# P27 report recovery

1. Define generation identity, recovery DTOs and source-key validation.
2. Split collection, provider and persistence into short transactions.
3. Integrate individual, cohort and tone-regeneration routes.
4. Add PostgreSQL/API regressions for replay, concurrency, timeout, ACL and provenance.
5. Run directed baseline/final suites and commit only P27 files.
6. Recollect and compare the source snapshot after the provider returns, before persistence; reject a changed snapshot while retaining the recovery key.
7. Preserve provenance only from the prior server version, and project source catalogs by the reader's current Tasks, Projects, and Communications permissions.

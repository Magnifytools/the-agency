# Legacy init_db includes business seeds/cleanup; never invoke it on release.
web: uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8004} --timeout-keep-alive 75

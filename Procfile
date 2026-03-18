release: python -m backend.scripts.init_db
web: uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8003} --timeout-keep-alive 75

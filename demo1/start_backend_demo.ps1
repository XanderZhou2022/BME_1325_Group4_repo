$env:ICU_PG_DSN = "dbname=icu_agent_demo user=postgres password=123456 host=localhost port=5432"
$env:ICU_CORS_ORIGINS = "*"
Set-Location "system/backend/api"
uvicorn --app-dir . app.main:app --host 0.0.0.0 --port 8000

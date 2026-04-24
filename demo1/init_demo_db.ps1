$env:ICU_PG_DSN = "dbname=icu_agent_demo user=postgres password=123456 host=localhost port=5432"
python "system/backend/测试数据库/init_core_tables.py"
Write-Host "Demo database initialized."

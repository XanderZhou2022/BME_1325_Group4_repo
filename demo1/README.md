# Demo1 Auto ICU Simulation

This folder contains isolated demo run helpers and a frontend page for step-by-step ICU simulation.

## 1) Data isolation

Use a dedicated database, for example:

- DB name: `icu_agent_demo`
- Env var: `ICU_PG_DSN`

Example DSN:

`dbname=icu_agent_demo user=postgres password=123456 host=localhost port=5432`

## 2) Initialize demo database schema

From project root:

```powershell
$env:ICU_PG_DSN="dbname=icu_agent_demo user=postgres password=123456 host=localhost port=5432"
python "system/backend/测试数据库/init_core_tables.py"
```

## 3) Start backend against demo database

```powershell
cd "system/backend/api"
$env:ICU_PG_DSN="dbname=icu_agent_demo user=postgres password=123456 host=localhost port=5432"
$env:ICU_CORS_ORIGINS="*"
uvicorn --app-dir . app.main:app --host 0.0.0.0 --port 8000
```

## 4) Start main frontend and open auto demo page

```powershell
cd "system/frontend"
npm install
npm run dev
```

Open:

- `http://<host-ip>:5173/auto`

## 5) Optional CLI simulation client

```powershell
python "system/simulation/run_simulation.py" --reset --steps 10 --show-timeline
```

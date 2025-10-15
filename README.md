
## Frontend (React + Vite)

A modern React frontend lives in `job-analytics/frontend`.

### Run locally

1) Backend

```bash
cd job-analytics/backend
uvicorn main:app --reload
```

2) Frontend

```bash
cd job-analytics/frontend
npm install
npm run dev
```

Open `http://localhost:5173`. API calls are proxied to the FastAPI server on `:8000` via Vite proxy.






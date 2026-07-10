# Operational Intelligence Backend

## Local setup

Run all commands from the backend project directory:

```powershell
cd backend
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --reload
```

On macOS or Linux, create the environment file with `cp .env.example .env`.

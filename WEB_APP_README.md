# Web App Quick Reference

The canonical web app guide is now maintained at [docs/WEB_APP.md](docs/WEB_APP.md).

Quick start:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements_web.txt
.\run_app.ps1
```

The launcher deliberately uses only the project-local `.venv`. During the first
pilot, the previous matrix-oriented interface remains available with
`.\run_app.ps1 -Legacy`.

Create local API secrets in `tools/.env`; use [tools/.env.example](tools/.env.example) as the template. Do not commit real API keys or uploaded tender/bidder documents.

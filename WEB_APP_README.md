# Web App Quick Reference

The canonical web app guide is now maintained at [docs/WEB_APP.md](docs/WEB_APP.md).

Quick start:

```powershell
python -m pip install -r requirements_web.txt
streamlit run app.py
```

Create local API secrets in `tools/.env`; use [tools/.env.example](tools/.env.example) as the template. Do not commit real API keys or uploaded tender/bidder documents.

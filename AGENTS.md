# AGENTS
- **Update/Publish (1 Rutsch):** `python3 publish.py` → Feeds+Live+Shorts abrufen → DB → `data/videos.json` + `index.html`/`404.html` bauen → commit + push → GitHub Pages live (~20–60 s). Lädt Token aus `.env` (GITHUB_API_TOKEN). `--no-push` = Dry-Run. Takt: ~3×/Tag, manuell.
- Backend: server.py (FastAPI + SQLite `feed.db`, Hintergrund-Task: Feeds alle 10 Min., Live-Check alle 5 Min.)
- API: /api/videos (limit, before+before_id, q, channel, cat — Live+Shorts ausgeschlossen), /api/shorts (limit, cat), /api/live (cat), /api/channels (id,name,cat,url,count), POST /api/refresh
- Seiten: / (Alle), /ki, /robotik, /quellen — serverseitig META-Tags (server.py: META)
- Frontend: static/index.html (API- und Static-Modus, Tabs, Live-Sektion, Shorts-Box 9:16, Quellen-View, Mini-Player, "Mehr laden")
- Kanäle: channels.json — {"channels": {ki: [...], robotic: [...]}} pro Eintrag {"name": "...", "url": "https://www.youtube.com/@handle"}
- Deploy: publish.py (1 Durchlauf: refresh → data/videos.json → index.html+404.html → git commit/push), GitHub Pages: https://ogerly.github.io/ki-r-feed/
- Daten: feed.db (lokal, git-ignored, regenerierbar), data/videos.json = client-fertiger Export, .env (GITHUB_API_TOKEN, git-ignored)
- Logik/Doku/Entscheidungen in WORKING/ (Whitepaper WH-001-PUB = System-Treue)

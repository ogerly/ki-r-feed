# AGENTS
- Backend: server.py (FastAPI + SQLite `feed.db`, Hintergrund-Task: Feeds alle 10 Min., Live-Check alle 2 (mit YT_API_KEY) bzw. 5 Min.)
- API: /api/videos (limit, before+before_id, q, channel), /api/live, /api/channels, POST /api/refresh
- Frontend: static/index.html (mobile first, Mini-Player, "Mehr laden")
- Kanäle: channels.json — pro Eintrag {"name": "...", "url": "https://www.youtube.com/@handle"}
- Dokumentation/Entscheidungen in WORKING/

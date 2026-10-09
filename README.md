# KI+R Feed

**Deutscher Video-Feed für KI & Robotik.** Die neuesten Videos aus 50+ Kanälen —
chronologisch, mit Live-Bereich und Shorts. Kein Abo-Chaos. Ein Feed.

## [→ Ansehen](https://ogerly.github.io/ki-r-feed/)

## Was du bekommst
- **Alle · KI · Robotik** — Tab-Filter, eigene URLs: `/` · `/ki` · `/robotik`
- **Live-Bereich** — was gerade läuft, direkt oben
- **Shorts** — horizontale Box im 9:16-Format
- **Suche** — über Titel und Kanäle
- **Mini-Player** — Video anklicken, weiter scrollen — läuft weiter
- **Quellen** — alle Kanäle mit direktem Link: `/quellen`
- **Mobile-first** — dunkles Theme, ohne Account, ohne Tracking

## So funktioniert's
Ein lokaler Job holt mehrmals täglich die Kanäle ab (YouTube-RSS, Fallback:
Kanal-Seite), legt die Videos in SQLite und pusht den Stand als statische Seite
auf [GitHub Pages](https://pages.github.com/). Dein Browser lädt eine JSON-Datei — fertig.

## Kanäle pflegen
`channels.json` → Kategorie (`ki` / `robotic`) → `{name, url}` — dann `python3 publish.py`.
So einfach.

## Stack
FastAPI · SQLite · Vanilla JS · GitHub Pages — keine Abhängigkeiten außer drei Python-Paketen.

## Rechtliches
Persönliches Projekt ohne kommerzielle Interessen. Alle Videos sind von den
jeweiligen Kanälen **öffentlich** auf YouTube veröffentlicht — wir zeigen nur,
was öffentlich ist. Die Inhalte gehören den Kanälen.
Wer Code oder Daten für eigene Zwecke (v. a. kommerziell) nutzen will:
**selbst die Rechtslage prüfen** (YouTube-ToS, Urheberrecht, DSGVO).

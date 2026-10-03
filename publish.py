#!/usr/bin/env python3
"""1-Durchlauf-Publish: Quellen checken -> DB aktualisieren -> Static-Artefakte bauen -> GitHub pushen.

Nutzung:
  python3 publish.py            # Refresh + Export + commit/push
  python3 publish.py --no-push  # nur Refresh + Export (Dry-Run)
"""
import asyncio, json, os, re, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def load_env():
    p = BASE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()
import server  # noqa: E402  (init, run_all, SELECT, META, db)


def export():
    with server.db() as d:
        rows = [dict(r) for r in d.execute(server.SELECT + " ORDER BY v.published DESC, v.id DESC")]
        chans = [dict(r) for r in d.execute("""
            SELECT c.id, c.name, c.cat, c.url, COUNT(v.id) AS count
            FROM channels c LEFT JOIN videos v ON v.channel_id = c.id
            GROUP BY c.id ORDER BY c.cat COLLATE NOCASE, c.name COLLATE NOCASE""")]
    out = BASE / "data"
    out.mkdir(exist_ok=True)
    payload = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "videos": rows, "channels": chans}
    (out / "videos.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copyfile(BASE / "channels.json", out / "channels.json")
    return len(rows)


def build_site():
    html = (BASE / "static" / "index.html").read_text(encoding="utf-8")
    title, desc = server.META["all"]
    html = html.replace("<!--META-->",
        f"<title>{title}</title>"
        f'<meta name="description" content="{desc}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{desc}">'
        f'<meta property="og:site_name" content="KI Robotik Feed">', 1)
    (BASE / "index.html").write_text(html, encoding="utf-8")
    (BASE / "404.html").write_text(html, encoding="utf-8")


SOCIAL_URL = "https://ogerly.github.io/ki-r-feed/"


def _fmt(t, n):
    t = re.sub(r"\s+", " ", t or "").strip()
    return (t[:n] + "…") if len(t) > n else t


def _pick():
    with server.db() as d:
        live = [dict(r) for r in d.execute(server.SELECT + " WHERE v.live=1 ORDER BY v.published DESC LIMIT 1")]
        new = [dict(r) for r in d.execute(server.SELECT + " WHERE v.shorts=0 AND v.live=0 ORDER BY v.published DESC, v.id DESC LIMIT 20")]
        short = [dict(r) for r in d.execute(server.SELECT + " WHERE v.shorts=1 ORDER BY v.published DESC, v.id DESC LIMIT 1")]
    picks = []
    for cat in ("ki", "robotic"):
        picks += [v for v in new if v["cat"] == cat][:2]
    for v in new:
        if len(picks) >= 3:
            break
        if v["id"] not in {p["id"] for p in picks}:
            picks.append(v)
    return picks[:3], (live[0] if live else None), (short[0] if short else None)


def build_x(picks, live_v, short_v):
    for n in (58, 44, 30):
        post = "Neu im KI+R Feed 🇩🇪\n\n" + "\n".join(f"• {_fmt(v['title'], n)}" for v in picks)
        if live_v:
            post += f"\n🔴 LIVE: {_fmt(live_v['title'], n)} — {live_v['channel']}"
        if short_v:
            post += f"\n⚡ {_fmt(short_v['title'], n)}"
        post += f"\n#KI #Robotik #AI\n{SOCIAL_URL}"
        if len(post) <= 280:
            return post
    post = "Neu im KI+R Feed 🇩🇪\n\n" + "\n".join(f"• {_fmt(v['title'], 30)}" for v in picks[:2])
    return post + f"\n#KI #Robotik #AI\n{SOCIAL_URL}"


def build_li(picks, live_v, short_v):
    post = "Neues aus der KI- und Robotik-Welt ist online.\n\nIn den letzten Stunden neu:\n"
    post += "\n".join(f"• „{_fmt(v['title'], 90)}“ ({v['channel']})" for v in picks)
    if live_v:
        post += f"\nUnd gerade live: „{_fmt(live_v['title'], 90)}“ ({live_v['channel']})"
    if short_v:
        post += f"\nNeu als Short: „{_fmt(short_v['title'], 90)}“"
    post += f"\n\nDer Feed bündelt die neuesten Videos aus 50+ Kanälen — chronologisch, mit Live- und Shorts-Bereich.\n\n{SOCIAL_URL}\n#KünstlicheIntelligenz #Robotik #Innovation"
    return post


def build_tg(picks, live_v, short_v):
    post = "Neu im Feed 🤖\n" + "\n".join(f"• {_fmt(v['title'], 70)}" for v in picks)
    if live_v:
        post += f"\n🔴 LIVE jetzt: {_fmt(live_v['title'], 70)}"
    post += f"\n{SOCIAL_URL}\n#KI #Robotik"
    return post


def social():
    picks, live_v, short_v = _pick()
    if not picks:
        return False
    entry_id = "|".join(v["id"] for v in picks) + "|" + (live_v or {}).get("id", "")
    path = BASE / "social.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if entry_id in existing:
        return False
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = "# Social Posts\n\n_Fertige Beiträge pro Update — jeweils der neueste Stand oben. Regeln: WH-002-SOCIAL (Whitepaper)._\n"
    entry = f"\n## {ts}\n\n### X\n\n{build_x(picks, live_v, short_v)}\n\n### LinkedIn / Foren\n\n{build_li(picks, live_v, short_v)}\n\n### WhatsApp / Telegram\n\n{build_tg(picks, live_v, short_v)}\n\n---\n"
    idx = existing.find("\n## ")
    body = header + entry + (existing[idx + 1:] if idx != -1 else "")
    parts = body.split("\n## ")
    path.write_text(parts[0] + "".join("## " + p for p in parts[1:31]), encoding="utf-8")
    print(f"social.md: neuer Eintrag ({len(picks)} Videos" + (" + LIVE" if live_v else "") + (", +Short" if short_v else "") + ")")
    return True


def git(*args, quiet=False):
    r = subprocess.run(["git", *args], cwd=BASE, capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stderr.strip() or r.stdout.strip())
        if quiet:
            msg = msg.replace(os.environ.get("GITHUB_API_TOKEN", ""), "***")
        raise RuntimeError(f"git {' '.join(args)}: {msg}")
    return r.stdout.strip()


def ensure_credentials():
    token = os.environ.get("GITHUB_API_TOKEN", "")
    if not token:
        return
    r = subprocess.run(["git", "credential", "approve"], cwd=BASE,
                       input=f"protocol=https\nhost=github.com\nusername=x-access-token\npassword={token}\n\n",
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("Warnung: GITHUB_API_TOKEN konnte nicht zurueckgesetzt werden (git credential approve).")


def ensure_identity():
    missing = False
    for key in ("user.email", "user.name"):
        try:
            git("config", key)
        except RuntimeError:
            missing = True
    if missing:
        git("config", "user.email", "ki-feed@users.noreply.github.com")
        git("config", "user.name", "KI Feed")
        print("Git-Identitaet lokal gesetzt (ki-feed).")


def publish(msg):
    if not (BASE / ".git").exists():
        git("init", "-b", "main")
        print("Git-Repo initialisiert.")
    ensure_identity()
    git("add", "-A")
    if not git("status", "--porcelain"):
        print("Keine Aenderungen - nichts zu pushen.")
        return
    git("commit", "-m", msg)
    if not git("remote").strip():
        print("\nKein Remote konfiguriert. Einmalig einrichten:")
        print("  git remote add origin https://github.com/<user>/<repo>.git")
        print("  git push -u origin main")
        return
    ensure_credentials()
    git("push", "origin", "main", quiet=True)
    print("Pushed nach GitHub.")


def main():
    t0 = time.time()
    server.init()
    asyncio.run(server.run_all())
    n = export()
    build_site()
    social()
    print(f"Fertig in {time.time() - t0:.0f}s - {n} Videos exportiert.")
    if "--no-push" in sys.argv:
        print("--no-push: Git-Commit uebersprungen.")
        return
    publish(f"sync: {n} Videos, {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")


if __name__ == "__main__":
    main()

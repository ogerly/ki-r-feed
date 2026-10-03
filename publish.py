#!/usr/bin/env python3
"""1-Durchlauf-Publish: Quellen checken -> DB aktualisieren -> Static-Artefakte bauen -> GitHub pushen.

Nutzung:
  python3 publish.py            # Refresh + Export + commit/push
  python3 publish.py --no-push  # nur Refresh + Export (Dry-Run)
"""
import asyncio, json, os, shutil, subprocess, sys, time
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
    print(f"Fertig in {time.time() - t0:.0f}s - {n} Videos exportiert.")
    if "--no-push" in sys.argv:
        print("--no-push: Git-Commit uebersprungen.")
        return
    publish(f"sync: {n} Videos, {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")


if __name__ == "__main__":
    main()

import asyncio, json, os, re, sqlite3, time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
DB = BASE / "feed.db"
API_KEY = os.getenv("YT_API_KEY", "")  # optional: robustere Live-Erkennung
FEED_EVERY = 600                        # Feeds alle 10 Min.
LIVE_EVERY = 120 if API_KEY else 300    # Live-Check
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", "Accept-Language": "de-DE,de;q=0.9", "Cookie": "SOCS=CAI; CONSENT=YES+1"}
lock = asyncio.Lock()


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY, name TEXT, url TEXT UNIQUE, cat TEXT DEFAULT 'all');
        CREATE TABLE IF NOT EXISTS videos(
          id TEXT PRIMARY KEY, channel_id TEXT, title TEXT, published TEXT,
          live INTEGER DEFAULT 0, upcoming INTEGER DEFAULT 0, first_seen REAL, last_seen REAL,
          shorts INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS ix_pub ON videos(published DESC);
        CREATE INDEX IF NOT EXISTS ix_ch ON videos(channel_id);""")
        cols = [r[1] for r in c.execute("PRAGMA table_info(channels)")]
        if "cat" not in cols:
            c.execute("ALTER TABLE channels ADD COLUMN cat TEXT DEFAULT 'all'")
        vcols = [r[1] for r in c.execute("PRAGMA table_info(videos)")]
        if "shorts" not in vcols:
            c.execute("ALTER TABLE videos ADD COLUMN shorts INTEGER DEFAULT 0")


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def resolve(c, url):
    with db() as d:
        row = d.execute("SELECT id FROM channels WHERE url=?", (url,)).fetchone()
    if row:
        return row["id"]
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    cid = m.group(1) if m else None
    if not cid:
        r = await c.get(url, headers=UA, follow_redirects=True)
        m = re.search(r'"channelId":"(UC[\w-]{22})"', r.text) or re.search(r"channel_id=(UC[\w-]{22})", r.text)
        cid = m.group(1) if m else None
    return cid


def ch_name(ch):
    if ch.get("name"):
        return ch["name"]
    for k in ch:
        if k not in ("id", "url"):
            return k
    return ""


def load_channels():
    chans = json.loads((BASE / "channels.json").read_text()).get("channels", [])
    if isinstance(chans, dict):
        return [(cat, ch) for cat, lst in chans.items() for ch in lst]
    return [("all", ch) for ch in chans]


REL = re.compile(r"vor\s+(\d+)\s+(Min|Std|Tage|Tagen|Woche|Wochen|Monat|Monate|Jahr|Jahre)", re.I)
UNIT = {"min": 60, "std": 3600, "tage": 86400, "tagen": 86400,
        "woche": 604800, "wochen": 604800, "monat": 2592000, "monate": 2592000,
        "jahr": 31536000, "jahren": 31536000}


def approx_published(text, now):
    m = REL.search(text or "")
    off = int(m.group(1)) * UNIT[m.group(2).lower()] if m else 0
    return datetime.fromtimestamp(now - off, tz=timezone.utc).isoformat(timespec="seconds")


def parse_videos_page(html, now, limit=30):
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html, re.S)
    if not m:
        return []
    try:
        d = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    scope = d
    for t in (d.get("contents") or {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs") or []:
        tr = t.get("tabRenderer") or {}
        if tr.get("title") == "Videos" and "content" in tr:
            scope = tr["content"]
            break
    out, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            lv = o.get("lockupViewModel")
            if lv and (lv.get("contentType") or "").endswith("VIDEO"):
                vid = lv.get("contentId")
                if vid and vid not in seen:
                    seen.add(vid)
                    md = (lv.get("metadata") or {}).get("lockupMetadataViewModel") or {}
                    parts = []
                    for row in ((md.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows") or []:
                        parts += [(p.get("text") or {}).get("content", "") for p in row.get("metadataParts") or []]
                    pub = next((p for p in parts if re.search(r"vor\b", p, re.I)), "")
                    out.append({"id": vid, "title": (md.get("title") or {}).get("content") or "",
                                "published": approx_published(pub, now)})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(scope)
    return out[:limit]


def parse_shorts_page(html, now, limit=30):
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html, re.S)
    if not m:
        return []
    try:
        d = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    out, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            lv = o.get("shortsLockupViewModel")
            if lv:
                vid = ((lv.get("onTap") or {}).get("innertubeCommand") or {}).get("reelWatchEndpoint", {}).get("videoId")
                if not vid:
                    ent = lv.get("entityId") or ""
                    vid = ent.split("shorts-shelf-item-")[-1] if "shorts-shelf-item-" in ent else ent
                if vid and vid not in seen:
                    seen.add(vid)
                    at = lv.get("accessibilityText") or ""
                    title = re.sub(r",\s*[\d.,]+\s*(?:Aufrufe|Views)\b.*$", "", at, flags=re.I).strip() or at
                    out.append({"id": vid, "title": title,
                                "published": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds")})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(d)
    return out[:limit]


async def fetch_channel(c, ch, cat="all"):
    try:
        cid = await resolve(c, ch["url"])
        if not cid:
            print("Kanal nicht aufgelöst:", ch["url"])
            return
        name = ch_name(ch)
        now = time.time()
        vids, src = None, "rss"
        try:
            r = await c.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                name = name or root.findtext("a:author/a:name", "", NS)
                vids = [
                    {"id": e.findtext("yt:videoId", "", NS),
                     "title": e.findtext("a:title", "", NS),
                     "published": e.findtext("a:published", "", NS)}
                    for e in root.findall("a:entry", NS)
                    if e.findtext("yt:videoId", "", NS)]
        except Exception as ex:
            print("RSS-Fehler:", ch.get("url"), ex)
        if not vids:
            src = "page"
            r = await c.get(f"https://www.youtube.com/channel/{cid}/videos", headers=UA, follow_redirects=True)
            vids = parse_videos_page(r.text, now)
        if not vids:
            print("Keine Videos:", ch.get("url"), "(rss+page)")
            return
        shorts = None
        try:
            rs = await c.get(f"https://www.youtube.com/channel/{cid}/shorts", headers=UA, follow_redirects=True)
            shorts = parse_shorts_page(rs.text, now)
        except Exception:
            shorts = None
        print(f"{ch_name(ch)}: {len(vids)} Videos ({src})" + (f", {len(shorts)} Shorts" if shorts is not None else ""))
        with db() as d:
            d.execute("INSERT INTO channels(id,name,url,cat) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,url=excluded.url,cat=excluded.cat",
                      (cid, name, ch["url"], cat))
            for v in vids:
                d.execute("""INSERT INTO videos(id,channel_id,title,published,first_seen,last_seen,shorts) VALUES(?,?,?,?,?,?,0)
                  ON CONFLICT(id) DO UPDATE SET title=excluded.title,last_seen=excluded.last_seen""",
                          (v["id"], cid, v["title"], v["published"], now, now))
            for s in (shorts or []):
                d.execute("""INSERT INTO videos(id,channel_id,title,published,first_seen,last_seen,shorts) VALUES(?,?,?,?,?,?,1)
                  ON CONFLICT(id) DO UPDATE SET title=excluded.title,last_seen=excluded.last_seen,shorts=1""",
                          (s["id"], cid, s["title"], s["published"], now, now))
    except Exception as ex:
        print("Feed-Fehler:", ch.get("url"), ex)


async def refresh_feeds():
    sem = asyncio.Semaphore(10)

    async def one(c, cat, ch):
        async with sem:
            await fetch_channel(c, ch, cat)

    async with httpx.AsyncClient(timeout=15) as c:
        await asyncio.gather(*[one(c, cat, ch) for cat, ch in load_channels()])


async def live_nokey(c, cid):
    """-> (ok, video_id, title). ok=False bei Fehlern, dann Status nicht ändern."""
    try:
        r = await c.get(f"https://www.youtube.com/channel/{cid}/live", headers=UA, follow_redirects=True)
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', r.text)
        if m and '"isLive":true' in r.text:
            t = re.search(r'<meta name="title" content="([^"]*)"', r.text)
            return True, m.group(1), t.group(1) if t else ""
        return True, None, ""
    except Exception:
        return False, None, ""


async def refresh_live():
    async with httpx.AsyncClient(timeout=15) as c:
        if API_KEY:
            with db() as d:
                ids = [r["id"] for r in d.execute(
                    "SELECT id FROM videos WHERE live=1 OR upcoming=1 OR first_seen>?", (time.time() - 3 * 86400,))]
            for i in range(0, len(ids), 50):
                batch = ids[i:i + 50]
                r = await c.get("https://www.googleapis.com/youtube/v3/videos",
                                params={"part": "snippet", "id": ",".join(batch), "key": API_KEY})
                state = {it["id"]: it["snippet"].get("liveBroadcastContent") for it in r.json().get("items", [])}
                with db() as d:
                    for vid in batch:
                        st = state.get(vid)
                        d.execute("UPDATE videos SET live=?,upcoming=? WHERE id=?",
                                  (int(st == "live"), int(st == "upcoming"), vid))
        else:
            with db() as d:
                cids = [r["id"] for r in d.execute("SELECT id FROM channels")]
            sem = asyncio.Semaphore(8)

            async def chk(cid):
                async with sem:
                    return cid, await live_nokey(c, cid)

            for cid, (ok, vid, title) in await asyncio.gather(*[chk(x) for x in cids]):
                if not ok:
                    continue
                with db() as d:
                    d.execute("UPDATE videos SET live=0 WHERE channel_id=? AND live=1 AND id IS NOT ?", (cid, vid))
                    if vid:
                        d.execute("INSERT OR IGNORE INTO videos(id,channel_id,title,published,first_seen,last_seen) VALUES(?,?,?,?,?,?)",
                                  (vid, cid, title, iso_now(), time.time(), time.time()))
                        d.execute("UPDATE videos SET live=1 WHERE id=?", (vid,))


async def run_all(feeds=True):
    async with lock:
        if feeds:
            await refresh_feeds()
        await refresh_live()


async def loop():
    last = 0
    while True:
        try:
            due = time.time() - last > FEED_EVERY
            await run_all(feeds=due)
            if due:
                last = time.time()
        except Exception as ex:
            print("Update-Fehler:", ex)
        await asyncio.sleep(LIVE_EVERY)


@asynccontextmanager
async def lifespan(app):
    init()
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
SELECT = "SELECT v.id,v.title,v.published,v.live,v.upcoming,v.shorts,v.channel_id,c.name AS channel,c.cat AS cat FROM videos v JOIN channels c ON c.id=v.channel_id"


def cat_where(cat):
    return (" AND c.cat=?", [cat]) if cat else ("", [])


@app.get("/api/videos")
def videos(limit: int = 48, before: str = "", before_id: str = "", q: str = "", channel: str = "", cat: str = ""):
    limit = max(1, min(limit, 200))
    sql, p = SELECT + " WHERE v.live=0 AND v.shorts=0", []
    if before:
        sql += " AND (v.published<? OR (v.published=? AND v.id<?))"; p += [before, before, before_id]
    if q:
        sql += " AND (v.title LIKE ? OR c.name LIKE ?)"; p += [f"%{q}%"] * 2
    if channel:
        sql += " AND v.channel_id=?"; p.append(channel)
    w, pp = cat_where(cat)
    sql += w + " ORDER BY v.published DESC, v.id DESC LIMIT ?"
    with db() as d:
        rows = [dict(r) for r in d.execute(sql, p + pp + [limit + 1])]
    return {"videos": rows[:limit], "has_more": len(rows) > limit}


@app.get("/api/shorts")
def shorts(limit: int = 30, cat: str = ""):
    limit = max(1, min(limit, 60))
    w, p = cat_where(cat)
    with db() as d:
        rows = [dict(r) for r in d.execute(SELECT + " WHERE v.shorts=1" + w + " ORDER BY v.published DESC, v.id DESC LIMIT ?", p + [limit])]
    return {"videos": rows}


@app.get("/api/live")
def live(cat: str = ""):
    w, p = cat_where(cat)
    with db() as d:
        return {"videos": [dict(r) for r in d.execute(SELECT + " WHERE v.live=1" + w + " ORDER BY v.published DESC", p)]}


@app.get("/api/channels")
def channels():
    with db() as d:
        return [dict(r) for r in d.execute("""
            SELECT c.id, c.name, c.cat, c.url, COUNT(v.id) AS count
            FROM channels c LEFT JOIN videos v ON v.channel_id = c.id
            GROUP BY c.id ORDER BY c.cat COLLATE NOCASE, c.name COLLATE NOCASE""")]


@app.post("/api/refresh")
async def refresh():
    await run_all()
    return {"ok": True}


META = {
    "all": ("KI & Robotik Video Feed", "Neueste Videos aus KI- und Robotik-Kanälen auf einen Blick – chronologisch sortiert, mit Live-Bereich."),
    "ki": ("KI News – Video Feed", "Neueste Videos aus deutschen KI-Kanälen – chronologisch sortiert, mit Live-Bereich."),
    "robotic": ("Robotik News – Video Feed", "Neueste Videos aus Robotik-Kanälen – chronologisch sortiert, mit Live-Bereich."),
    "quellen": ("Quellen – KI & Robotik Feed", "Alle Kanäle des Feeds: KI & Robotik — mit Link zum YouTube-Kanal."),
}
ROUTE_PATH = {"all": "", "ki": "/ki", "robotic": "/robotik", "quellen": "/quellen"}


def page(request: Request, cat: str):
    title, desc = META.get(cat, META["all"])
    html = (BASE / "static" / "index.html").read_text()
    base = str(request.base_url).rstrip("/")
    html = html.replace("<!--META-->",
        f"<title>{title}</title>"
        f'<meta name="description" content="{desc}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{desc}">'
        f'<meta property="og:url" content="{base}{ROUTE_PATH[cat]}">'
        f'<meta property="og:site_name" content="KI Robotik Feed">', 1)
    return HTMLResponse(html)


@app.get("/")
def index(request: Request):
    return page(request, "all")


@app.get("/ki")
def ki(request: Request):
    return page(request, "ki")


@app.get("/robotik")
def robotik(request: Request):
    return page(request, "robotic")


@app.get("/quellen")
def quellen(request: Request):
    return page(request, "quellen")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

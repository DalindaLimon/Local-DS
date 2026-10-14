"""Discovery: curated starter list, search and simple "Suggested for you" ranking."""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from collections import Counter
from urllib.parse import quote

from app.config import Settings
from app.feeds import reddit_throttle
from app.urlsafe import safe_get

log = logging.getLogger(__name__)

# kind: reddit (input = subreddit name), rss (input = feed/site URL), youtube (input = channel URL/@handle)
STARTER: list[dict] = [
    # tech
    {"kind": "reddit", "input": "technology", "title": "r/technology", "topics": ["tech", "news"]},
    {"kind": "reddit", "input": "programming", "title": "r/programming", "topics": ["tech", "programming"]},
    {"kind": "reddit", "input": "linux", "title": "r/linux", "topics": ["tech", "linux"]},
    {
        "kind": "rss",
        "input": "https://hnrss.org/frontpage",
        "title": "Hacker News front page",
        "topics": ["tech", "programming", "news"],
    },
    {
        "kind": "rss",
        "input": "https://feeds.arstechnica.com/arstechnica/index",
        "title": "Ars Technica",
        "topics": ["tech", "science", "news"],
    },
    {
        "kind": "rss",
        "input": "https://www.theverge.com/rss/index.xml",
        "title": "The Verge",
        "topics": ["tech", "gadgets"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@mkbhd",
        "title": "Marques Brownlee",
        "topics": ["tech", "gadgets"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@LinusTechTips",
        "title": "Linus Tech Tips",
        "topics": ["tech", "gadgets", "pc"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@Fireship",
        "title": "Fireship",
        "topics": ["tech", "programming"],
    },
    # homelab
    {"kind": "reddit", "input": "selfhosted", "title": "r/selfhosted", "topics": ["homelab", "linux", "tech"]},
    {"kind": "reddit", "input": "homelab", "title": "r/homelab", "topics": ["homelab", "tech"]},
    {"kind": "reddit", "input": "Proxmox", "title": "r/Proxmox", "topics": ["homelab", "linux"]},
    {"kind": "reddit", "input": "homeassistant", "title": "r/homeassistant", "topics": ["homelab", "smarthome"]},
    {"kind": "reddit", "input": "LocalLLaMA", "title": "r/LocalLLaMA", "topics": ["homelab", "ai", "tech"]},
    {"kind": "reddit", "input": "3Dprinting", "title": "r/3Dprinting", "topics": ["3dprinting", "maker"]},
    {"kind": "reddit", "input": "openwrt", "title": "r/openwrt", "topics": ["homelab", "networking"]},
    {"kind": "reddit", "input": "cachyos", "title": "r/cachyos", "topics": ["linux", "pc"]},
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@TechnoTim",
        "title": "Techno Tim",
        "topics": ["homelab", "linux"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@JeffGeerling",
        "title": "Jeff Geerling",
        "topics": ["homelab", "maker", "tech"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@CraftComputing",
        "title": "Craft Computing",
        "topics": ["homelab", "pc"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@ServeTheHomeVideo",
        "title": "ServeTheHome",
        "topics": ["homelab", "networking"],
    },
    {"kind": "rss", "input": "https://selfh.st/rss/", "title": "selfh.st", "topics": ["homelab"]},
    # gaming / pc
    {"kind": "reddit", "input": "pcmasterrace", "title": "r/pcmasterrace", "topics": ["pc", "gaming", "humor"]},
    {"kind": "reddit", "input": "linux_gaming", "title": "r/linux_gaming", "topics": ["gaming", "linux"]},
    {"kind": "reddit", "input": "buildapc", "title": "r/buildapc", "topics": ["pc", "gaming"]},
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@GamersNexus",
        "title": "Gamers Nexus",
        "topics": ["pc", "gaming", "tech"],
    },
    # science
    {"kind": "reddit", "input": "science", "title": "r/science", "topics": ["science"]},
    {"kind": "reddit", "input": "space", "title": "r/space", "topics": ["science", "space"]},
    {"kind": "reddit", "input": "EngineeringPorn", "title": "r/EngineeringPorn", "topics": ["science", "maker"]},
    {"kind": "rss", "input": "https://www.quantamagazine.org/feed/", "title": "Quanta Magazine", "topics": ["science"]},
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@veritasium",
        "title": "Veritasium",
        "topics": ["science", "education"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@kurzgesagt",
        "title": "Kurzgesagt",
        "topics": ["science", "education"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@smartereveryday",
        "title": "SmarterEveryDay",
        "topics": ["science", "maker"],
    },
    # maker / diy
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@StuffMadeHere",
        "title": "Stuff Made Here",
        "topics": ["maker", "3dprinting"],
    },
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@CNCKitchen",
        "title": "CNC Kitchen",
        "topics": ["3dprinting", "maker"],
    },
    {"kind": "reddit", "input": "functionalprint", "title": "r/functionalprint", "topics": ["3dprinting", "maker"]},
    # humor
    {"kind": "reddit", "input": "ProgrammerHumor", "title": "r/ProgrammerHumor", "topics": ["humor", "programming"]},
    {"kind": "reddit", "input": "funny", "title": "r/funny", "topics": ["humor"]},
    {"kind": "reddit", "input": "mildlyinteresting", "title": "r/mildlyinteresting", "topics": ["humor", "misc"]},
    {"kind": "rss", "input": "https://xkcd.com/atom.xml", "title": "xkcd", "topics": ["humor", "science"]},
    # news
    {"kind": "reddit", "input": "worldnews", "title": "r/worldnews", "topics": ["news"]},
    {"kind": "rss", "input": "https://feeds.bbci.co.uk/news/world/rss.xml", "title": "BBC World", "topics": ["news"]},
    {
        "kind": "rss",
        "input": "https://www.theguardian.com/world/rss",
        "title": "The Guardian World",
        "topics": ["news"],
    },
    # cooking / lifestyle
    {"kind": "reddit", "input": "Cooking", "title": "r/Cooking", "topics": ["food"]},
    {
        "kind": "youtube",
        "input": "https://www.youtube.com/@JoshuaWeissman",
        "title": "Joshua Weissman",
        "topics": ["food"],
    },
]

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "tech": ["tech", "gadget", "software", "hardware", "computer", "apple", "android", "google"],
    "programming": ["programming", "code", "coding", "developer", "python", "javascript", "rust", "golang", "dev"],
    "linux": ["linux", "kde", "gnome", "arch", "debian", "ubuntu", "fedora", "cachy", "kernel", "distro"],
    "homelab": ["homelab", "selfhost", "self-host", "proxmox", "docker", "server", "nas", "unraid", "truenas", "lxc"],
    "networking": ["network", "router", "openwrt", "wifi", "switch", "vlan", "firewall", "pfsense", "opnsense"],
    "smarthome": ["home assistant", "homeassistant", "zigbee", "smart home", "camera", "frigate", "tapo"],
    "ai": ["ai", "llm", "llama", "gpt", "machine learning", "neural", "ollama", "model"],
    "pc": ["pc", "gpu", "cpu", "nvidia", "amd", "intel", "ryzen", "rtx", "build"],
    "gaming": ["game", "gaming", "steam", "console", "playstation", "xbox", "nintendo"],
    "science": ["science", "physics", "biology", "chemistry", "research", "math"],
    "space": ["space", "nasa", "rocket", "spacex", "astronomy", "planet"],
    "maker": ["maker", "diy", "build", "engineering", "cnc", "electronics", "arduino"],
    "3dprinting": ["3d print", "3dprint", "printer", "filament", "bambu", "prusa", "qidi", "klipper"],
    "humor": ["funny", "humor", "meme", "joke", "comedy"],
    "news": ["news", "world", "politics", "breaking"],
    "food": ["food", "cooking", "recipe", "kitchen", "chef"],
    "education": ["explained", "learn", "education", "history"],
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def guess_topics(*texts: str) -> list[str]:
    blob = " ".join(t.lower() for t in texts if t)
    found = []
    for topic, words in TOPIC_KEYWORDS.items():
        for w in words:
            if (" " in w and w in blob) or (" " not in w and re.search(rf"\b{re.escape(w)}", blob)):
                found.append(topic)
                break
    return found


def starter_topics_for(kind: str, value: str) -> list[str]:
    v = value.lower().rstrip("/")
    for s in STARTER:
        if s["kind"] == kind and s["input"].lower().rstrip("/") == v:
            return list(s["topics"])
    return []


def _source_key(kind: str, value: str) -> str:
    v = value.lower().strip().rstrip("/")
    if kind == "reddit":
        m = re.search(r"r/([a-z0-9_]+)", v)
        return "reddit:" + (m.group(1) if m else v)
    if kind == "youtube":
        return "youtube:" + v.split("youtube.com/")[-1]
    return "rss:" + re.sub(r"^https?://(www\.)?", "", v)


def existing_keys(conn: sqlite3.Connection) -> set[str]:
    keys = set()
    for s in conn.execute("SELECT kind, feed_url, site_url, channel_url, title FROM sources"):
        if s["kind"] == "reddit" and s["feed_url"]:
            keys.add(_source_key("reddit", s["feed_url"]))
        elif s["kind"] == "youtube":
            if s["channel_url"]:
                keys.add(_source_key("youtube", s["channel_url"]))
            keys.add("ytitle:" + (s["title"] or "").lower())
        else:
            for u in (s["feed_url"], s["site_url"]):
                if u:
                    keys.add(_source_key("rss", u))
    return keys


def starter_list(conn: sqlite3.Connection) -> list[dict]:
    keys = existing_keys(conn)
    out = []
    for s in STARTER:
        added = _source_key(s["kind"], s["input"]) in keys or (
            s["kind"] == "youtube" and "ytitle:" + s["title"].lower() in keys
        )
        out.append({**s, "added": added})
    return out


def topic_affinity(conn: sqlite3.Connection, user_id: int) -> Counter:
    """Topic -> affinity from the user's source weights, likes, dislikes and comments."""
    aff: Counter = Counter()
    rows = conn.execute(
        """SELECT s.id, s.topics, s.title, COALESCE(p.weight, 1.0) AS weight, p.manual
           FROM sources s LEFT JOIN user_source_prefs p ON p.source_id=s.id AND p.user_id=?""",
        (user_id,),
    ).fetchall()
    for r in rows:
        topics = [t for t in (r["topics"] or "").split(",") if t] or guess_topics(r["title"])
        base = 0.5 + math.log(max(r["weight"], 0.05))  # having a source is mild interest
        if r["manual"] == "mute":
            base = -1.5
        for t in topics:
            aff[t] += base
    # Likes (+), dislikes (-) and comments (+, you cared enough to write something) on posts and Shorts: the
    # topics of the post's source count most, words in the title a little.
    engaged = (
        conn.execute(
            """SELECT CASE WHEN r.value > 0 THEN 1.0 ELSE -0.8 END AS w, COALESCE(i.title, sh.title) AS title,
                  src.topics AS topics, src.title AS stitle
           FROM reactions r
           LEFT JOIN items i ON r.item_type='item' AND i.id=r.item_id
           LEFT JOIN shorts sh ON r.item_type='short' AND sh.id=r.item_id
           LEFT JOIN sources src ON src.id=COALESCE(i.source_id, sh.source_id)
           WHERE r.user_id=? ORDER BY r.created_at DESC LIMIT 500""",
            (user_id,),
        ).fetchall()
        + conn.execute(
            """SELECT 0.7 AS w, COALESCE(i.title, sh.title) AS title, src.topics AS topics, src.title AS stitle
           FROM (SELECT item_type, item_id FROM comments WHERE user_id=?
                 GROUP BY item_type, item_id ORDER BY MAX(created_at) DESC LIMIT 300) c
           LEFT JOIN items i ON c.item_type='item' AND i.id=c.item_id
           LEFT JOIN shorts sh ON c.item_type='short' AND sh.id=c.item_id
           LEFT JOIN sources src ON src.id=COALESCE(i.source_id, sh.source_id)""",
            (user_id,),
        ).fetchall()
    )
    for r in engaged:
        source_topics = [x for x in (r["topics"] or "").split(",") if x] or guess_topics(r["stitle"] or "")
        for topic in source_topics:
            aff[topic] += 0.25 * r["w"]
        for topic in guess_topics(r["title"] or ""):
            aff[topic] += 0.3 * r["w"]
    return aff


def suggested(conn: sqlite3.Connection, user_id: int, limit: int = 12, kind: str | None = None) -> list[dict]:
    """Starter entries not added yet, best match first. `kind` = youtube | reddit | rss limits the list."""
    aff = topic_affinity(conn, user_id)
    keys = existing_keys(conn)
    # Liked Shorts/posts mention channels and subreddits; boost candidates whose name appears there.
    liked_titles = " ".join(
        (r["t"] or "").lower()
        for r in conn.execute(
            """SELECT COALESCE(i.title, sh.title || ' ' || sh.channel_name) AS t FROM reactions r
               LEFT JOIN items i ON r.item_type='item' AND i.id=r.item_id
               LEFT JOIN shorts sh ON r.item_type='short' AND sh.id=r.item_id
               WHERE r.user_id=? AND r.value=1 ORDER BY r.created_at DESC LIMIT 300""",
            (user_id,),
        )
    )
    liked_words = Counter(_WORD_RE.findall(liked_titles))
    scored = []
    for s in STARTER:
        if kind and s["kind"] != kind:
            continue
        if _source_key(s["kind"], s["input"]) in keys or (
            s["kind"] == "youtube" and "ytitle:" + s["title"].lower() in keys
        ):
            continue
        score = sum(aff.get(t, 0.0) for t in s["topics"]) / max(len(s["topics"]), 1)
        name_words = [w for w in _WORD_RE.findall(s["title"].lower()) if len(w) > 3 and w != "reddit"]
        score += 0.5 * sum(min(liked_words.get(w, 0), 3) for w in name_words)
        reason_topics = sorted(s["topics"], key=lambda t: -aff.get(t, 0))[:2]
        scored.append((score, s, reason_topics))
    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    out = []
    for score, s, topics in scored[:limit]:
        reason = (
            f"Matches your interests: {', '.join(topics)}" if score > 0 else f"Popular in {', '.join(s['topics'][:2])}"
        )
        out.append({**s, "score": round(score, 2), "reason": reason, "added": False})
    return out


def search_reddit(query: str, settings: Settings, limit: int = 10) -> list[dict]:
    q = query.strip()
    results: list[dict] = []
    try:
        reddit_throttle.wait()
        res = safe_get(
            f"https://www.reddit.com/subreddits/search.json?q={quote(q, safe='')}&limit={limit}&include_over_18=off",
            headers={"User-Agent": settings.reddit_user_agent, "Accept": "application/json"},
            timeout=10,
        )
        if res.status == 200:
            data = json.loads(res.content)
            for child in data.get("data", {}).get("children", [])[:limit]:
                d = child.get("data", {})
                name = d.get("display_name")
                if name:
                    subs = d.get("subscribers") or 0
                    results.append(
                        {
                            "kind": "reddit",
                            "input": name,
                            "title": f"r/{name}",
                            "subtitle": f"{subs:,} members · {(d.get('public_description') or '')[:100]}",
                        }
                    )
        else:
            log.info("reddit search returned %s", res.status)
    except Exception as exc:
        log.info("reddit search failed: %s", exc)
    if not results:
        name = re.sub(r"[^A-Za-z0-9_]", "", q)[:21]
        if len(name) >= 2:
            results.append(
                {
                    "kind": "reddit",
                    "input": name,
                    "title": f"r/{name}",
                    "subtitle": "Reddit search unavailable; try adding this subreddit by name",
                }
            )
    return results

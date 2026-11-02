#!/usr/bin/env python3
"""IPE Job Tracker - checks company career pages daily, filters by keywords,
writes docs/index.html (dashboard) + data/jobs.csv, and notifies via Telegram/email.

Usage:
  python tracker.py run        # check all sources, update dashboard, send alerts
  python tracker.py discover   # scan html_watch pages and suggest better (ATS) sources
"""
import csv, hashlib, html, json, os, re, smtplib, sys, time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
CONFIG = ROOT / "companies.json"
STATE = ROOT / "data" / "jobs.json"
CSV_OUT = ROOT / "data" / "jobs.csv"
HTML_OUT = ROOT / "docs" / "index.html"
UA = {"User-Agent": "Mozilla/5.0 (compatible; IPEJobTracker/1.0; personal job search)"}
TIMEOUT = 25
NEW_DAYS = 2          # jobs first seen within this many days show as NEW
DROP_DAYS = 30        # forget jobs not seen for this long

def now(): return datetime.now(timezone.utc)
def jid(*parts): return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]

def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw); r.raise_for_status(); return r

# ---------- keyword filter ----------
def matches(title, cfg):
    t = title.lower()
    inc = [k.lower() for k in cfg["keywords_include"]]
    exc = [k.lower() for k in cfg["keywords_exclude"]]
    hit = lambda k: re.search(r"(?<![a-z0-9])" + re.escape(k.strip()), t)
    return any(hit(k) for k in inc) and not any(hit(k) for k in exc)

# ---------- source fetchers: each returns list of dict(title,url,location) ----------
def fetch_greenhouse(src, cfg):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{src['id']}/jobs").json()
    return [dict(title=j["title"], url=j["absolute_url"], location=(j.get("location") or {}).get("name", ""))
            for j in d.get("jobs", [])]

def fetch_lever(src, cfg):
    d = get(f"https://api.lever.co/v0/postings/{src['id']}?mode=json").json()
    return [dict(title=j["text"], url=j["hostedUrl"], location=(j.get("categories") or {}).get("location", ""))
            for j in d]

def fetch_smartrecruiters(src, cfg):
    out, offset = [], 0
    while offset < 500:
        d = get(f"https://api.smartrecruiters.com/v1/companies/{src['id']}/postings?limit=100&offset={offset}").json()
        for j in d.get("content", []):
            loc = j.get("location") or {}
            out.append(dict(title=j["name"],
                            url=f"https://jobs.smartrecruiters.com/{src['id']}/{j['id']}",
                            location=", ".join(x for x in [loc.get("city"), loc.get("country", "").upper()] if x)))
        offset += 100
        if offset >= d.get("totalFound", 0): break
    return out

def fetch_workday(src, cfg):
    # src: tenant, wd (e.g. 5), site ; searches each include keyword server-side
    base = f"https://{src['tenant']}.wd{src['wd']}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{src['tenant']}/{src['site']}/jobs"
    seen, out = set(), []
    for kw in cfg["workday_search_terms"]:
        r = requests.post(api, headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT,
                          json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": kw})
        r.raise_for_status()
        for j in r.json().get("jobPostings", []):
            path = j.get("externalPath", "")
            if path in seen: continue
            seen.add(path)
            out.append(dict(title=j.get("title", ""), url=f"{base}/{src['site']}{path}",
                            location=j.get("locationsText", "")))
    return out

def fetch_rss(src, cfg):
    soup = BeautifulSoup(get(src["url"]).content, "xml")
    out = []
    for it in soup.find_all(["item", "entry"]):
        link = it.find("link")
        url = (link.get("href") or link.text) if link else src["url"]
        out.append(dict(title=(it.find("title").text if it.find("title") else "").strip(), url=url.strip(), location=""))
    return out

def fetch_html_watch(src, cfg):
    """Fallback for pages with no feed: pull link texts / headings that look like job titles."""
    soup = BeautifulSoup(get(src["url"]).text, "html.parser")
    out = []
    for tag in soup.find_all(["a", "h1", "h2", "h3", "h4", "li", "td", "span"]):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if 6 <= len(text) <= 120 and matches(text, cfg):
            a = tag if tag.name == "a" else tag.find("a")
            href = a.get("href") if a else None
            url = requests.compat.urljoin(src["url"], href) if href else src["url"]
            out.append(dict(title=text, url=url, location=""))
    return out

FETCHERS = dict(greenhouse=fetch_greenhouse, lever=fetch_lever, smartrecruiters=fetch_smartrecruiters,
                workday=fetch_workday, rss=fetch_rss, html_watch=fetch_html_watch)

# ---------- discover better sources ----------
PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.lever\.co/([A-Za-z0-9_-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("workday", r"https?://([a-z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
]
def discover(cfg):
    found = []
    for src in cfg["sources"]:
        if src["type"] != "html_watch": continue
        try: page = get(src["url"]).text
        except Exception as e: print(f"  skip {src['name']}: {e}"); continue
        for typ, pat in PATTERNS:
            m = re.search(pat, page)
            if m:
                s = dict(name=src["name"], region=src.get("region", ""), type=typ)
                if typ == "workday": s.update(tenant=m.group(1), wd=m.group(2), site=m.group(3))
                else: s["id"] = m.group(1)
                found.append(s); print("  FOUND", json.dumps(s)); break
    print("\nCopy the lines above into companies.json 'sources' (replace the html_watch entry)." if found
          else "Nothing detected automatically.")

# ---------- state ----------
def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else None

def update_state(old, results):
    first_run = old is None
    jobs = old or {}
    t = now().isoformat(timespec="seconds")
    new = []
    for src, items in results:
        for it in items:
            k = jid(src["name"], it["title"], it["url"])
            if k in jobs: jobs[k]["last_seen"] = t
            else:
                jobs[k] = dict(company=src["name"], region=src.get("region", ""), title=it["title"], url=it["url"],
                               location=it.get("location", ""), first_seen=t, last_seen=t)
                new.append(jobs[k])
    cutoff = now() - timedelta(days=DROP_DAYS)
    jobs = {k: v for k, v in jobs.items() if datetime.fromisoformat(v["last_seen"]) >= cutoff}
    return jobs, ([] if first_run else new)

# ---------- outputs ----------
def write_csv(jobs):
    rows = sorted(jobs.values(), key=lambda j: j["first_seen"], reverse=True)
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["First seen", "Company", "Region", "Title", "Location", "Link"])
        for j in rows: w.writerow([j["first_seen"][:10], j["company"], j["region"], j["title"], j["location"], j["url"]])

def write_html(jobs, errors):
    rows = sorted(jobs.values(), key=lambda j: j["first_seen"], reverse=True)
    cutoff = now() - timedelta(days=NEW_DAYS)
    e = html.escape
    trs = []
    for j in rows:
        isnew = datetime.fromisoformat(j["first_seen"]) >= cutoff
        trs.append(f'<tr data-r="{e(j["region"])}"><td>{"<span class=new>NEW</span>" if isnew else ""}</td>'
                   f'<td>{e(j["first_seen"][:10])}</td><td>{e(j["company"])}</td><td>{e(j["region"])}</td>'
                   f'<td><a href="{e(j["url"])}" target="_blank" rel="noopener">{e(j["title"])}</a></td>'
                   f'<td>{e(j["location"])}</td></tr>')
    errs = "".join(f"<li>{e(n)}: {e(m)}</li>" for n, m in errors)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>IPE Job Tracker</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd;--acc:#1F3864}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181d;--fg:#eaeaea;--mut:#9aa;--line:#333;--acc:#7aa2f7}}}}
body{{font-family:Arial,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:16px}}
h1{{margin:0 0 4px;color:var(--acc)}} .sub{{color:var(--mut);font-size:13px;margin-bottom:12px}}
input,select{{padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);margin:0 6px 8px 0}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}}
th{{color:var(--acc)}} a{{color:var(--acc)}}
.new{{background:#e8590c;color:#fff;font-size:11px;padding:2px 6px;border-radius:10px}}
details{{margin-top:16px;color:var(--mut);font-size:13px}}
</style></head><body>
<h1>IPE Job Tracker</h1>
<div class="sub">Updated {now().strftime('%Y-%m-%d %H:%M UTC')} &middot; {len(rows)} matching posts</div>
<input id="q" placeholder="Search company or title..." oninput="f()">
<select id="r" onchange="f()"><option value="">All regions</option><option>Global</option><option>Bangladesh</option></select>
<div class="wrap"><table id="t"><thead><tr><th></th><th>First seen</th><th>Company</th><th>Region</th><th>Job title</th><th>Location</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div>
<details><summary>Sources that failed in the last run ({len(errors)})</summary><ul>{errs}</ul></details>
<script>
function f(){{var q=document.getElementById('q').value.toLowerCase(),r=document.getElementById('r').value;
document.querySelectorAll('#t tbody tr').forEach(function(tr){{
tr.style.display=(tr.textContent.toLowerCase().indexOf(q)>-1&&(!r||tr.dataset.r===r))?'':'none';}});}}
</script></body></html>"""
    HTML_OUT.write_text(page, encoding="utf-8")

# ---------- notifications ----------
def notify(new):
    if not new: return
    lines = [f"{len(new)} new IPE-related post(s):"] + [f"- {j['company']}: {j['title']}\n  {j['url']}" for j in new[:40]]
    if len(new) > 40: lines.append(f"...and {len(new)-40} more on the dashboard")
    text = "\n".join(lines)
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            for i in range(0, len(text), 3900):
                requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              data={"chat_id": chat, "text": text[i:i+3900], "disable_web_page_preview": "true"}, timeout=20)
        except Exception as ex: print("Telegram failed:", ex)
    host, user, pw, to = (os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "EMAIL_TO"))
    if host and user and pw and to:
        try:
            m = EmailMessage(); m["Subject"] = f"IPE jobs: {len(new)} new"; m["From"] = user; m["To"] = to
            m.set_content(text)
            with smtplib.SMTP_SSL(host, 465, timeout=30) as s: s.login(user, pw); s.send_message(m)
        except Exception as ex: print("Email failed:", ex)

# ---------- main ----------
def run():
    cfg = json.loads(CONFIG.read_text())
    results, errors = [], []
    for src in cfg["sources"]:
        try:
            items = FETCHERS[src["type"]](src, cfg)
            items = [i for i in items if matches(i["title"], cfg)]
            results.append((src, items)); print(f"OK   {src['name']}: {len(items)} match")
        except Exception as ex:
            errors.append((src["name"], str(ex)[:150])); print(f"FAIL {src['name']}: {ex}")
        time.sleep(cfg.get("delay_seconds", 1))
    STATE.parent.mkdir(exist_ok=True); HTML_OUT.parent.mkdir(exist_ok=True)
    jobs, new = update_state(load_state(), results)
    STATE.write_text(json.dumps(jobs, indent=1))
    write_csv(jobs); write_html(jobs, errors); notify(new)
    print(f"\nTotal {len(jobs)} | new today {len(new)} | failed sources {len(errors)}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run": run()
    elif cmd == "discover": discover(json.loads(CONFIG.read_text()))
    else: print(__doc__)

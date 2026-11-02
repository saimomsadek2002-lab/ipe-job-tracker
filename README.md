# IPE Job Tracker

Checks 170+ company career pages every morning (8:00 Dhaka time), keeps only IPE-related
job titles, and shows them on ONE dashboard page. New posts get a NEW badge and are sent
to your Telegram / email. Free, runs on GitHub, nothing to keep running on your PC.

## Setup (about 15 minutes, no coding)

1. Create a free account at github.com, then click **New repository** -> name it `ipe-job-tracker` -> **Public** -> Create.
   (Public is needed for the free dashboard page. The list only contains public job links.)
2. Click **uploading an existing file**, drag in everything from this folder
   (`tracker.py`, `companies.json`, `requirements.txt`, `README.md`, and the `.github` folder, `data`, `docs`),
   then **Commit changes**.
   Tip: if the `.github` folder does not upload by drag-and-drop, use Add file -> Create new file and type
   `.github/workflows/daily.yml`, then paste the contents.
3. Go to **Settings -> Actions -> General -> Workflow permissions** -> choose **Read and write permissions** -> Save.
4. Go to **Actions** tab -> **Daily IPE job check** -> **Run workflow**. Wait 2-5 minutes.
5. Go to **Settings -> Pages** -> Source: **Deploy from a branch** -> Branch `main`, folder `/docs` -> Save.
   Your dashboard will be at `https://YOUR-USERNAME.github.io/ipe-job-tracker/` (bookmark it on your phone).

After this it runs by itself every day.

## Get alerts on your phone (optional, pick one or both)

**Telegram (easiest)**
1. In Telegram, message **@BotFather** -> `/newbot` -> follow steps -> copy the **token**.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the number after `"chat":{"id":`.
3. In GitHub: **Settings -> Secrets and variables -> Actions -> New repository secret**. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

**Email (Gmail)**
1. Turn on 2-step verification in your Google account, then create an **App password** (Google Account -> Security -> App passwords).
2. Add secrets: `SMTP_HOST` = `smtp.gmail.com`, `SMTP_USER` = your Gmail, `SMTP_PASS` = the app password, `EMAIL_TO` = where to send.

The very first run does NOT send alerts (everything would look new). Alerts start from the second day.

## Make it smarter: find real job feeds

Most companies are watched with `html_watch` (reads the career page text). It works for simple pages
but misses JavaScript-heavy sites. Many big companies use Greenhouse / Lever / SmartRecruiters / Workday,
which give exact, reliable data. To auto-detect them, run on any computer with Python:

    pip install -r requirements.txt
    python tracker.py discover

It prints ready-to-paste lines like `{"name":"X","type":"greenhouse","id":"x"}`. Replace the company's
`html_watch` entry in `companies.json` with it. Check the "Sources that failed" section at the bottom of the dashboard
to see which sites need this.

## Customize

Edit `companies.json`:
- `keywords_include` / `keywords_exclude`: words that must / must not appear in a job title.
- `sources`: add or remove companies. Types: `greenhouse`, `lever`, `smartrecruiters`, `workday`, `rss`, `html_watch`.
- Bangladesh companies mostly post on BDJobs, so also use the alerts below.

## Portals with no public feed (set once, takes 5 minutes)

- **BDJobs**: log in -> search "Industrial Engineer" / "Production Engineer" / "Management Trainee" -> save as Job Alert.
- **LinkedIn**: Jobs -> search same keywords, location Bangladesh and your target countries -> toggle **Set alert** (daily).
- **Indeed / Google Alerts**: same keywords. Google Alerts can deliver as an RSS feed, which you can paste into `companies.json` as `{"type":"rss","url":"..."}`.

## Honest limits
- Some career sites block bots or need JavaScript: they will show under "failed sources" or return nothing.
- html_watch shows job-like titles it finds on the page; the link may point to the career page instead of the exact job.
- Sites change layouts sometimes, so check the failed list now and then.

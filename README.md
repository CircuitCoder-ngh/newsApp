# Worldline

A personal world-news timeline. Every hour a GitHub Action reads 54 RSS feeds from 34 English-language outlets around the world. It merges coverage of the same event, groups events into ongoing stories, and publishes a static site to GitHub Pages. It costs nothing to run: no servers, no API keys, no paid models.

- **Timeline:** the last 48 hours of events, newest first. Each event shows one headline, a short excerpt, and a link to every outlet that covered it.
- **Stories:** each ongoing story has its own page with its full timeline, earliest first.
- **Archive:** one page per day for the last 30 days.

Each entry has a small bar chart with one bar per outlet that reported it, colored by the outlet's region. This makes it easy to tell a global story from a regional one. By default, events reported by only one outlet are hidden. A toggle shows them.

## How it works

```
feeds.yaml ──► fetch ──► dedupe ──► embed headlines ──► cluster ──► label ──► data/ ──► build ──► _site/
               (RSS)     (by URL)   (bge-small, CPU)    (events,    (no LLM)   (JSON)   (Jinja2)  (static HTML)
                                                        stories)
```

1. **Fetch** (`pipeline/fetch.py`) requests each feed once, using conditional GET. It drops live blogs, video, opinion, sport and similar items using the URL and title patterns in `feeds.yaml`. It also drops items older than 48 hours and anything already seen.
2. **Embed** (`pipeline/embed.py`) turns each headline into a vector with the small `BAAI/bge-small-en-v1.5` model through `fastembed`, which runs on CPU with no PyTorch.
3. **Cluster** (`pipeline/cluster.py`) works incrementally, comparing each new headline with its average similarity to the articles of every open event:
   - **Event:** a headline that scores at least `EVENT_SIM` joins that event. Events close after 18 hours of silence or 36 hours in total.
   - **Story:** otherwise the headline starts a new event, which joins the closest open story if it scores at least `STORY_SIM` against that story's latest 40 articles. Otherwise it starts a new story.
4. **Label** (`pipeline/label.py`) sets each event's headline to the member article closest to the cluster's center. A story's title is the headline of its most widely covered recent event, and its key terms come from class-based TF-IDF.
5. **Housekeeping** drops one-article stories once they've been quiet for 7 days, and moves stories that have been quiet for 30 days into `archive/`.
6. **Build** (`pipeline/site/`) renders plain HTML that works without JavaScript. The topic filters are pure CSS. A few lines of JS remember your filter choices.

## Running locally

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                                         # install dependencies
uv run python -m pipeline check-feeds           # fetch every feed once and report problems
uv run python -m pipeline run                   # fetch + cluster into ./data
uv run python -m pipeline build                 # render ./_site
python -m http.server -d _site 8000             # preview at http://localhost:8000
uv run python -m pipeline inspect --articles    # print recent stories, events and articles
uv run pytest                                   # tests
```

`--data DIR` (before the command) points any command at a different data directory. For example, `uv run python -m pipeline --data ./.localdata run` keeps experiments away from `./data`.

## Deploying to GitHub Pages

1. Create a **public** GitHub repository. Free accounts only get Pages and unlimited Actions minutes on public repos. Push this project to its `main` branch.
2. In **Settings → Pages**, set **Source** to **GitHub Actions**.
3. In **Actions → Update timeline**, choose **Run workflow** to start the first run.

From then on the workflow runs hourly at 17 minutes past the hour, and again whenever `main` changes. It stores pipeline state on a `data` branch as a single commit that's replaced each run, so the repository doesn't grow over time.

Notes:
- GitHub starts scheduled runs on a best-effort basis, often 5–30 minutes late.
- GitHub disables scheduled workflows in public repos after 60 days without activity. The hourly push to `data` should keep the schedule active. If it ever stops, re-enable it on the Actions tab.
- The site is public. It only shows headlines, short excerpts and links, and every entry credits and links to its source.

## Tuning

Everything tunable is in `pipeline/config.py`:

| Setting | Default | Effect |
|---|---|---|
| `EVENT_SIM` | 0.75 | Raise it if unrelated developments merge into one event. Lower it if the same news shows up as separate events. |
| `STORY_SIM` | 0.60 | Raise it if stories collect loosely related events. Lower it if one story splits apart. |
| `EVENT_GAP`, `EVENT_MAX_SPAN` | 18h, 36h | How long an event keeps accepting new articles. |
| `STORY_GAP` | 7 days | How long a quiet story can still pick up new events. |
| `SITE_TIMEZONE` | America/New_York | Time zone for every time shown on the site. |
| `MIN_OUTLETS_DEFAULT` | 2 | Events with fewer outlets are hidden until toggled on. |

The defaults were tuned on two days of real coverage. In that data, headlines about the same event scored about 0.76–0.97, headlines from the same story about 0.52–0.70, and unrelated headlines about 0.33–0.50. After changing a threshold, rebuild your local data (`rm -rf .localdata` then `run`) and compare `inspect` output.

## Adding or removing outlets

Edit `feeds.yaml` and run `uv run python -m pipeline check-feeds`. Each outlet has a region, which sets its bar color, and one or more feeds tagged `world`, `business` or `science`. When an article appears in more than one of an outlet's feeds, the first feed listed decides its topic.

## Data layout (`data/`, the `data` branch)

| Path | Contents |
|---|---|
| `articles/YYYY-MM-DD.jsonl` | Raw ingest log by publish date, kept for 30 days |
| `events/YYYY-MM.json` | Events of active stories, by month first seen |
| `stories.json` | Stories active in the last 30 days |
| `archive/` | Older stories and their events |
| `feed_state.json` | Per-feed ETag/Last-Modified and failure counts |
| `runs.jsonl` | One line per run: counts, timing, failed feeds |

## Adding AI summaries later

`Event.summary` and `Story.summary` exist but are always empty. The templates already show a summary in place of the outlet's excerpt whenever one is set. To add summaries, insert a step in `pipeline/run.py` after relabeling that fills them in for the touched events and stories. That step could call a local model through Ollama, or Claude Haiku through the Anthropic API from the Action, which would cost a few dollars a month at hourly scans.

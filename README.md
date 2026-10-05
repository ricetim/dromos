# Dromos

A personal running-analytics dashboard. It pulls activities from Coros (and
optionally Strava), and shows them with maps, charts, laps, personal bests,
shoe mileage, and goals.

The whole app ships as one Docker image, `ricetim/dromos:latest`. FastAPI
serves the API, the built React frontend, and pre-built static JSON snapshots.
APScheduler handles background sync.

## Running with Docker

```bash
cp .env.example .env      # then fill in the values below
docker compose up -d      # serves on port 80
```

`docker-compose.yml` mounts `./data` to `/data`. That directory holds the SQLite
database, the raw `.fit` files, the generated static JSON, and the map-tile
cache. Back it up, and don't delete it between deploys.

### Updating a deployment

```bash
docker compose pull && docker compose up -d
```

When the static JSON format changes (`STATIC_SCHEMA_VERSION` in
`backend/app/services/builder.py`), the first boot after an update runs a full
rebuild in the background. That takes a few minutes on a large history. The
site keeps serving the previous files until each one is replaced.

## Configuration (`.env`)

Compose loads every variable from `.env` through `env_file`. `.env` is
gitignored, so secrets stay out of the repo. `.env.example` lists every key.

| Variable | Required | Purpose |
|---|---|---|
| `COROS_EMAIL`, `COROS_PASSWORD` | For Coros sync | Account login for Coros's unofficial API. When set, the app checks for new activities every 5 minutes, on the clock (:00, :05 … :55). |
| `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN` | For Strava sync | Strava API app credentials plus an OAuth refresh token. Syncs every 6 hours: matches Strava activities to local runs, imports Strava-only runs, and pulls photos. |
| `CARTO_API_KEY` | For the Light and Dark map styles | See below. |
| `DATA_DIR` | No | Overrides the data directory. Defaults to `/data` in the container. |
| `DISPLAY_TZ` | No | IANA timezone that decides which calendar day a run falls on. Defaults to `America/Los_Angeles`. |

### `CARTO_API_KEY`: why it's needed

The activity maps offer three tile styles. Light and Dark come from
[CARTO basemaps](https://carto.com/basemaps), and Standard comes from
OpenStreetMap. **CARTO now requires an API key.** Without one, CARTO doesn't
return an error. It returns HTTP 200 with an "API KEY REQUIRED" watermark image
in place of every tile.

To set it up, get a key at <https://carto.com/basemaps> and add it to `.env` on
the host that runs the container:

```bash
CARTO_API_KEY=your-key-here
```

Then restart with `docker compose up -d`. Compose only reads `.env` when the
container is created, so editing the file alone does nothing until then.

How the key is used:

- **It never reaches the browser.** Maps request tiles from the app's own
  caching proxy (`/api/tiles/{style}/{z}/{x}/{y}.png`, in
  `backend/app/routers/tiles.py`). The proxy adds the key server-side when it
  fetches from CARTO. Only the Light and Dark styles send it; OpenStreetMap
  never receives it.
- **Tiles are cached on disk permanently** under `data/tiles/`, so each tile is
  fetched from CARTO once. After that, you only use your CARTO quota when you
  view an area of the map you haven't looked at before.
- **Without a key**, Light and Dark tiles show blank in areas that aren't cached
  yet. The proxy recognises CARTO's watermark image and refuses to cache it.
  Standard (OpenStreetMap) keeps working.
- **Watermark tiles cached before this fix** are detected and refetched the next
  time they're requested, so they clear up once the key is in place. No manual
  cache cleanup is needed.

## Development

- **Backend:** run from `backend/` with `DATA_DIR` pointing at a scratch
  directory, e.g. `DATA_DIR=/tmp/testdata python3 -m pytest -q`
- **Frontend:** `cd frontend && npm run dev` (proxies `/api` and `/static` to
  `localhost:8000`)
- **Type-check:** `npm run build`, which runs `tsc -b`. A bare
  `npx tsc --noEmit` checks **nothing** in this repo, because `tsconfig.json`
  only contains project references.
- **Event log:** the system log viewer is at `/api/logs/view`.

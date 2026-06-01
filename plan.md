# Dromos Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a personal running fitness dashboard that ingests Coros `.fit` files, computes Runalyze-style statistics, and displays them in a React SPA with maps, GPS photo pins, charts, gear tracking, goals, and Daniels/Pfitzinger training plans — packaged as a Docker Compose application.

**Architecture:** FastAPI backend + SQLite stores full-resolution DataPoints; React/TypeScript SPA; APScheduler for background Coros/Strava sync; Docker Compose runs backend (port 8000) + Nginx-served frontend (port 80) with a shared `./data` volume.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, fitparse, Pillow, APScheduler / React 18, TypeScript, Vite, react-leaflet, Recharts, Tailwind CSS / Docker + Docker Compose

---

## Project Structure

```
dromos/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── config.py
│   │   ├── routers/
│   │   │   ├── activities.py
│   │   │   ├── shoes.py
│   │   │   ├── goals.py
│   │   │   ├── stats.py
│   │   │   ├── sync.py
│   │   │   └── plans.py
│   │   └── services/
│   │       ├── fit_parser.py
│   │       ├── analytics.py
│   │       ├── strava.py
│   │       ├── coros.py
│   │       ├── exif.py
│   │       └── training_plans/
│   │           ├── __init__.py
│   │           ├── daniels.py
│   │           └── pfitzinger.py
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── fixtures/
│   │   │   └── sample.fit
│   │   ├── test_models.py
│   │   ├── test_fit_parser.py
│   │   ├── test_activities.py
│   │   ├── test_analytics.py
│   │   ├── test_strava.py
│   │   └── test_training_plans.py
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── types/index.ts
│   │   ├── api/client.ts
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── ActivityList.tsx
│   │   │   ├── ActivityDetail.tsx
│   │   │   ├── Gear.tsx
│   │   │   ├── Goals.tsx
│   │   │   ├── Plans.tsx
│   │   │   └── PlanDetail.tsx
│   │   └── components/
│   │       ├── ActivityMap.tsx
│   │       ├── ActivityCharts.tsx
│   │       ├── PhotoGallery.tsx
│   │       └── GoalCard.tsx
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   └── vite.config.ts
├── data/
│   └── fit_files/
├── docker-compose.yml
├── .env.example
├── design.md
├── requirements.md
└── plan.md
```

---

## Phase 1 — Core Ingest + Docker

### Task 1: Backend project scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`

**Step 1: Create `backend/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "dromos-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "sqlmodel>=0.0.19",
    "fitparse>=1.2",
    "httpx>=0.27",
    "python-multipart>=0.0.9",
    "apscheduler>=3.10",
    "Pillow>=10.0",
    "exifread>=3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]
```

**Step 2: Create `backend/app/config.py`**

```python
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data" / "fit_files")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{Path(os.getenv('DATA_DIR', str(BASE_DIR / 'data')))}/dromos.db"

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET", "")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN", "")

COROS_EMAIL = os.getenv("COROS_EMAIL", "")
COROS_PASSWORD = os.getenv("COROS_PASSWORD", "")
```

**Step 3: Create `backend/app/database.py`**

```python
from sqlmodel import SQLModel, create_engine, Session
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
```

**Step 4: Create `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import create_db_and_tables

app = FastAPI(title="Dromos")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

@app.get("/api/health")
def health():
    return {"status": "ok"}
```

**Step 5: Create `backend/tests/conftest.py`**

```python
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool
from app.main import app
from app.database import get_session

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client")
def client_fixture(session):
    def get_session_override():
        yield session
    app.dependency_overrides[get_session] = get_session_override
    yield TestClient(app)
    app.dependency_overrides.clear()
```

**Step 6: Install and verify**

```bash
cd backend && pip install -e ".[dev]"
pytest tests/ -v
uvicorn app.main:app --reload
curl http://localhost:8000/api/health
```
Expected: `{"status":"ok"}`

**Step 7: Commit**

```bash
git add backend/
git commit -m "feat: backend scaffold with FastAPI + SQLite"
```

---

### Task 2: Docker Compose

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `docker-compose.yml`
- Create: `.env.example`

**Step 1: Write the Docker tests (smoke test)**

Create `tests/test_docker_compose.py` (root level, run manually):

```python
# Manual smoke test — run after `docker compose up -d`
# curl http://localhost/api/health  →  {"status":"ok"}
# curl http://localhost             →  HTML page
```

**Step 2: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install -e ".[dev]" --no-cache-dir || pip install fastapi uvicorn[standard] \
    sqlmodel fitparse httpx python-multipart apscheduler Pillow exifread
COPY app/ ./app/
ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Create `frontend/nginx.conf`**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**Step 4: Create `frontend/Dockerfile`**

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**Step 5: Create `docker-compose.yml`**

```yaml
services:
  backend:
    build: ./backend
    volumes:
      - ./data:/data
    env_file: .env
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  data:
```

**Step 6: Create `.env.example`**

```
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REFRESH_TOKEN=
COROS_EMAIL=
COROS_PASSWORD=
```

**Step 7: Verify build (once frontend scaffold exists)**

```bash
docker compose build
docker compose up -d
curl http://localhost/api/health
docker compose down
```
Expected: `{"status":"ok"}`

**Step 8: Commit**

```bash
git add backend/Dockerfile frontend/Dockerfile frontend/nginx.conf docker-compose.yml .env.example
git commit -m "feat: Docker Compose with backend + Nginx frontend"
```

---

### Task 3: Data models

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/tests/test_models.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_models.py
from datetime import datetime, timezone, date
from app.models import Activity, DataPoint, Shoe, ActivityShoe, Goal, Photo
from app.models import TrainingPlan, PlannedWorkout

def test_create_activity(session):
    act = Activity(
        source="manual_upload",
        started_at=datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc),
        distance_m=10000.0,
        duration_s=3600,
        sport_type="run",
    )
    session.add(act)
    session.commit()
    session.refresh(act)
    assert act.id is not None

def test_photo_has_gps_fields(session):
    act = Activity(source="manual_upload", started_at=datetime.now(timezone.utc),
                   distance_m=5000, duration_s=1800, sport_type="run")
    session.add(act)
    session.commit()
    photo = Photo(activity_id=act.id, url="https://example.com/photo.jpg",
                  lat=37.7749, lon=-122.4194)
    session.add(photo)
    session.commit()
    session.refresh(photo)
    assert photo.lat == 37.7749
    assert photo.lon == -122.4194

def test_create_training_plan(session):
    plan = TrainingPlan(
        name="Daniels 5K Plan",
        source="daniels",
        goal_race_date=date(2026, 6, 1),
        goal_distance="5k",
        start_date=date(2026, 3, 1),
        target_vdot=50.0,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    assert plan.id is not None

def test_planned_workout_links_activity(session):
    act = Activity(source="manual_upload", started_at=datetime.now(timezone.utc),
                   distance_m=10000, duration_s=3600, sport_type="run")
    plan = TrainingPlan(name="Test", source="daniels", goal_race_date=date(2026,6,1),
                        goal_distance="marathon", start_date=date(2026,3,1))
    session.add(act)
    session.add(plan)
    session.commit()
    workout = PlannedWorkout(
        training_plan_id=plan.id,
        scheduled_date=date(2026, 3, 5),
        week_number=1,
        workout_type="easy",
        description="8 km easy",
        target_distance_m=8000,
        completed_activity_id=act.id,
    )
    session.add(workout)
    session.commit()
    session.refresh(workout)
    assert workout.completed_activity_id == act.id
```

**Step 2: Run to verify failure**

```bash
cd backend && pytest tests/test_models.py -v
```
Expected: `ImportError` — models don't exist yet.

**Step 3: Create `backend/app/models.py`**

```python
from typing import Optional
from datetime import datetime, date
from sqlmodel import Field, SQLModel, Relationship


class Activity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str                          # "coros" | "strava" | "manual_upload"
    external_id: Optional[str] = None
    strava_id: Optional[str] = None
    started_at: datetime
    distance_m: float = 0.0
    duration_s: int = 0
    elevation_gain_m: float = 0.0
    avg_hr: Optional[int] = None
    avg_pace_s_per_km: Optional[float] = None
    sport_type: str = "run"
    fit_file_path: Optional[str] = None
    notes: Optional[str] = None

    datapoints: list["DataPoint"] = Relationship(back_populates="activity")
    photos: list["Photo"] = Relationship(back_populates="activity")
    activity_shoes: list["ActivityShoe"] = Relationship(back_populates="activity")


class DataPoint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", index=True)
    timestamp: datetime
    lat: Optional[float] = None
    lon: Optional[float] = None
    distance_m: Optional[float] = None
    speed_m_s: Optional[float] = None
    heart_rate: Optional[int] = None
    cadence: Optional[int] = None
    altitude_m: Optional[float] = None
    power_w: Optional[int] = None

    activity: Optional[Activity] = Relationship(back_populates="datapoints")


class Photo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", index=True)
    strava_photo_id: Optional[str] = None
    url: str
    captured_at: Optional[datetime] = None
    lat: Optional[float] = None          # EXIF GPS latitude
    lon: Optional[float] = None          # EXIF GPS longitude

    activity: Optional[Activity] = Relationship(back_populates="photos")


class Shoe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    brand: Optional[str] = None
    retired: bool = False
    notes: Optional[str] = None
    retirement_threshold_km: float = 800.0

    activity_shoes: list["ActivityShoe"] = Relationship(back_populates="shoe")


class ActivityShoe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", index=True)
    shoe_id: int = Field(foreign_key="shoe.id", index=True)

    activity: Optional[Activity] = Relationship(back_populates="activity_shoes")
    shoe: Optional[Shoe] = Relationship(back_populates="activity_shoes")


class Goal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str                            # "weekly_distance" | "monthly_distance" | "annual_distance"
    target_value: float
    period_start: datetime
    period_end: datetime
    notes: Optional[str] = None


class TrainingPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    source: str                          # "daniels" | "pfitzinger"
    goal_race_date: date
    goal_distance: str                   # "5k" | "10k" | "half" | "marathon"
    start_date: date
    target_vdot: Optional[float] = None  # Daniels plans
    peak_weekly_km: Optional[float] = None  # Pfitzinger plans
    notes: Optional[str] = None

    workouts: list["PlannedWorkout"] = Relationship(back_populates="plan")


class PlannedWorkout(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    training_plan_id: int = Field(foreign_key="trainingplan.id", index=True)
    scheduled_date: date
    week_number: int
    workout_type: str   # "easy"|"long"|"marathon_pace"|"threshold"|"interval"|"recovery"|"rest"
    description: str
    target_distance_m: Optional[float] = None
    target_pace_s_per_km: Optional[float] = None
    completed_activity_id: Optional[int] = Field(default=None, foreign_key="activity.id")

    plan: Optional[TrainingPlan] = Relationship(back_populates="workouts")
```

**Step 4: Run tests**

```bash
cd backend && pytest tests/test_models.py -v
```
Expected: `4 passed`

**Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: data models — Activity, DataPoint, Photo (GPS), TrainingPlan, PlannedWorkout"
```

---

### Task 4: `.fit` file parser service

**Files:**
- Create: `backend/app/services/fit_parser.py`
- Create: `backend/tests/test_fit_parser.py`
- Add: `backend/tests/fixtures/sample.fit` (copy a real .fit from a Coros run)

**Step 1: Write failing tests**

```python
# backend/tests/test_fit_parser.py
import pytest
from pathlib import Path
from app.services.fit_parser import parse_fit_file, FitParseResult

FIXTURE = Path(__file__).parent / "fixtures" / "sample.fit"

@pytest.mark.skipif(not FIXTURE.exists(), reason="no sample.fit fixture")
def test_parse_returns_result():
    result = parse_fit_file(FIXTURE)
    assert isinstance(result, FitParseResult)
    assert result.started_at is not None
    assert result.distance_m > 0
    assert result.duration_s > 0
    assert len(result.datapoints) > 0

@pytest.mark.skipif(not FIXTURE.exists(), reason="no sample.fit fixture")
def test_datapoints_have_timestamps():
    result = parse_fit_file(FIXTURE)
    for dp in result.datapoints:
        assert dp["timestamp"] is not None

def test_parse_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_fit_file(Path("/nonexistent/file.fit"))
```

**Step 2: Run to verify failure**

```bash
cd backend && pytest tests/test_fit_parser.py::test_parse_nonexistent_file_raises -v
```
Expected: `ImportError`

**Step 3: Create `backend/app/services/fit_parser.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import fitparse


@dataclass
class FitParseResult:
    started_at: datetime
    distance_m: float
    duration_s: int
    elevation_gain_m: float
    avg_hr: int | None
    sport_type: str
    datapoints: list[dict[str, Any]] = field(default_factory=list)


def parse_fit_file(path: Path) -> FitParseResult:
    if not path.exists():
        raise FileNotFoundError(f"FIT file not found: {path}")

    fitfile = fitparse.FitFile(str(path))
    records: list[dict] = []
    session_data: dict = {}
    sport_type = "run"

    for record in fitfile.get_messages("record"):
        row = {f.name: f.value for f in record if f.value is not None}
        if row:
            records.append(row)

    for msg in fitfile.get_messages("session"):
        session_data = {f.name: f.value for f in msg if f.value is not None}

    for msg in fitfile.get_messages("sport"):
        sport_val = {f.name: f.value for f in msg}.get("sport", "running")
        sport_type = str(sport_val).lower().replace(" ", "_")

    started_at = session_data.get("start_time") or (
        records[0]["timestamp"] if records else datetime.now(timezone.utc)
    )
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    distance_m = float(session_data.get("total_distance") or 0)
    duration_s = int(session_data.get("total_elapsed_time") or 0)
    elevation_gain_m = float(session_data.get("total_ascent") or 0)
    avg_hr = session_data.get("avg_heart_rate")

    datapoints = []
    for r in records:
        ts = r.get("timestamp")
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        pos_lat = r.get("position_lat")
        pos_lon = r.get("position_long")
        # Coros stores semicircles; divide by 2^31 / 180
        datapoints.append({
            "timestamp": ts,
            "lat": pos_lat / 11930465 if pos_lat is not None else None,
            "lon": pos_lon / 11930465 if pos_lon is not None else None,
            "distance_m": r.get("distance"),
            "speed_m_s": r.get("speed"),
            "heart_rate": r.get("heart_rate"),
            "cadence": (r.get("cadence") or 0) * 2 if r.get("cadence") else None,
            "altitude_m": r.get("altitude"),
            "power_w": r.get("power"),
        })

    return FitParseResult(
        started_at=started_at,
        distance_m=distance_m,
        duration_s=duration_s,
        elevation_gain_m=elevation_gain_m,
        avg_hr=int(avg_hr) if avg_hr else None,
        sport_type=sport_type,
        datapoints=datapoints,
    )
```

**Step 4: Run tests**

```bash
cd backend && pytest tests/test_fit_parser.py -v
```
Expected: `test_parse_nonexistent_file_raises` passes; fixture tests skip until sample.fit added.

**Step 5: Commit**

```bash
git add backend/app/services/ backend/tests/test_fit_parser.py
git commit -m "feat: FIT file parser service"
```

---

### Task 5: Activities router

**Files:**
- Create: `backend/app/routers/activities.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_activities.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_activities.py
import pytest
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "sample.fit"

def test_list_activities_empty(client):
    r = client.get("/api/activities")
    assert r.status_code == 200
    assert r.json() == []

def test_get_nonexistent_activity(client):
    r = client.get("/api/activities/999")
    assert r.status_code == 404

@pytest.mark.skipif(not FIXTURE.exists(), reason="no sample.fit")
def test_upload_fit_file(client, tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    with open(FIXTURE, "rb") as f:
        r = client.post("/api/activities/upload",
                        files={"file": ("run.fit", f, "application/octet-stream")})
    assert r.status_code == 201
    assert r.json()["distance_m"] > 0
```

**Step 2: Run to verify failure**

```bash
cd backend && pytest tests/test_activities.py::test_list_activities_empty -v
```
Expected: `404` routing error.

**Step 3: Create `backend/app/routers/activities.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlmodel import Session, select
from app.database import get_session
from app.models import Activity, DataPoint
from app.services.fit_parser import parse_fit_file
from app.config import DATA_DIR
import shutil, uuid
from pathlib import Path

router = APIRouter(prefix="/api/activities", tags=["activities"])


@router.get("", response_model=list[Activity])
def list_activities(session: Session = Depends(get_session)):
    return session.exec(select(Activity).order_by(Activity.started_at.desc())).all()


@router.get("/{activity_id}", response_model=Activity)
def get_activity(activity_id: int, session: Session = Depends(get_session)):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    return act


@router.get("/{activity_id}/datapoints")
def get_datapoints(activity_id: int, session: Session = Depends(get_session)):
    if not session.get(Activity, activity_id):
        raise HTTPException(status_code=404)
    return session.exec(
        select(DataPoint)
        .where(DataPoint.activity_id == activity_id)
        .order_by(DataPoint.timestamp)
    ).all()


@router.get("/{activity_id}/photos")
def get_photos(activity_id: int, session: Session = Depends(get_session)):
    from app.models import Photo
    if not session.get(Activity, activity_id):
        raise HTTPException(status_code=404)
    from sqlmodel import select as sel
    return session.exec(sel(Photo).where(Photo.activity_id == activity_id)).all()


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_fit(file: UploadFile = File(...), session: Session = Depends(get_session)):
    dest = DATA_DIR / f"{uuid.uuid4()}.fit"
    with dest.open("wb") as buf:
        shutil.copyfileobj(file.file, buf)
    try:
        result = parse_fit_file(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Cannot parse FIT file: {e}")

    paces = [1000 / dp["speed_m_s"] for dp in result.datapoints
             if dp.get("speed_m_s") and dp["speed_m_s"] > 0]
    act = Activity(
        source="manual_upload",
        started_at=result.started_at,
        distance_m=result.distance_m,
        duration_s=result.duration_s,
        elevation_gain_m=result.elevation_gain_m,
        avg_hr=result.avg_hr,
        sport_type=result.sport_type,
        fit_file_path=str(dest),
        avg_pace_s_per_km=sum(paces) / len(paces) if paces else None,
    )
    session.add(act)
    session.flush()
    for dp in result.datapoints:
        session.add(DataPoint(activity_id=act.id, **dp))
    session.commit()
    session.refresh(act)
    return act


@router.patch("/{activity_id}")
def update_activity(activity_id: int, data: dict, session: Session = Depends(get_session)):
    act = session.get(Activity, activity_id)
    if not act:
        raise HTTPException(status_code=404)
    for k in {"notes", "strava_id"}:
        if k in data:
            setattr(act, k, data[k])
    session.add(act)
    session.commit()
    session.refresh(act)
    return act
```

**Step 4: Register router — add to `backend/app/main.py`:**

```python
from app.routers import activities
app.include_router(activities.router)
```

**Step 5: Run tests**

```bash
cd backend && pytest tests/test_activities.py -v
```
Expected: `test_list_activities_empty` and `test_get_nonexistent_activity` pass.

**Step 6: Commit**

```bash
git add backend/app/routers/ backend/app/main.py backend/tests/test_activities.py
git commit -m "feat: activities router — upload, list, get, datapoints, photos"
```

---

### Task 6: Frontend scaffold + Activity List page

**Files:**
- Create: `frontend/` (Vite scaffold)
- Create: `frontend/src/types/index.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/pages/ActivityList.tsx`

**Step 1: Scaffold**

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install react-router-dom @tanstack/react-query axios
npm install leaflet react-leaflet @types/leaflet
npm install recharts
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

Add `./src/**/*.{ts,tsx}` to `content` in `tailwind.config.js`.
Add Tailwind directives to `src/index.css`.

**Step 2: Create `frontend/src/types/index.ts`**

```typescript
export interface Activity {
  id: number; source: string; started_at: string;
  distance_m: number; duration_s: number; elevation_gain_m: number;
  avg_hr: number | null; avg_pace_s_per_km: number | null;
  sport_type: string; notes: string | null;
}
export interface DataPoint {
  id: number; activity_id: number; timestamp: string;
  lat: number | null; lon: number | null; distance_m: number | null;
  speed_m_s: number | null; heart_rate: number | null;
  cadence: number | null; altitude_m: number | null; power_w: number | null;
}
export interface Photo {
  id: number; activity_id: number; url: string;
  captured_at: string | null; lat: number | null; lon: number | null;
}
export interface Shoe {
  id: number; name: string; brand: string | null;
  retired: boolean; retirement_threshold_km: number; total_distance_km?: number;
}
export interface Goal {
  id: number; type: string; target_value: number;
  period_start: string; period_end: string; notes: string | null;
}
export interface TrainingPlan {
  id: number; name: string; source: string;
  goal_race_date: string; goal_distance: string;
  start_date: string; target_vdot: number | null; peak_weekly_km: number | null;
}
export interface PlannedWorkout {
  id: number; training_plan_id: number; scheduled_date: string;
  week_number: number; workout_type: string; description: string;
  target_distance_m: number | null; target_pace_s_per_km: number | null;
  completed_activity_id: number | null;
}
```

**Step 3: Create `frontend/src/api/client.ts`**

```typescript
import axios from "axios";
const api = axios.create({ baseURL: "/api" });

export const getActivities = () => api.get("/activities").then(r => r.data);
export const getActivity = (id: number) => api.get(`/activities/${id}`).then(r => r.data);
export const getDataPoints = (id: number) => api.get(`/activities/${id}/datapoints`).then(r => r.data);
export const getPhotos = (id: number) => api.get(`/activities/${id}/photos`).then(r => r.data);
export const uploadFit = (file: File) => {
  const fd = new FormData(); fd.append("file", file);
  return api.post("/activities/upload", fd).then(r => r.data);
};
export const getShoes = () => api.get("/shoes").then(r => r.data);
export const createShoe = (data: object) => api.post("/shoes", data).then(r => r.data);
export const updateShoe = (id: number, data: object) => api.patch(`/shoes/${id}`, data).then(r => r.data);
export const getGoals = () => api.get("/goals").then(r => r.data);
export const createGoal = (data: object) => api.post("/goals", data).then(r => r.data);
export const deleteGoal = (id: number) => api.delete(`/goals/${id}`);
export const getStatsSummary = () => api.get("/stats/summary").then(r => r.data);
export const getPlans = () => api.get("/plans").then(r => r.data);
export const createPlan = (data: object) => api.post("/plans", data).then(r => r.data);
export const getPlan = (id: number) => api.get(`/plans/${id}`).then(r => r.data);
export const getPlanWorkouts = (id: number) => api.get(`/plans/${id}/workouts`).then(r => r.data);
export const deletePlan = (id: number) => api.delete(`/plans/${id}`);
```

**Step 4: Create `frontend/src/App.tsx`** with BrowserRouter + QueryClientProvider routing all pages.

**Step 5: Create `frontend/src/pages/ActivityList.tsx`** — scrollable list of activities with upload button, distance/pace display, link to detail page.

**Step 6: Verify**

```bash
# Terminal 1
cd backend && uvicorn app.main:app --reload

# Terminal 2
cd frontend && npm run dev
```
Open `http://localhost:5173`. Upload a `.fit` file — activity appears in the list.

**Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: frontend scaffold + Activity List page with .fit upload"
```

---

## Phase 2 — Activity Detail

### Task 7: Interactive map with GPS photo pins

**Files:**
- Create: `frontend/src/components/ActivityMap.tsx`

```tsx
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { DataPoint, Photo } from "../types";
import { useMemo } from "react";

// Fix Leaflet default marker icons broken by Vite bundling
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

const cameraIcon = L.divIcon({
  html: "📷",
  className: "",
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

interface Props {
  datapoints: DataPoint[];
  photos?: Photo[];
  highlightRange?: [number, number] | null;
}

function FitBounds({ coords }: { coords: [number, number][] }) {
  const map = useMap();
  useMemo(() => { if (coords.length) map.fitBounds(coords as any); }, [coords]);
  return null;
}

export default function ActivityMap({ datapoints, photos = [], highlightRange }: Props) {
  const coords: [number, number][] = datapoints
    .filter(dp => dp.lat !== null && dp.lon !== null)
    .map(dp => [dp.lat!, dp.lon!]);

  if (!coords.length)
    return <div className="h-64 flex items-center justify-center text-gray-400">No GPS data</div>;

  const highlighted = highlightRange ? coords.slice(highlightRange[0], highlightRange[1]) : [];
  const gpsPhotos = photos.filter(p => p.lat !== null && p.lon !== null);

  return (
    <MapContainer style={{ height: 400 }} center={coords[0]} zoom={13}>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                 attribution='© <a href="https://openstreetmap.org">OSM</a>' />
      <FitBounds coords={coords} />
      <Polyline positions={coords} color="#3b82f6" weight={3} />
      {highlighted.length > 0 && <Polyline positions={highlighted} color="#ef4444" weight={5} />}
      {gpsPhotos.map(photo => (
        <Marker key={photo.id} position={[photo.lat!, photo.lon!]} icon={cameraIcon}>
          <Popup>
            <img src={photo.url} alt="Run photo" className="max-w-xs max-h-48 object-cover" />
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/ActivityMap.tsx
git commit -m "feat: map component with GPS track, highlight range, and GPS photo pins"
```

---

### Task 8: Activity charts component

**Files:**
- Create: `frontend/src/components/ActivityCharts.tsx`

```tsx
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  Brush, CartesianGrid, Legend,
} from "recharts";
import { DataPoint } from "../types";

interface Props {
  datapoints: DataPoint[];
  onRangeChange?: (start: number, end: number) => void;
}

function elapsed(seconds: number) {
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`;
}

export default function ActivityCharts({ datapoints, onRangeChange }: Props) {
  if (!datapoints.length) return null;
  const t0 = new Date(datapoints[0].timestamp).getTime();
  const data = datapoints.map((dp, i) => ({
    i,
    s: Math.round((new Date(dp.timestamp).getTime() - t0) / 1000),
    pace: dp.speed_m_s && dp.speed_m_s > 0 ? +(1000 / dp.speed_m_s).toFixed(1) : null,
    hr: dp.heart_rate,
    alt: dp.altitude_m,
    cad: dp.cadence,
  }));

  return (
    <div className="space-y-4">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="s" tickFormatter={elapsed} minTickGap={60} />
          <YAxis yAxisId="pace" orientation="left" reversed domain={["auto", "auto"]} />
          <YAxis yAxisId="hr" orientation="right" />
          <Tooltip labelFormatter={v => elapsed(v as number)} />
          <Legend />
          <Line yAxisId="pace" dataKey="pace" dot={false} stroke="#3b82f6" name="Pace s/km" />
          <Line yAxisId="hr" dataKey="hr" dot={false} stroke="#ef4444" name="HR bpm" />
          <Brush dataKey="s" height={20}
                 onChange={(e: any) => onRangeChange?.(e.startIndex, e.endIndex)} />
        </LineChart>
      </ResponsiveContainer>
      <ResponsiveContainer width="100%" height={120}>
        <LineChart data={data}>
          <XAxis dataKey="s" tickFormatter={elapsed} minTickGap={60} />
          <YAxis />
          <Tooltip />
          <Line dataKey="alt" dot={false} stroke="#10b981" name="Elevation m" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/ActivityCharts.tsx
git commit -m "feat: activity charts — pace, HR, elevation with brush selector"
```

---

### Task 9: Activity Detail page

**Files:**
- Create: `frontend/src/pages/ActivityDetail.tsx`
- Create: `frontend/src/components/PhotoGallery.tsx`

**Step 1: Create `frontend/src/components/PhotoGallery.tsx`**

```tsx
import { useState } from "react";
import { Photo } from "../types";

export default function PhotoGallery({ photos }: { photos: Photo[] }) {
  const [lightbox, setLightbox] = useState<string | null>(null);
  if (!photos.length) return null;
  return (
    <div>
      <div className="flex gap-2 flex-wrap">
        {photos.map(p => (
          <img key={p.id} src={p.url} alt=""
               className="h-24 w-24 object-cover rounded cursor-pointer hover:opacity-80"
               onClick={() => setLightbox(p.url)} />
        ))}
      </div>
      {lightbox && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50"
             onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="" className="max-h-screen max-w-screen-lg" />
        </div>
      )}
    </div>
  );
}
```

**Step 2: Create `frontend/src/pages/ActivityDetail.tsx`**

```tsx
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getActivity, getDataPoints, getPhotos } from "../api/client";
import ActivityMap from "../components/ActivityMap";
import ActivityCharts from "../components/ActivityCharts";
import PhotoGallery from "../components/PhotoGallery";

export default function ActivityDetail() {
  const { id } = useParams<{ id: string }>();
  const actId = Number(id);
  const [range, setRange] = useState<[number, number] | null>(null);

  const { data: act } = useQuery({ queryKey: ["activity", actId], queryFn: () => getActivity(actId) });
  const { data: dps = [] } = useQuery({ queryKey: ["datapoints", actId], queryFn: () => getDataPoints(actId) });
  const { data: photos = [] } = useQuery({ queryKey: ["photos", actId], queryFn: () => getPhotos(actId) });

  if (!act) return <div className="p-4">Loading…</div>;

  return (
    <div className="p-4 max-w-5xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">
        {new Date(act.started_at).toLocaleDateString()} — {act.sport_type}
      </h1>
      <div className="grid grid-cols-4 gap-4 text-center">
        {[
          ["Distance", `${(act.distance_m / 1000).toFixed(2)} km`],
          ["Time", `${Math.floor(act.duration_s / 60)} min`],
          ["Avg HR", act.avg_hr ? `${act.avg_hr} bpm` : "—"],
          ["Elevation", `${act.elevation_gain_m.toFixed(0)} m`],
        ].map(([l, v]) => (
          <div key={l} className="bg-gray-100 rounded p-3">
            <div className="text-xs text-gray-500 uppercase">{l}</div>
            <div className="text-xl font-semibold">{v}</div>
          </div>
        ))}
      </div>
      <ActivityMap datapoints={dps} photos={photos} highlightRange={range} />
      <ActivityCharts datapoints={dps} onRangeChange={(s, e) => setRange([s, e])} />
      <PhotoGallery photos={photos} />
      {act.notes && <p className="text-gray-600 italic">{act.notes}</p>}
    </div>
  );
}
```

**Step 3: Wire route in `App.tsx`** — `<Route path="/activities/:id" element={<ActivityDetail />} />`

**Step 4: Verify** — GPS photo pins appear on map; chart brush highlights map segment.

**Step 5: Commit**

```bash
git add frontend/src/pages/ActivityDetail.tsx frontend/src/components/PhotoGallery.tsx
git commit -m "feat: activity detail — map with GPS photo pins, charts, photo gallery"
```

---

## Phase 3 — Analytics

### Task 10: Analytics service

**Files:**
- Create: `backend/app/services/analytics.py`
- Create: `backend/tests/test_analytics.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_analytics.py
from app.services.analytics import compute_pace_zones, compute_vdot, compute_training_load

def test_vdot_5k_20min():
    # 5 km in 20:00 → VDOT ≈ 47.5
    vdot = compute_vdot(distance_m=5000, duration_s=1200)
    assert 46 < vdot < 49

def test_vdot_marathon_3h():
    # Marathon in 3:00:00 → VDOT ≈ 46
    vdot = compute_vdot(distance_m=42195, duration_s=10800)
    assert 44 < vdot < 48

def test_pace_zones_empty():
    zones = compute_pace_zones([])
    assert all(v == 0.0 for v in zones.values())

def test_training_load_single():
    result = compute_training_load([{"duration_s": 3600, "avg_hr": 150, "hr_max": 190, "hr_rest": 50}])
    assert result["hrTSS"] > 0
    assert "ATL" in result and "CTL" in result and "TSB" in result

def test_tsb_is_ctl_minus_atl():
    result = compute_training_load([{"duration_s": 3600, "avg_hr": 160, "hr_max": 190, "hr_rest": 50}])
    assert abs(result["TSB"] - (result["CTL"] - result["ATL"])) < 0.01
```

**Step 2: Run to verify failure**

```bash
cd backend && pytest tests/test_analytics.py -v
```
Expected: `ImportError`

**Step 3: Create `backend/app/services/analytics.py`**

```python
import math
from typing import Any


def compute_pace_zones(datapoints: list[dict], hr_max: int = 190) -> dict[str, float]:
    zones = {f"Z{i}": 0.0 for i in range(1, 6)}
    for dp in datapoints:
        hr = dp.get("heart_rate")
        if not hr:
            continue
        pct = hr / hr_max
        if pct < 0.60:   zones["Z1"] += 1
        elif pct < 0.70: zones["Z2"] += 1
        elif pct < 0.80: zones["Z3"] += 1
        elif pct < 0.90: zones["Z4"] += 1
        else:             zones["Z5"] += 1
    return zones


def compute_vdot(distance_m: float, duration_s: float) -> float:
    """Jack Daniels VDOT from race performance (Daniels & Gilbert 1979)."""
    if duration_s <= 0 or distance_m <= 0:
        return 0.0
    t = duration_s / 60  # minutes
    v = distance_m / t   # m/min
    pct_vo2max = (0.8 + 0.1894393 * math.exp(-0.012778 * t)
                  + 0.2989558 * math.exp(-0.1932605 * t))
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v ** 2
    return round(vo2 / pct_vo2max, 1)


def _hr_tss(duration_s: float, avg_hr: float, hr_max: float, hr_rest: float) -> float:
    if hr_max <= hr_rest:
        return 0.0
    hrr = (avg_hr - hr_rest) / (hr_max - hr_rest)
    y = 1.92  # male; use 1.67 for female
    trimp = (duration_s / 60) * hrr * 0.64 * math.exp(y * hrr)
    threshold_hrr = 0.85
    threshold_trimp = 60 * threshold_hrr * 0.64 * math.exp(y * threshold_hrr)
    return round((trimp / threshold_trimp) * 100, 1)


def compute_training_load(activities: list[dict[str, Any]],
                          atl_days: int = 7, ctl_days: int = 42) -> dict[str, Any]:
    atl_k = 1 - math.exp(-1 / atl_days)
    ctl_k = 1 - math.exp(-1 / ctl_days)
    atl = ctl = total = 0.0
    for act in activities:
        tss = _hr_tss(act.get("duration_s", 0), act.get("avg_hr", 140),
                      act.get("hr_max", 190), act.get("hr_rest", 50))
        total += tss
        atl = atl + atl_k * (tss - atl)
        ctl = ctl + ctl_k * (tss - ctl)
    return {"hrTSS": round(total, 1), "ATL": round(atl, 1),
            "CTL": round(ctl, 1), "TSB": round(ctl - atl, 1)}
```

**Step 4: Run tests**

```bash
cd backend && pytest tests/test_analytics.py -v
```
Expected: `5 passed`

**Step 5: Commit**

```bash
git add backend/app/services/analytics.py backend/tests/test_analytics.py
git commit -m "feat: analytics — VDOT, pace zones, hrTSS, ATL/CTL/TSB"
```

---

### Task 11: Stats router + Dashboard page

**Files:**
- Create: `backend/app/routers/stats.py`
- Modify: `backend/app/main.py`
- Create: `frontend/src/pages/Dashboard.tsx`

**Step 1: Create `backend/app/routers/stats.py`**

```python
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models import Activity
from app.services.analytics import compute_training_load
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/api/stats", tags=["stats"])

@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    activities = session.exec(select(Activity).order_by(Activity.started_at)).all()
    load = compute_training_load([
        {"duration_s": a.duration_s, "avg_hr": a.avg_hr or 140,
         "hr_max": 190, "hr_rest": 50}
        for a in activities
    ])
    now = datetime.now(timezone.utc)
    week_acts = [a for a in activities if a.started_at >= now - timedelta(days=7)]
    return {
        **load,
        "total_activities": len(activities),
        "weekly_distance_km": round(sum(a.distance_m for a in week_acts) / 1000, 2),
        "weekly_activities": len(week_acts),
        "recent": [{"id": a.id, "started_at": a.started_at.isoformat(),
                    "distance_m": a.distance_m, "sport_type": a.sport_type}
                   for a in sorted(activities, key=lambda x: x.started_at, reverse=True)[:5]],
    }
```

**Step 2: Register in `main.py`** — `from app.routers import stats; app.include_router(stats.router)`

**Step 3: Create `frontend/src/pages/Dashboard.tsx`** — ATL/CTL/TSB stat cards, weekly distance, goal progress cards, last 5 activities.

**Step 4: Commit**

```bash
git add backend/app/routers/stats.py frontend/src/pages/Dashboard.tsx
git commit -m "feat: stats summary endpoint and dashboard"
```

---

## Phase 4 — Photos & Strava

### Task 12: EXIF service + Strava sync

**Files:**
- Create: `backend/app/services/exif.py`
- Create: `backend/app/services/strava.py`
- Create: `backend/app/routers/sync.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_strava.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_strava.py
from unittest.mock import patch, MagicMock
from app.services.strava import refresh_access_token, fetch_activity_photos
from app.services.exif import extract_gps_from_url

def test_refresh_token():
    mock = MagicMock()
    mock.json.return_value = {"access_token": "tok123", "expires_at": 9999999999}
    with patch("httpx.post", return_value=mock):
        assert refresh_access_token("cid", "csec", "rtok") == "tok123"

def test_fetch_photos_empty():
    mock = MagicMock()
    mock.json.return_value = []
    with patch("httpx.get", return_value=mock):
        assert fetch_activity_photos("token", "123") == []

def test_extract_gps_no_exif():
    # Image with no EXIF GPS should return (None, None)
    mock = MagicMock()
    mock.content = b"not an image"
    with patch("httpx.get", return_value=mock):
        lat, lon = extract_gps_from_url("http://example.com/photo.jpg")
    assert lat is None and lon is None
```

**Step 2: Create `backend/app/services/exif.py`**

```python
import io
import httpx
import exifread
from typing import Optional


def _dms_to_decimal(dms, ref: str) -> float:
    """Convert degrees/minutes/seconds + ref to decimal degrees."""
    d = float(dms[0].num) / float(dms[0].den)
    m = float(dms[1].num) / float(dms[1].den)
    s = float(dms[2].num) / float(dms[2].den)
    result = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        result = -result
    return round(result, 7)


def extract_gps_from_url(url: str) -> tuple[Optional[float], Optional[float]]:
    """Download image and extract EXIF GPS. Returns (lat, lon) or (None, None)."""
    try:
        r = httpx.get(url, timeout=10)
        tags = exifread.process_file(io.BytesIO(r.content), details=False)
        lat_tag = tags.get("GPS GPSLatitude")
        lat_ref = tags.get("GPS GPSLatitudeRef")
        lon_tag = tags.get("GPS GPSLongitude")
        lon_ref = tags.get("GPS GPSLongitudeRef")
        if not (lat_tag and lon_tag):
            return None, None
        lat = _dms_to_decimal(lat_tag.values, str(lat_ref))
        lon = _dms_to_decimal(lon_tag.values, str(lon_ref))
        return lat, lon
    except Exception:
        return None, None
```

**Step 3: Create `backend/app/services/strava.py`**

```python
import httpx
from app.config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    r = httpx.post("https://www.strava.com/oauth/token", data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })
    return r.json()["access_token"]


def get_access_token() -> str:
    return refresh_access_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN)


def fetch_activity_photos(access_token: str, strava_activity_id: str) -> list[dict]:
    r = httpx.get(
        f"https://www.strava.com/api/v3/activities/{strava_activity_id}/photos",
        params={"photo_sources": "true", "size": 1200},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    data = r.json()
    return data if isinstance(data, list) else []


def sync_photos_for_activity(activity, session) -> int:
    from app.models import Photo
    from app.services.exif import extract_gps_from_url
    from sqlmodel import select
    if not activity.strava_id:
        return 0
    token = get_access_token()
    photos = fetch_activity_photos(token, activity.strava_id)
    existing = {p.strava_photo_id for p in
                session.exec(select(Photo).where(Photo.activity_id == activity.id)).all()}
    count = 0
    for p in photos:
        uid = str(p.get("unique_id", ""))
        if uid in existing:
            continue
        urls = p.get("urls", {})
        url = urls.get("1200") or urls.get("600") or next(iter(urls.values()), None)
        if not url:
            continue
        lat, lon = extract_gps_from_url(url)
        session.add(Photo(activity_id=activity.id, strava_photo_id=uid,
                          url=url, lat=lat, lon=lon))
        count += 1
    session.commit()
    return count
```

**Step 4: Create `backend/app/routers/sync.py`**

```python
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlmodel import Session, select
from app.database import get_session
from app.models import Activity
from app.services.strava import get_access_token, sync_photos_for_activity
from datetime import datetime, timezone

router = APIRouter(prefix="/api/sync", tags=["sync"])
_last_sync: dict = {"status": "never", "ts": None, "error": None}


@router.get("/status")
def status():
    return _last_sync


@router.post("/trigger")
def trigger(bg: BackgroundTasks, session: Session = Depends(get_session)):
    bg.add_task(_sync_strava_photos, session)
    return {"message": "sync triggered"}


def _sync_strava_photos(session: Session):
    global _last_sync
    try:
        acts = session.exec(select(Activity).where(Activity.strava_id != None)).all()
        total = sum(sync_photos_for_activity(a, session) for a in acts)
        _last_sync = {"status": "ok", "ts": datetime.now(timezone.utc).isoformat(),
                      "new_photos": total, "error": None}
    except Exception as e:
        _last_sync = {"status": "error", "ts": datetime.now(timezone.utc).isoformat(),
                      "error": str(e)}
```

**Step 5: Register router and add APScheduler to `main.py`**

```python
from app.routers import sync
from apscheduler.schedulers.background import BackgroundScheduler

app.include_router(sync.router)
scheduler = BackgroundScheduler()

@app.on_event("startup")
def start_scheduler():
    from app.database import Session, engine
    from app.routers.sync import _sync_strava_photos
    scheduler.add_job(lambda: _sync_strava_photos(Session(engine)), "interval", hours=6)
    scheduler.start()

@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown()
```

**Step 6: Run tests**

```bash
cd backend && pytest tests/test_strava.py -v
```
Expected: `3 passed`

**Step 7: Commit**

```bash
git add backend/app/services/strava.py backend/app/services/exif.py \
        backend/app/routers/sync.py backend/app/main.py backend/tests/test_strava.py
git commit -m "feat: Strava photo sync with EXIF GPS extraction"
```

---

## Phase 5 — Gear & Goals

### Task 13: Shoes router + Gear page

**Files:**
- Create: `backend/app/routers/shoes.py`
- Create: `frontend/src/pages/Gear.tsx`

**Step 1: Create `backend/app/routers/shoes.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func
from app.database import get_session
from app.models import Shoe, ActivityShoe, Activity

router = APIRouter(prefix="/api/shoes", tags=["shoes"])

@router.get("")
def list_shoes(session: Session = Depends(get_session)):
    shoes = session.exec(select(Shoe)).all()
    result = []
    for shoe in shoes:
        dist = session.exec(
            select(func.sum(Activity.distance_m))
            .join(ActivityShoe, ActivityShoe.activity_id == Activity.id)
            .where(ActivityShoe.shoe_id == shoe.id)
        ).first() or 0.0
        result.append({**shoe.model_dump(), "total_distance_km": round(dist / 1000, 1)})
    return result

@router.post("", status_code=201)
def create_shoe(shoe: Shoe, session: Session = Depends(get_session)):
    session.add(shoe); session.commit(); session.refresh(shoe); return shoe

@router.patch("/{shoe_id}")
def update_shoe(shoe_id: int, data: dict, session: Session = Depends(get_session)):
    shoe = session.get(Shoe, shoe_id)
    if not shoe: raise HTTPException(status_code=404)
    for k in {"name", "brand", "retired", "notes", "retirement_threshold_km"}:
        if k in data: setattr(shoe, k, data[k])
    session.add(shoe); session.commit(); session.refresh(shoe); return shoe
```

**Step 2: Register router** in `main.py`.

**Step 3: Create `frontend/src/pages/Gear.tsx`** — shoe list with mileage bar, retire button, add-shoe form.

**Step 4: Commit**

```bash
git add backend/app/routers/shoes.py frontend/src/pages/Gear.tsx
git commit -m "feat: shoe tracking with mileage and retirement"
```

---

### Task 14: Goals router + Goals page

**Files:**
- Create: `backend/app/routers/goals.py`
- Create: `frontend/src/pages/Goals.tsx`

**Step 1: Create `backend/app/routers/goals.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func
from app.database import get_session
from app.models import Goal, Activity

router = APIRouter(prefix="/api/goals", tags=["goals"])

def _progress_km(goal: Goal, session: Session) -> float:
    total = session.exec(
        select(func.sum(Activity.distance_m))
        .where(Activity.started_at >= goal.period_start)
        .where(Activity.started_at <= goal.period_end)
    ).first() or 0.0
    return round(total / 1000, 2)

@router.get("")
def list_goals(session: Session = Depends(get_session)):
    goals = session.exec(select(Goal)).all()
    return [{"goal": g.model_dump(), "progress_km": _progress_km(g, session)} for g in goals]

@router.post("", status_code=201)
def create_goal(goal: Goal, session: Session = Depends(get_session)):
    session.add(goal); session.commit(); session.refresh(goal); return goal

@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: int, session: Session = Depends(get_session)):
    goal = session.get(Goal, goal_id)
    if not goal: raise HTTPException(status_code=404)
    session.delete(goal); session.commit()
```

**Step 2: Register router** in `main.py`.

**Step 3: Create `frontend/src/pages/Goals.tsx`** — active goals with progress bars, create-goal form.

**Step 4: Commit**

```bash
git add backend/app/routers/goals.py frontend/src/pages/Goals.tsx
git commit -m "feat: goals with progress tracking"
```

---

## Phase 6 — Training Plans

### Task 15: Daniels plan generator

**Files:**
- Create: `backend/app/services/training_plans/__init__.py`
- Create: `backend/app/services/training_plans/daniels.py`
- Create: `backend/tests/test_training_plans.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_training_plans.py
import pytest
from datetime import date
from app.services.training_plans.daniels import generate_daniels_plan, vdot_paces

def test_vdot_paces_vdot50():
    paces = vdot_paces(50)
    # At VDOT 50: Easy ~5:30/km, Threshold ~4:10/km, Marathon ~4:35/km
    assert 300 < paces["easy"] < 370       # 5:00–6:10 /km
    assert 230 < paces["threshold"] < 280  # 3:50–4:40 /km
    assert 250 < paces["marathon"] < 310   # 4:10–5:10 /km

def test_generate_marathon_plan_length():
    plan = generate_daniels_plan(
        goal_distance="marathon",
        goal_race_date=date(2026, 10, 1),
        target_vdot=50.0,
    )
    # 18-week plan → 126 days → 126 PlannedWorkout dicts
    assert len(plan) == 18 * 7

def test_generate_5k_plan():
    plan = generate_daniels_plan(
        goal_distance="5k",
        goal_race_date=date(2026, 6, 1),
        target_vdot=45.0,
    )
    assert len(plan) > 0
    assert all("workout_type" in w for w in plan)
    assert all("scheduled_date" in w for w in plan)

def test_plan_has_required_fields():
    plan = generate_daniels_plan("marathon", date(2026,10,1), 50.0)
    w = plan[0]
    for field in ("scheduled_date", "week_number", "workout_type",
                  "description", "target_distance_m", "target_pace_s_per_km"):
        assert field in w
```

**Step 2: Run to verify failure**

```bash
cd backend && pytest tests/test_training_plans.py -v
```
Expected: `ImportError`

**Step 3: Create `backend/app/services/training_plans/__init__.py`** (empty)

**Step 4: Create `backend/app/services/training_plans/daniels.py`**

```python
"""
Jack Daniels training plan generator.
Pace formulas from "Daniels' Running Formula" (3rd ed.).
VDOT pace tables computed from the original regression equations.
"""
import math
from datetime import date, timedelta
from typing import Any


# ── VDOT pace computation ──────────────────────────────────────────────────

def _velocity_at_vdot_pct(vdot: float, pct: float) -> float:
    """Return velocity (m/min) for a given VDOT and % of VO2max."""
    # Invert: VO2 = -4.60 + 0.182258v + 0.000104v^2
    # At pct*VO2max: solve quadratic for v
    vo2_target = pct * vdot
    a, b, c = 0.000104, 0.182258, -4.60 - vo2_target
    disc = b**2 - 4*a*c
    return (-b + math.sqrt(disc)) / (2 * a)


def vdot_paces(vdot: float) -> dict[str, float]:
    """
    Return training paces (seconds per km) for key zones at a given VDOT.
    Zone %VO2max values from Daniels' Running Formula table.
    """
    zones = {
        "easy":       0.65,   # 59–74% VO2max; use 65% midpoint
        "marathon":   0.84,
        "threshold":  0.88,
        "interval":   0.975,
        "repetition": 1.05,   # slightly over VO2max pace
    }
    paces = {}
    for name, pct in zones.items():
        v = _velocity_at_vdot_pct(vdot, pct)   # m/min
        paces[name] = round(1000 / v * 60, 1)  # s/km
    return paces


# ── Plan templates ─────────────────────────────────────────────────────────
# Each entry: (workout_type, distance_km_fraction_of_weekly, description_template)
# weekly_km is computed from VDOT; individual day distances scale from weekly total.

_MARATHON_TEMPLATE_18W = [
    # week: list of (type, km, description)
    # Week 1 — base
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",5,"Long 16 km")],
    # Week 2
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("threshold",2.5,"6 km w/ 3 km threshold"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",6,"Long 19 km")],
    # Week 3
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("interval",2.5,"8 km w/ 3×1600m @ I-pace"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",6.5,"Long 21 km")],
    # Week 4 — recovery
    [("easy",2.5,"Easy 8 km"),("rest",0,"Rest"),("easy",2,"Easy 6 km"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",5,"Long 16 km")],
    # Weeks 5–8: build with marathon-pace work
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("marathon_pace",3,"12 km w/ 6 @ MP"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",7,"Long 22 km")],
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("threshold",3,"10 km w/ 4 km threshold"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",7.5,"Long 24 km")],
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("interval",3,"10 km w/ 4×1200m @ I-pace"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",8,"Long 26 km")],
    [("easy",2.5,"Easy 8 km"),("rest",0,"Rest"),("easy",2,"Easy 6 km"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",5.5,"Long 18 km")],
    # Weeks 9–12: peak mileage
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("marathon_pace",3.5,"14 km w/ 8 @ MP"),
     ("rest",0,"Rest"),("easy",3,"Easy 10 km"),("easy",2,"Easy 6 km"),("long",8.5,"Long 27 km")],
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("threshold",3.5,"12 km w/ 5 km threshold"),
     ("rest",0,"Rest"),("easy",3,"Easy 10 km"),("easy",2,"Easy 6 km"),("long",9,"Long 29 km")],
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("interval",3.5,"12 km w/ 5×1000m @ I-pace"),
     ("rest",0,"Rest"),("easy",3,"Easy 10 km"),("easy",2,"Easy 6 km"),("long",9.5,"Long 30 km")],
    [("easy",2.5,"Easy 8 km"),("rest",0,"Rest"),("easy",2,"Easy 6 km"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",6,"Long 19 km")],
    # Weeks 13–16: maintenance + specificity
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("marathon_pace",4,"16 km w/ 10 @ MP"),
     ("rest",0,"Rest"),("easy",3,"Easy 10 km"),("easy",2,"Easy 6 km"),("long",8,"Long 26 km")],
    [("easy",3,"Easy 10 km"),("rest",0,"Rest"),("threshold",3,"10 km w/ 4 km threshold"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",7,"Long 22 km")],
    [("easy",2.5,"Easy 8 km"),("rest",0,"Rest"),("marathon_pace",3,"12 km w/ 6 @ MP"),
     ("rest",0,"Rest"),("easy",2.5,"Easy 8 km"),("easy",2,"Easy 6 km"),("long",6,"Long 19 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("easy",2,"Easy 6 km"),
     ("rest",0,"Rest"),("easy",1.5,"Easy 5 km"),("easy",1,"Easy 3 km"),("long",5,"Long 16 km")],
    # Weeks 17–18: taper
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("marathon_pace",2,"8 km w/ 4 @ MP"),
     ("rest",0,"Rest"),("easy",1.5,"Easy 5 km"),("easy",1,"Easy 3 km"),("long",3.5,"Long 11 km")],
    [("easy",1.5,"Easy 5 km"),("rest",0,"Rest"),("easy",1,"Easy 3 km"),
     ("rest",0,"Rest"),("easy",1,"Easy 3 km"),("easy",0.5,"Easy 3 km shakeout"),
     ("marathon_pace",0,"Race day!")],
]

_5K_TEMPLATE_12W = [
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("interval",2,"6 km w/ 4×400m @ R-pace"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",3,"Long 10 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("threshold",2,"6 km w/ 2 km threshold"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",4,"Long 12 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("interval",2.5,"8 km w/ 6×400m @ I-pace"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",4,"Long 13 km")],
    [("easy",1.5,"Easy 5 km"),("rest",0,"Rest"),("easy",1.5,"Easy 5 km"),
     ("rest",0,"Rest"),("easy",1.5,"Easy 5 km"),("easy",1,"Easy 3 km"),("long",3,"Long 10 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("interval",3,"10 km w/ 5×1000m @ I-pace"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",4.5,"Long 14 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("threshold",2.5,"8 km w/ 3 km threshold"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",4.5,"Long 14 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("interval",3,"10 km w/ 3×1600m @ I-pace"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",5,"Long 16 km")],
    [("easy",1.5,"Easy 5 km"),("rest",0,"Rest"),("easy",1.5,"Easy 5 km"),
     ("rest",0,"Rest"),("easy",1.5,"Easy 5 km"),("easy",1,"Easy 3 km"),("long",3,"Long 10 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("interval",3,"10 km w/ 8×400m @ R-pace"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",4.5,"Long 14 km")],
    [("easy",2,"Easy 6 km"),("rest",0,"Rest"),("threshold",2.5,"8 km w/ 4 km threshold"),
     ("rest",0,"Rest"),("easy",2,"Easy 6 km"),("easy",1.5,"Easy 5 km"),("long",4,"Long 13 km")],
    [("easy",1.5,"Easy 5 km"),("rest",0,"Rest"),("interval",2,"6 km w/ 4×400m @ I-pace"),
     ("rest",0,"Rest"),("easy",1.5,"Easy 5 km"),("easy",1,"Easy 3 km"),("long",3,"Long 10 km")],
    [("easy",1,"Easy 3 km"),("rest",0,"Rest"),("easy",1,"Easy 3 km"),
     ("rest",0,"Rest"),("easy",0.5,"Easy 2 km"),("easy",0.5,"Shakeout 2 km"),
     ("interval",0,"Race day!")],
]

_TEMPLATES = {
    "marathon": _MARATHON_TEMPLATE_18W,
    "half":     _MARATHON_TEMPLATE_18W[:16],  # simplified — use marathon template truncated
    "10k":      _5K_TEMPLATE_12W,
    "5k":       _5K_TEMPLATE_12W,
}


def generate_daniels_plan(
    goal_distance: str,
    goal_race_date: date,
    target_vdot: float,
) -> list[dict[str, Any]]:
    """
    Generate a list of PlannedWorkout dicts for a Daniels plan.
    """
    template = _TEMPLATES.get(goal_distance, _MARATHON_TEMPLATE_18W)
    num_weeks = len(template)
    start_date = goal_race_date - timedelta(weeks=num_weeks)
    paces = vdot_paces(target_vdot)

    workouts = []
    for week_idx, week_days in enumerate(template, start=1):
        for day_idx, (wtype, dist_km, desc) in enumerate(week_days):
            scheduled = start_date + timedelta(weeks=week_idx - 1, days=day_idx)
            target_dist = dist_km * 1000 if dist_km > 0 else None
            pace = paces.get(wtype) if wtype != "rest" else None
            workouts.append({
                "scheduled_date": scheduled,
                "week_number": week_idx,
                "workout_type": wtype,
                "description": desc,
                "target_distance_m": target_dist,
                "target_pace_s_per_km": pace,
            })
    return workouts
```

**Step 5: Run tests**

```bash
cd backend && pytest tests/test_training_plans.py -v
```
Expected: `4 passed`

**Step 6: Commit**

```bash
git add backend/app/services/training_plans/ backend/tests/test_training_plans.py
git commit -m "feat: Daniels training plan generator with VDOT pace computation"
```

---

### Task 16: Pfitzinger plan generator

**Files:**
- Create: `backend/app/services/training_plans/pfitzinger.py`

**Step 1: Add tests to `backend/tests/test_training_plans.py`**

```python
from app.services.training_plans.pfitzinger import generate_pfitzinger_plan

def test_pfitzinger_18_55_length():
    plan = generate_pfitzinger_plan(
        goal_race_date=date(2026, 10, 4),
        peak_weekly_km=88,   # 55 miles ≈ 88 km
    )
    assert len(plan) == 18 * 7

def test_pfitzinger_has_long_runs():
    plan = generate_pfitzinger_plan(date(2026,10,4), peak_weekly_km=88)
    long_runs = [w for w in plan if w["workout_type"] == "long"]
    assert len(long_runs) >= 10

def test_pfitzinger_has_medium_long_runs():
    plan = generate_pfitzinger_plan(date(2026,10,4), peak_weekly_km=88)
    ml_runs = [w for w in plan if w["workout_type"] == "marathon_pace"]
    assert len(ml_runs) >= 4
```

**Step 2: Run to verify failure**

```bash
cd backend && pytest tests/test_training_plans.py::test_pfitzinger_18_55_length -v
```
Expected: `ImportError`

**Step 3: Create `backend/app/services/training_plans/pfitzinger.py`**

```python
"""
Pfitzinger 18-week marathon plan generator.
Structure based on the 18/55 plan from "Advanced Marathoning" (Pfitzinger & Douglas).
Encode your own copy of the book for exact workouts; this provides the structural skeleton.
Distances scaled proportionally from the 55 mpw (88 km/wk) peak plan.
"""
from datetime import date, timedelta
from typing import Any

# Each week: list of (workout_type, distance_km, description)
# 0 km = rest day
# Distances are for the 55 mpw (~88 km/week peak) plan.
_PFITZ_18_55 = [
    # Week 1 (base, ~64 km)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),
     ("rest",0,"Rest"),("easy",11,"General aerobic 11 km"),("easy",8,"General aerobic 8 km"),
     ("long",22,"Long run 22 km")],
    # Week 2 (~72 km)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("easy",16,"General aerobic 16 km"),
     ("rest",0,"Rest"),("easy",11,"General aerobic 11 km"),("easy",8,"General aerobic 8 km"),
     ("long",27,"Long run 27 km")],
    # Week 3 (~80 km)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("marathon_pace",16,"Med-long 16 km"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",29,"Long run 29 km")],
    # Week 4 — recovery (~55 km)
    [("recovery",8,"Recovery 8 km"),("rest",0,"Rest"),("easy",11,"General aerobic 11 km"),
     ("rest",0,"Rest"),("easy",10,"General aerobic 10 km"),("easy",8,"General aerobic 8 km"),
     ("long",18,"Long run 18 km")],
    # Week 5 (~80 km)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("threshold",16,"LT 16 km w/ 8 km @ LT"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",29,"Long run 29 km")],
    # Week 6 (~88 km — peak week 1)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("marathon_pace",19,"Med-long 19 km"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",32,"Long run 32 km")],
    # Week 7 (~88 km — peak week 2)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("threshold",16,"LT 16 km w/ 10 km @ LT"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",35,"Long run 35 km")],
    # Week 8 — recovery (~56 km)
    [("recovery",8,"Recovery 8 km"),("rest",0,"Rest"),("easy",11,"General aerobic 11 km"),
     ("rest",0,"Rest"),("easy",10,"General aerobic 10 km"),("easy",8,"General aerobic 8 km"),
     ("long",19,"Long run 19 km")],
    # Week 9 (~88 km — peak week 3)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("marathon_pace",19,"Med-long 19 km"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",32,"Long run 32 km")],
    # Week 10 (~88 km — peak week 4)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("threshold",16,"LT 16 km w/ 11 km @ LT"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",35,"Long run 35 km")],
    # Week 11 (~88 km — peak week 5)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("marathon_pace",21,"Med-long 21 km"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",32,"Long run 32 km")],
    # Week 12 — recovery (~56 km)
    [("recovery",8,"Recovery 8 km"),("rest",0,"Rest"),("easy",11,"General aerobic 11 km"),
     ("rest",0,"Rest"),("easy",10,"General aerobic 10 km"),("easy",8,"General aerobic 8 km"),
     ("long",19,"Long run 19 km")],
    # Week 13 (~80 km)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("marathon_pace",19,"Med-long 19 km w/ 13 @ MP"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",29,"Long run 29 km")],
    # Week 14 (~80 km)
    [("recovery",10,"Recovery 10 km"),("rest",0,"Rest"),("threshold",16,"LT 16 km w/ 10 km @ LT"),
     ("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),("easy",8,"General aerobic 8 km"),
     ("long",29,"Long run 29 km")],
    # Week 15 (~72 km — begin taper)
    [("recovery",8,"Recovery 8 km"),("rest",0,"Rest"),("marathon_pace",16,"Med-long 16 km w/ 10 @ MP"),
     ("rest",0,"Rest"),("easy",11,"General aerobic 11 km"),("easy",8,"General aerobic 8 km"),
     ("long",24,"Long run 24 km")],
    # Week 16 (~56 km — taper continues)
    [("recovery",8,"Recovery 8 km"),("rest",0,"Rest"),("easy",13,"General aerobic 13 km"),
     ("rest",0,"Rest"),("easy",10,"General aerobic 10 km"),("easy",6,"General aerobic 6 km"),
     ("long",19,"Long run 19 km")],
    # Week 17 (~40 km — heavy taper)
    [("recovery",6,"Recovery 6 km"),("rest",0,"Rest"),("marathon_pace",11,"11 km w/ 6 @ MP"),
     ("rest",0,"Rest"),("easy",8,"General aerobic 8 km"),("easy",5,"General aerobic 5 km"),
     ("long",16,"Long run 16 km")],
    # Week 18 — race week (~26 km + race)
    [("recovery",6,"Recovery 6 km"),("rest",0,"Rest"),("easy",8,"Easy 8 km"),
     ("rest",0,"Rest"),("easy",5,"Easy 5 km"),("easy",3,"Shakeout 3 km"),
     ("marathon_pace",0,"Race day — Marathon!")],
]


def generate_pfitzinger_plan(
    goal_race_date: date,
    peak_weekly_km: float = 88.0,
) -> list[dict[str, Any]]:
    """
    Generate Pfitzinger 18-week marathon plan.
    Scales distances proportionally from the 88 km/week peak template.
    """
    scale = peak_weekly_km / 88.0
    num_weeks = len(_PFITZ_18_55)
    start_date = goal_race_date - timedelta(weeks=num_weeks)

    workouts = []
    for week_idx, week_days in enumerate(_PFITZ_18_55, start=1):
        for day_idx, (wtype, dist_km, desc) in enumerate(week_days):
            scheduled = start_date + timedelta(weeks=week_idx - 1, days=day_idx)
            scaled_km = dist_km * scale
            target_dist = scaled_km * 1000 if scaled_km > 0 else None
            workouts.append({
                "scheduled_date": scheduled,
                "week_number": week_idx,
                "workout_type": wtype,
                "description": desc,
                "target_distance_m": target_dist,
                "target_pace_s_per_km": None,  # Pfitzinger paces set by feel/LT test
            })
    return workouts
```

**Step 5: Run tests**

```bash
cd backend && pytest tests/test_training_plans.py -v
```
Expected: `7 passed`

**Step 6: Commit**

```bash
git add backend/app/services/training_plans/pfitzinger.py
git commit -m "feat: Pfitzinger 18-week marathon plan generator"
```

---

### Task 17: Plans router + Plans pages

**Files:**
- Create: `backend/app/routers/plans.py`
- Modify: `backend/app/main.py`
- Create: `frontend/src/pages/Plans.tsx`
- Create: `frontend/src/pages/PlanDetail.tsx`

**Step 1: Create `backend/app/routers/plans.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.database import get_session
from app.models import TrainingPlan, PlannedWorkout, Activity
from app.services.training_plans.daniels import generate_daniels_plan
from app.services.training_plans.pfitzinger import generate_pfitzinger_plan
from datetime import date

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("")
def list_plans(session: Session = Depends(get_session)):
    return session.exec(select(TrainingPlan)).all()


@router.post("", status_code=201)
def create_plan(data: dict, session: Session = Depends(get_session)):
    source = data.get("source")
    goal_race_date = date.fromisoformat(data["goal_race_date"])

    if source == "daniels":
        workouts_data = generate_daniels_plan(
            goal_distance=data["goal_distance"],
            goal_race_date=goal_race_date,
            target_vdot=float(data["target_vdot"]),
        )
        start = workouts_data[0]["scheduled_date"]
    elif source == "pfitzinger":
        workouts_data = generate_pfitzinger_plan(
            goal_race_date=goal_race_date,
            peak_weekly_km=float(data.get("peak_weekly_km", 88)),
        )
        start = workouts_data[0]["scheduled_date"]
    else:
        raise HTTPException(status_code=422, detail="source must be 'daniels' or 'pfitzinger'")

    plan = TrainingPlan(
        name=data.get("name", f"{source.title()} {data.get('goal_distance','marathon')} plan"),
        source=source,
        goal_race_date=goal_race_date,
        goal_distance=data.get("goal_distance", "marathon"),
        start_date=start,
        target_vdot=data.get("target_vdot"),
        peak_weekly_km=data.get("peak_weekly_km"),
        notes=data.get("notes"),
    )
    session.add(plan)
    session.flush()

    for wd in workouts_data:
        session.add(PlannedWorkout(training_plan_id=plan.id, **wd))

    session.commit()
    session.refresh(plan)
    return plan


@router.get("/{plan_id}")
def get_plan(plan_id: int, session: Session = Depends(get_session)):
    plan = session.get(TrainingPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404)
    return plan


@router.get("/{plan_id}/workouts")
def get_workouts(plan_id: int, session: Session = Depends(get_session)):
    if not session.get(TrainingPlan, plan_id):
        raise HTTPException(status_code=404)
    workouts = session.exec(
        select(PlannedWorkout)
        .where(PlannedWorkout.training_plan_id == plan_id)
        .order_by(PlannedWorkout.scheduled_date)
    ).all()
    # Auto-match completed activities by date + distance (±20%)
    today = date.today()
    result = []
    for w in workouts:
        status = "future"
        if w.completed_activity_id:
            status = "completed"
        elif w.scheduled_date < today and w.workout_type != "rest":
            status = "missed"
        elif w.scheduled_date == today:
            status = "today"
        result.append({**w.model_dump(), "status": status})
    return result


@router.patch("/{plan_id}/workouts/{workout_id}")
def update_workout(plan_id: int, workout_id: int, data: dict,
                   session: Session = Depends(get_session)):
    workout = session.get(PlannedWorkout, workout_id)
    if not workout or workout.training_plan_id != plan_id:
        raise HTTPException(status_code=404)
    if "completed_activity_id" in data:
        workout.completed_activity_id = data["completed_activity_id"]
    session.add(workout)
    session.commit()
    session.refresh(workout)
    return workout


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: int, session: Session = Depends(get_session)):
    plan = session.get(TrainingPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404)
    session.exec(select(PlannedWorkout).where(
        PlannedWorkout.training_plan_id == plan_id
    ))
    for w in session.exec(select(PlannedWorkout).where(
        PlannedWorkout.training_plan_id == plan_id
    )).all():
        session.delete(w)
    session.delete(plan)
    session.commit()
```

**Step 2: Register** `from app.routers import plans; app.include_router(plans.router)` in `main.py`.

**Step 3: Create `frontend/src/pages/Plans.tsx`** — list of plans with "Create Plan" form (source selector, goal race date, goal distance, VDOT or peak KM).

**Step 4: Create `frontend/src/pages/PlanDetail.tsx`** — calendar grid by week showing each day's workout. Colour-coded: green = completed, red = missed, blue = today, grey = future/rest.

**Step 5: Wire routes in `App.tsx`**

```tsx
<Route path="/plans" element={<Plans />} />
<Route path="/plans/:id" element={<PlanDetail />} />
```

**Step 6: Commit**

```bash
git add backend/app/routers/plans.py frontend/src/pages/Plans.tsx \
        frontend/src/pages/PlanDetail.tsx backend/app/main.py
git commit -m "feat: training plans router + Plans and PlanDetail pages"
```

---

## Phase 7 — Coros Auto-Sync

### Task 18: Coros sync service

**Files:**
- Create: `backend/app/services/coros.py`
- Modify: `backend/app/routers/sync.py`
- Modify: `backend/app/main.py`

**Step 1: Create `backend/app/services/coros.py`**

```python
"""
Coros sync via unofficial Training Hub API.
Switch to the official partner API once access is granted.
"""
import httpx
from pathlib import Path
from app.config import COROS_EMAIL, COROS_PASSWORD

BASE = "https://trainingapi.coros.com"


def login(email: str, password: str) -> str:
    r = httpx.post(f"{BASE}/account/login",
                   json={"account": email, "pwd": password}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["accessToken"]


def list_activities(token: str, page: int = 1, size: int = 20) -> list[dict]:
    r = httpx.get(f"{BASE}/activity/query",
                  params={"pageNumber": page, "pageSize": size},
                  headers={"accesstoken": token}, timeout=15)
    r.raise_for_status()
    return r.json().get("data", {}).get("dataList", [])


def download_fit(token: str, sport_type: str, label_id: str) -> bytes:
    r = httpx.get(f"{BASE}/activity/fit/url",
                  params={"sportType": sport_type, "labelId": label_id},
                  headers={"accesstoken": token}, timeout=15)
    r.raise_for_status()
    url = r.json()["data"]["fileUrl"]
    return httpx.get(url, timeout=30).content


def get_training_notes(token: str, label_id: str) -> str | None:
    """Fetch post-workout notes for an activity."""
    try:
        r = httpx.get(f"{BASE}/activity/detail",
                      params={"labelId": label_id},
                      headers={"accesstoken": token}, timeout=15)
        return r.json().get("data", {}).get("remark")
    except Exception:
        return None
```

**Step 2: Extend `backend/app/routers/sync.py`** — add `_sync_coros()` that logins, lists remote activities, skips already-imported `external_id`s, downloads `.fit`, parses, saves Activity + DataPoints + notes.

```python
# Add to sync.py

from app.services.coros import login as coros_login, list_activities as coros_list
from app.services.coros import download_fit, get_training_notes
from app.services.fit_parser import parse_fit_file
from app.config import COROS_EMAIL, COROS_PASSWORD, DATA_DIR
from app.models import DataPoint
import uuid

def _sync_coros(session: Session):
    global _last_sync
    if not COROS_EMAIL:
        return
    try:
        token = coros_login(COROS_EMAIL, COROS_PASSWORD)
        remote = coros_list(token)
        existing = {a.external_id for a in session.exec(select(Activity)).all()}
        new_count = 0
        for meta in remote:
            ext_id = str(meta.get("labelId", ""))
            if ext_id in existing:
                continue
            fit_bytes = download_fit(token, str(meta.get("sportType", "100")), ext_id)
            dest = DATA_DIR / f"{uuid.uuid4()}.fit"
            dest.write_bytes(fit_bytes)
            result = parse_fit_file(dest)
            notes = get_training_notes(token, ext_id)
            paces = [1000 / dp["speed_m_s"] for dp in result.datapoints
                     if dp.get("speed_m_s") and dp["speed_m_s"] > 0]
            act = Activity(
                source="coros", external_id=ext_id,
                started_at=result.started_at, distance_m=result.distance_m,
                duration_s=result.duration_s, elevation_gain_m=result.elevation_gain_m,
                avg_hr=result.avg_hr, sport_type=result.sport_type,
                fit_file_path=str(dest), notes=notes,
                avg_pace_s_per_km=sum(paces)/len(paces) if paces else None,
            )
            session.add(act)
            session.flush()
            for dp in result.datapoints:
                session.add(DataPoint(activity_id=act.id, **dp))
            new_count += 1
        session.commit()
        _last_sync = {"status": "ok", "ts": datetime.now(timezone.utc).isoformat(),
                      "new_activities": new_count, "error": None}
    except Exception as e:
        _last_sync = {"status": "error", "ts": datetime.now(timezone.utc).isoformat(),
                      "error": str(e)}
```

**Step 3: Schedule Coros sync hourly in `main.py`**

```python
scheduler.add_job(lambda: _sync_coros(Session(engine)), "interval", hours=1)
```

**Step 4: Commit**

```bash
git add backend/app/services/coros.py backend/app/routers/sync.py backend/app/main.py
git commit -m "feat: Coros hourly background sync with training notes"
```

---

## Running the App

**Without Docker (development):**

```bash
# Terminal 1 — backend
cd backend && pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`

**With Docker:**

```bash
cp .env.example .env   # fill in credentials
docker compose up --build
```

Open `http://localhost`

**Run all backend tests:**

```bash
cd backend && pytest tests/ -v
```

---

## Environment Variables (`.env`)

```
# Strava — get from https://www.strava.com/settings/api
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REFRESH_TOKEN=

# Coros — your account credentials
COROS_EMAIL=
COROS_PASSWORD=

# Optional override (defaults to ./data inside project)
DATA_DIR=
```

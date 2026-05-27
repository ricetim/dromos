from typing import Optional, List
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
    elevation_loss_m: Optional[float] = None
    avg_hr: Optional[int] = None
    avg_pace_s_per_km: Optional[float] = None
    sport_type: str = "run"
    fit_file_path: Optional[str] = None
    notes: Optional[str] = None
    rpe: Optional[int] = None                # 1-5 from Coros feelType
    name: Optional[str] = None             # activity name from Coros

    # Weather at run time (fetched from Open-Meteo at upload)
    weather_temp_c: Optional[float] = None
    weather_feels_like_c: Optional[float] = None
    weather_precip_mm: Optional[float] = None
    weather_cloud_pct: Optional[int] = None
    weather_wind_kph: Optional[float] = None
    weather_condition: Optional[str] = None
    weather_is_daytime: Optional[bool] = None

    datapoints: List["DataPoint"] = Relationship(back_populates="activity")
    photos: List["Photo"] = Relationship(back_populates="activity")
    activity_shoes: List["ActivityShoe"] = Relationship(back_populates="activity")


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
    # Running dynamics
    vertical_oscillation_mm: Optional[float] = None   # mm
    stride_length_m: Optional[float] = None           # metres
    vertical_ratio: Optional[float] = None            # %
    stance_time_ms: Optional[float] = None            # ms (ground contact time)

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
    strava_gear_id: Optional[str] = None   # e.g. "g12345678" — used as dedup key on sync

    activity_shoes: List["ActivityShoe"] = Relationship(back_populates="shoe")


class ActivityShoe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", unique=True, index=True)
    shoe_id: int = Field(foreign_key="shoe.id", index=True)

    activity: Optional[Activity] = Relationship(back_populates="activity_shoes")
    shoe: Optional[Shoe] = Relationship(back_populates="activity_shoes")


class UserProfile(SQLModel, table=True):
    """Singleton row (id=1) storing user-specific physiology settings."""
    id: Optional[int] = Field(default=None, primary_key=True)
    hr_max: int = 185          # maximum heart rate (bpm)
    hr_rest: int = 50          # resting heart rate (bpm)
    weight_kg: Optional[float] = None
    default_shoe_id: Optional[int] = Field(default=None, foreign_key="shoe.id")


class Lap(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", index=True)
    lap_number: int
    start_elapsed_s: float       # seconds from activity start
    end_elapsed_s: float
    distance_m: float = 0.0
    duration_s: float = 0.0
    avg_hr: Optional[int] = None
    avg_pace_s_per_km: Optional[float] = None
    elevation_gain_m: Optional[float] = None


class Goal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str                            # "weekly_distance" | "monthly_distance" | "annual_distance"
    target_value: float
    period_start: date
    period_end: date
    notes: Optional[str] = None



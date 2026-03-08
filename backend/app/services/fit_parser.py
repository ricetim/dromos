from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import fitdecode


@dataclass
class LapData:
    lap_number: int
    start_elapsed_s: float
    end_elapsed_s: float
    distance_m: float
    duration_s: float
    avg_hr: Optional[int]
    avg_pace_s_per_km: Optional[float]
    elevation_gain_m: Optional[float]


@dataclass
class FitParseResult:
    started_at: datetime
    distance_m: float
    duration_s: int
    elevation_gain_m: float
    elevation_loss_m: Optional[float]
    avg_hr: Optional[int]
    sport_type: str
    datapoints: list[dict[str, Any]] = field(default_factory=list)
    laps: list[LapData] = field(default_factory=list)


def _get(frame, name):
    """Safely get a field value from a fitdecode data message."""
    if frame.has_field(name):
        return frame.get_value(name)
    return None


def _tz(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


_MILE_M = 1609.344
_MIN_PARTIAL_M = 50.0


def _synthesize_mile_laps(datapoints: list[dict]) -> list["LapData"]:
    """
    Build per-mile LapData from a DataPoints list.
    Called when a FIT file has only one device lap (i.e. the whole run is one lap).
    Requires datapoints sorted by timestamp with distance_m populated.
    """
    pts = [
        dp for dp in datapoints
        if dp.get("distance_m") is not None and dp.get("timestamp") is not None
    ]
    if not pts:
        return []

    laps: list[LapData] = []
    lap_num = 0
    next_boundary = _MILE_M
    lap_start_idx = 0
    t0 = pts[0]["timestamp"]

    def _emit(start_i: int, end_i: int, dist: float) -> LapData:
        nonlocal lap_num
        lap_num += 1
        slice_ = pts[start_i:end_i + 1]
        t_start = (slice_[0]["timestamp"] - t0).total_seconds()
        t_end   = (slice_[-1]["timestamp"] - t0).total_seconds()
        dur = t_end - t_start

        hrs = [dp["heart_rate"] for dp in slice_ if dp.get("heart_rate")]
        avg_hr = int(sum(hrs) / len(hrs)) if hrs else None

        alts = [dp["altitude_m"] for dp in slice_ if dp.get("altitude_m") is not None]
        elev_gain = sum(
            max(0.0, alts[i + 1] - alts[i]) for i in range(len(alts) - 1)
        ) if len(alts) > 1 else 0.0

        pace = (1000.0 / (dist / dur)) if dur > 0 and dist > 0 else None
        return LapData(
            lap_number=lap_num,
            start_elapsed_s=round(t_start, 1),
            end_elapsed_s=round(t_end, 1),
            distance_m=round(dist, 1),
            duration_s=round(dur, 1),
            avg_hr=avg_hr,
            avg_pace_s_per_km=round(pace, 1) if pace else None,
            elevation_gain_m=round(elev_gain, 2) if alts else None,
        )

    for i, dp in enumerate(pts):
        if dp["distance_m"] >= next_boundary:
            laps.append(_emit(lap_start_idx, i, _MILE_M))
            lap_start_idx = i
            next_boundary += _MILE_M

    # Partial final lap
    if lap_start_idx < len(pts) - 1:
        remaining = pts[-1]["distance_m"] - pts[lap_start_idx]["distance_m"]
        if remaining >= _MIN_PARTIAL_M:
            laps.append(_emit(lap_start_idx, len(pts) - 1, remaining))

    return laps


def parse_fit_file(path: Path) -> FitParseResult:
    if not path.exists():
        raise FileNotFoundError(f"FIT file not found: {path}")

    records: list[dict] = []
    session_data: dict = {}
    lap_records: list[dict] = []
    sport_type = "run"

    with fitdecode.FitReader(str(path), error_handling=fitdecode.ErrorHandling.IGNORE) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue

            if frame.name == "record":
                row = {}
                for field_def in frame.fields:
                    if field_def.value is not None:
                        row[field_def.name] = field_def.value
                if row:
                    records.append(row)

            elif frame.name == "lap":
                lap = {}
                for field_def in frame.fields:
                    if field_def.value is not None:
                        lap[field_def.name] = field_def.value
                if lap:
                    lap_records.append(lap)

            elif frame.name == "session":
                for field_def in frame.fields:
                    if field_def.value is not None:
                        session_data[field_def.name] = field_def.value

            elif frame.name == "sport":
                sport_val = _get(frame, "sport")
                if sport_val is not None:
                    sport_type = str(sport_val).lower().replace(" ", "_")

    # Determine start time
    started_at = _tz(session_data.get("start_time"))
    if started_at is None and records:
        started_at = _tz(records[0].get("timestamp"))
    if started_at is None:
        started_at = datetime.now(timezone.utc)

    distance_m = float(session_data.get("total_distance") or 0)
    duration_s = int(session_data.get("total_elapsed_time") or 0)
    elevation_gain_m = float(session_data.get("total_ascent") or 0)
    elevation_loss_m = float(session_data.get("total_descent")) if session_data.get("total_descent") is not None else None
    avg_hr = session_data.get("avg_heart_rate")

    # Semicircle → decimal degrees conversion factor (2^31 / 180)
    SEMICIRCLE = 11930465

    datapoints = []
    for r in records:
        ts = _tz(r.get("timestamp"))
        if ts is None:
            continue

        pos_lat = r.get("position_lat")
        pos_lon = r.get("position_long")

        # Cadence in FIT is stored as revolutions/min for one foot;
        # multiply by 2 for total steps/min (running cadence convention)
        raw_cadence = r.get("cadence")
        cadence = raw_cadence * 2 if raw_cadence is not None else None

        datapoints.append({
            "timestamp": ts,
            "lat": pos_lat / SEMICIRCLE if pos_lat is not None else None,
            "lon": pos_lon / SEMICIRCLE if pos_lon is not None else None,
            "distance_m": r.get("distance"),
            "speed_m_s": r.get("speed"),
            "heart_rate": r.get("heart_rate"),
            "cadence": cadence,
            "altitude_m": r.get("altitude"),
            "power_w": r.get("power"),
            # Running dynamics
            "vertical_oscillation_mm": r.get("vertical_oscillation"),
            "stride_length_m": r.get("stride_length"),
            "vertical_ratio": r.get("vertical_ratio"),
            "stance_time_ms": r.get("stance_time"),
        })

    # Build lap data from lap frames
    laps: list[LapData] = []
    act_start_ts = started_at
    elapsed_so_far = 0.0
    for i, lap in enumerate(lap_records):
        dur = float(lap.get("total_elapsed_time") or lap.get("total_timer_time") or 0)
        dist = float(lap.get("total_distance") or 0)
        a_hr = lap.get("avg_heart_rate")
        elev = lap.get("total_ascent")
        avg_speed = lap.get("avg_speed")
        pace = (1000.0 / avg_speed) if avg_speed and avg_speed > 0 else None
        start_s = elapsed_so_far
        end_s = elapsed_so_far + dur
        laps.append(LapData(
            lap_number=i + 1,
            start_elapsed_s=round(start_s, 1),
            end_elapsed_s=round(end_s, 1),
            distance_m=dist,
            duration_s=dur,
            avg_hr=int(a_hr) if a_hr is not None else None,
            avg_pace_s_per_km=round(pace, 1) if pace else None,
            elevation_gain_m=float(elev) if elev is not None else None,
        ))
        elapsed_so_far = end_s

    # If the device recorded only one lap (entire run as a single lap),
    # synthesize per-mile splits instead — more useful for pacing analysis.
    if len(laps) == 1:
        laps = _synthesize_mile_laps(datapoints)

    return FitParseResult(
        started_at=started_at,
        distance_m=distance_m,
        duration_s=duration_s,
        elevation_gain_m=elevation_gain_m,
        elevation_loss_m=elevation_loss_m,
        avg_hr=int(avg_hr) if avg_hr is not None else None,
        sport_type=sport_type,
        datapoints=datapoints,
        laps=laps,
    )

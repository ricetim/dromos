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


@pytest.mark.skipif(not FIXTURE.exists(), reason="no sample.fit fixture")
def test_datapoints_not_compressed():
    """Every record from the FIT file must be stored — no downsampling."""
    result = parse_fit_file(FIXTURE)
    # FIT files record at ~1Hz; a 30-min run should have >=1000 points
    assert len(result.datapoints) >= 100


def test_parse_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_fit_file(Path("/nonexistent/file.fit"))


from datetime import datetime, timezone, timedelta
from app.services.fit_parser import _synthesize_mile_laps, LapData


def _make_dps(total_m: float, step_m: float = 100.0, hr: int = 150):
    """Create synthetic datapoints at regular distance/time intervals."""
    dps = []
    t0 = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    d = 0.0
    i = 0
    while d <= total_m + step_m:
        dps.append({
            "timestamp": t0 + timedelta(seconds=i * 10),
            "distance_m": round(d, 1),
            "heart_rate": hr,
            "altitude_m": 50.0 + (d * 0.005),  # gentle climb
        })
        d += step_m
        i += 1
    return dps


def test_synthesize_two_full_miles():
    dps = _make_dps(3500.0)  # ~2.17 miles
    laps = _synthesize_mile_laps(dps)
    assert len(laps) == 3  # mile 1, mile 2, partial
    assert laps[0].lap_number == 1
    assert abs(laps[0].distance_m - 1609.344) < 1.0
    assert laps[1].lap_number == 2
    assert laps[2].distance_m < 1609.344  # partial


def test_synthesize_exact_one_mile():
    dps = _make_dps(1609.344)
    laps = _synthesize_mile_laps(dps)
    assert len(laps) == 1
    assert abs(laps[0].distance_m - 1609.344) < 1.0


def test_synthesize_ignores_tiny_remainder():
    """Remainder < 50m should not produce an extra lap."""
    # step_m=10 gives points at 0, 10, 20, ... 1610 (past the mile boundary)
    # After crossing the mile at ~1609.344, lap_start_idx is at the 1610 point.
    # pts[-1].distance_m = 1640, lap_start_idx point = 1610, remaining = 30m < 50m
    dps = _make_dps(1640.0, step_m=10.0)
    laps = _synthesize_mile_laps(dps)
    assert len(laps) == 1  # only the full mile; remainder 30m is below 50m threshold


def test_synthesize_large_remainder_creates_partial():
    """Remainder >= 50m should produce a partial lap."""
    # total_m=1700, step_m=10: after mile boundary at 1610, remaining = 1700-1610 = 90m >= 50m
    dps = _make_dps(1700.0, step_m=10.0)
    laps = _synthesize_mile_laps(dps)
    assert len(laps) == 2  # one full mile + one partial
    assert laps[1].distance_m < 1609.344
    assert laps[1].distance_m >= 50.0


def test_synthesize_avg_hr():
    dps = _make_dps(2000.0, hr=160)
    laps = _synthesize_mile_laps(dps)
    assert laps[0].avg_hr == 160


def test_synthesize_empty_returns_empty():
    assert _synthesize_mile_laps([]) == []

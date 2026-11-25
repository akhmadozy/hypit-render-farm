"""
Unit tests for OpenShorts Cloud Render Farm engine components:
- manifest validation
- layout calculations (SPLIT, TRACK, GENERAL)
- ffmpeg command assembly
"""

import pytest
import sys
from pathlib import Path

# Add hypit-render-farm root to sys.path
PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from engine.layout_engine import (  # noqa: E402
    validate_job_manifest,
    split_geometry,
    build_split_filter,
    build_general_filter,
    build_track_crop_geometry,
    build_track_filter,
)
from engine.render_worker import build_ffmpeg_render_command  # noqa: E402


@pytest.fixture
def sample_valid_manifest():
    return {
        "project_id": "PODCAST-EPS01-CLIP01",
        "source": {
            "type": "url",
            "url": "https://www.youtube.com/watch?v=mock_video_id",
            "local_asset_path": None,
        },
        "timing": {
            "start_seconds": 120.0,
            "end_seconds": 175.0,
            "duration_seconds": 55.0,
        },
        "layout": {
            "mode": "SPLIT",
            "split_seam_y": 0.5,
            "crop_smoothing": True,
        },
        "subtitles": {
            "enabled": True,
            "style": "karaoke",
            "font_size": 24,
            "color": "#FFFFFF",
            "highlight_color": "#FFDF00",
        },
        "hook_overlay": {
            "enabled": True,
            "text": "Rahasia Sukses Terbesar!",
            "duration_seconds": 4.0,
        },
        "output_spec": {
            "resolution": [1080, 1920],
            "fps": 30,
            "codec": "libx264",
        },
    }


def test_validate_job_manifest_valid(sample_valid_manifest):
    cleaned = validate_job_manifest(sample_valid_manifest)
    assert cleaned["project_id"] == "PODCAST-EPS01-CLIP01"
    assert cleaned["layout"]["mode"] == "SPLIT"
    assert cleaned["timing"]["duration_seconds"] == 55.0


def test_validate_job_manifest_invalid_timing(sample_valid_manifest):
    # start >= end
    bad = dict(sample_valid_manifest)
    bad["timing"] = {"start_seconds": 100.0, "end_seconds": 50.0, "duration_seconds": 50.0}
    with pytest.raises(ValueError, match="must be strictly less than end_seconds"):
        validate_job_manifest(bad)

    # negative duration
    bad_neg = dict(sample_valid_manifest)
    bad_neg["timing"] = {"start_seconds": 10.0, "end_seconds": 50.0, "duration_seconds": -40.0}
    with pytest.raises(ValueError, match="timing seconds must be positive values"):
        validate_job_manifest(bad_neg)



def test_validate_job_manifest_missing_required_fields(sample_valid_manifest):
    bad = dict(sample_valid_manifest)
    del bad["source"]
    with pytest.raises(ValueError, match="Missing required manifest section: source"):
        validate_job_manifest(bad)


def test_validate_job_manifest_invalid_layout_mode(sample_valid_manifest):
    bad = dict(sample_valid_manifest)
    bad["layout"] = {"mode": "INVALID_MODE"}
    with pytest.raises(ValueError, match="Unsupported layout mode"):
        validate_job_manifest(bad)


def test_split_geometry_within_boundaries():
    in_w, in_h = 1920, 1080
    out_w, out_h = 1080, 1920
    # Left speaker center at (480, 540)
    w, h, x, y, half_h = split_geometry(in_w, in_h, out_w, out_h, (480.0, 540.0, 150.0, 150.0))
    
    assert w <= in_w
    assert h <= in_h
    assert x >= 0
    assert y >= 0
    assert x + w <= in_w
    assert y + h <= in_h
    assert half_h == 960
    assert w % 2 == 0
    assert h % 2 == 0


def test_build_split_filter_graph():
    in_w, in_h = 1920, 1080
    out_w, out_h = 1080, 1920
    left_c = (480.0, 540.0, 120.0, 120.0)
    right_c = (1440.0, 540.0, 120.0, 120.0)

    fgraph = build_split_filter(in_w, in_h, out_w, out_h, left_c, right_c)
    assert "[0:v]split=2" in fgraph
    assert "vstack=inputs=2" in fgraph
    assert f"pad={out_w}:{out_h}" in fgraph
    assert "scale=1080:960" in fgraph


def test_build_general_filter_graph():
    in_w, in_h = 1920, 1080
    out_w, out_h = 1080, 1920

    fgraph = build_general_filter(in_w, in_h, out_w, out_h)
    assert "[0:v]split=2" in fgraph
    assert "boxblur=" in fgraph
    assert "overlay=(W-w)/2:(H-h)/2" in fgraph
    assert "setsar=1" in fgraph


def test_build_track_crop_geometry():
    in_w, in_h = 1920, 1080
    face_box = (800, 300, 950, 500) # x1, y1, x2, y2 -> center_x = 875, center_y = 400
    w, h, x, y = build_track_crop_geometry(in_w, in_h, face_box)

    assert h == in_h
    # 9:16 aspect of 1080 height is 607.5 -> rounded to even 606 or 608
    assert abs(w - int(round(in_h * 9 / 16))) <= 2
    assert x >= 0
    assert x + w <= in_w
    assert y == 0


def test_build_track_filter_graph():
    in_w, in_h = 1920, 1080
    out_w, out_h = 1080, 1920
    face_box = (800, 300, 950, 500)

    fgraph = build_track_filter(in_w, in_h, out_w, out_h, face_box)
    assert "crop=" in fgraph
    assert f"scale={out_w}:{out_h}" in fgraph
    assert "setsar=1" in fgraph


def test_build_ffmpeg_render_command(sample_valid_manifest, tmp_path):
    source_file = tmp_path / "input.mp4"
    source_file.write_bytes(b"dummy input")
    output_file = tmp_path / "output.mp4"
    srt_file = tmp_path / "subtitles.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello World\n", encoding="utf-8")

    cmd = build_ffmpeg_render_command(
        source_path=str(source_file),
        output_path=str(output_file),
        manifest=sample_valid_manifest,
        filter_complex="[0:v]scale=1080:1920[v]",
        subtitle_path=str(srt_file),
    )

    cmd_str = " ".join(cmd)
    assert "-avoid_negative_ts make_zero" in cmd_str
    # Verify -avoid_negative_ts is placed after -i (GEMINI.md rule)
    i_idx = cmd.index("-i")
    avoid_idx = cmd.index("-avoid_negative_ts")
    assert avoid_idx > i_idx, "-avoid_negative_ts must be placed after -i"

    assert "-ss 120.0" in cmd_str
    assert "-t 55.0" in cmd_str
    assert "-c:v libx264" in cmd_str
    assert "-c:a aac" in cmd_str
    assert "subtitles=" in cmd_str
    assert "drawtext=" in cmd_str
    assert str(output_file) in cmd


def test_validate_job_manifest_duration_mismatch(sample_valid_manifest):
    bad = dict(sample_valid_manifest)
    bad["timing"] = {"start_seconds": 10.0, "end_seconds": 30.0, "duration_seconds": 50.0}
    with pytest.raises(ValueError, match="does not match end_seconds"):
        validate_job_manifest(bad)


def test_validate_job_manifest_non_dict_section(sample_valid_manifest):
    bad = dict(sample_valid_manifest)
    bad["layout"] = "SPLIT"
    with pytest.raises(ValueError, match="must be a JSON object"):
        validate_job_manifest(bad)


def test_validate_job_manifest_invalid_url_scheme(sample_valid_manifest):
    bad = dict(sample_valid_manifest)
    bad["source"] = {"type": "url", "url": "ftp://example.com/video.mp4"}
    with pytest.raises(ValueError, match="must be a valid HTTP/HTTPS URL"):
        validate_job_manifest(bad)


def test_yolo_detection_graceful_fallback(tmp_path):
    from engine.layout_engine import detect_person_box_yolo, detect_split_speakers_yolo
    # Video file does not exist or YOLO not present in environment
    res = detect_person_box_yolo(str(tmp_path / "nonexistent.mp4"), 0.0, 10.0, 1920, 1080)
    assert res is None

    left, right = detect_split_speakers_yolo(str(tmp_path / "nonexistent.mp4"), 0.0, 10.0, 1920, 1080)
    assert left is None
    assert right is None


def test_build_ffmpeg_render_command_floating_typography_and_apostrophe(sample_valid_manifest, tmp_path):
    manifest = dict(sample_valid_manifest)
    manifest["hook_overlay"] = {"enabled": True, "text": "Rahasia 'Sukses' 100%: Kita!", "duration_seconds": 4.0}
    manifest["outro_overlay"] = {"enabled": True, "text": "Cek link's bio!", "duration_seconds": 5.0}

    cmd = build_ffmpeg_render_command(
        source_path=str(tmp_path / "in.mp4"),
        output_path=str(tmp_path / "out.mp4"),
        manifest=manifest,
        filter_complex="[0:v]scale=1080:1920[v]",
    )
    cmd_str = " ".join(cmd)
    assert "box=1" not in cmd_str
    assert "boxcolor=" not in cmd_str
    assert "boxborderw=" not in cmd_str
    assert "borderw=" in cmd_str
    assert "shadowx=" in cmd_str
    assert r"\'Sukses\'" not in cmd_str
    assert "Rahasia '\\''Sukses'\\'' 100\\%\\: Kita!" in cmd_str
    assert "Cek link'\\''s bio!" in cmd_str


def test_build_screencast_filter_and_routing(sample_valid_manifest, tmp_path):
    from unittest.mock import MagicMock, patch
    from engine.layout_engine import build_screencast_filter
    import engine.render_worker as rw

    fgraph = build_screencast_filter(1920, 1080, 1080, 1920)
    assert "force_original_aspect_ratio=decrease" in fgraph
    assert "boxblur=" in fgraph

    manifest = dict(sample_valid_manifest)
    manifest["layout"] = {"mode": "SCREENCAST"}
    manifest["subtitles"] = {"enabled": False}
    cmd = build_ffmpeg_render_command(
        source_path=str(tmp_path / "in.mp4"),
        output_path=str(tmp_path / "out.mp4"),
        manifest=manifest,
    )
    assert "force_original_aspect_ratio=decrease" in " ".join(cmd)

    m_path = tmp_path / "manifest.json"
    src_path = tmp_path / "src.mp4"
    src_path.write_bytes(b"video")
    manifest["source"] = {"type": "local", "local_asset_path": str(src_path)}
    import json
    m_path.write_text(json.dumps(manifest), encoding="utf-8")

    with patch.object(rw, "probe_video_dimensions", return_value=(1920, 1080)), \
         patch.object(rw, "build_screencast_filter", return_value="[0:v]scale=1080:1920[v]") as mock_sc, \
         patch.object(rw.subprocess, "run", return_value=MagicMock(returncode=0)), \
         patch.object(rw, "verify_rendered_mp4", return_value=True):
        rc = rw.run_worker(str(m_path), str(tmp_path / "out.mp4"))
        assert rc == 0
        mock_sc.assert_called_once_with(1920, 1080, 1080, 1920)


@pytest.mark.parametrize("orig_w,orig_h", [(720, 1280), (480, 1080), (600, 1920)])
def test_build_track_crop_geometry_clamps_portrait_source(orig_w, orig_h):
    w, h, x, y = build_track_crop_geometry(orig_w, orig_h, (orig_w * 0.5, orig_h * 0.25, orig_w * 0.8, orig_h * 0.5))
    assert 0 < w <= orig_w
    assert 0 < h <= orig_h
    assert x >= 0
    assert y >= 0
    assert x + w <= orig_w
    assert y + h <= orig_h
    assert w % 2 == 0
    assert h % 2 == 0


def test_probe_video_dimensions_fails_closed(tmp_path):
    import subprocess
    from unittest.mock import patch
    from engine.render_worker import probe_video_dimensions

    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffprobe")):
        with pytest.raises(RuntimeError, match="Failed to probe video dimensions"):
            probe_video_dimensions(str(tmp_path / "missing.mp4"))


def test_yolo_helpers_release_capture_on_error(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    from engine.layout_engine import detect_person_box_yolo, detect_split_speakers_yolo

    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.return_value = 30.0
    cap.read.side_effect = RuntimeError("decode boom")

    fake_cv2 = SimpleNamespace(
        VideoCapture=MagicMock(return_value=cap),
        CAP_PROP_FPS=5,
        CAP_PROP_POS_FRAMES=1,
    )
    fake_ultralytics = SimpleNamespace(YOLO=MagicMock(return_value=MagicMock()))

    with patch.dict(sys.modules, {"cv2": fake_cv2, "ultralytics": fake_ultralytics}):
        assert detect_person_box_yolo(str(tmp_path / "v.mp4"), 0.0, 10.0, 1920, 1080) is None
        assert cap.release.call_count == 1
        assert detect_split_speakers_yolo(str(tmp_path / "v.mp4"), 0.0, 10.0, 1920, 1080) == (None, None)
        assert cap.release.call_count == 2

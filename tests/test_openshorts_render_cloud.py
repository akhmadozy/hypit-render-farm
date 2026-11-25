"""
Unit tests for OpenShorts Cloud Render Orchestrator (openshorts_render_cloud.py)
"""

import json
import re
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.openshorts_render_cloud import (  # noqa: E402
    DEFAULT_REPO,
    DEFAULT_WORKFLOW,
    check_github_rate_limit,
    validate_manifest_file,
    create_temporary_asset_release,
    delete_temporary_asset_release,
    trigger_workflow_run,
    download_rendered_artifact,
    verify_final_mp4,
)


def test_default_repo_and_workflow():
    assert DEFAULT_REPO == "akhmadozy/hypit-render-farm"
    assert DEFAULT_WORKFLOW == "openshorts-render.yml"


@pytest.fixture
def valid_manifest_dict():
    return {
        "project_id": "TEST-PROJ-01",
        "source": {
            "type": "url",
            "url": "https://www.youtube.com/watch?v=12345",
            "local_asset_path": None,
        },
        "timing": {
            "start_seconds": 10.0,
            "end_seconds": 40.0,
            "duration_seconds": 30.0,
        },
        "layout": {
            "mode": "TRACK",
        },
        "output_spec": {
            "resolution": [1080, 1920],
            "fps": 30,
            "codec": "libx264",
        },
    }


def test_validate_manifest_file_success(tmp_path, valid_manifest_dict):
    m_path = tmp_path / "job_manifest.json"
    m_path.write_text(json.dumps(valid_manifest_dict), encoding="utf-8")

    manifest = validate_manifest_file(str(m_path))
    assert manifest["project_id"] == "TEST-PROJ-01"
    assert manifest["layout"]["mode"] == "TRACK"


def test_validate_manifest_file_not_found():
    with pytest.raises(FileNotFoundError):
        validate_manifest_file("/path/to/nonexistent/manifest.json")


def test_validate_manifest_file_invalid_json(tmp_path):
    m_path = tmp_path / "bad_manifest.json"
    m_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON"):
        validate_manifest_file(str(m_path))


def test_check_github_rate_limit_sufficient():
    mock_out = json.dumps({
        "resources": {
            "core": {
                "limit": 5000,
                "remaining": 4900,
                "reset": 1700000000,
            }
        }
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_out, stderr="")
        core = check_github_rate_limit(min_remaining=100)
        assert core is not None
        assert core["remaining"] == 4900


def test_check_github_rate_limit_low_quota_pacing():
    mock_out = json.dumps({
        "resources": {
            "core": {
                "limit": 5000,
                "remaining": 50,
                "reset": 1700000000,
            }
        }
    })
    with patch("subprocess.run") as mock_run, patch("time.sleep") as mock_sleep:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_out, stderr="")
        core = check_github_rate_limit(min_remaining=100)
        assert core["remaining"] == 50
        mock_sleep.assert_called_once()


def test_create_temporary_asset_release(tmp_path):
    asset_file = tmp_path / "raw_video.mp4"
    asset_file.write_bytes(b"dummy video data")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="release created", stderr="")
        tag = create_temporary_asset_release(
            repo_name="akhmadozy/hypit-render-farm",
            tag_name="temp-assets-test-1234",
            asset_files=[str(asset_file)],
        )
        assert tag == "temp-assets-test-1234"
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "release" in cmd
        assert "create" in cmd
        assert "akhmadozy/hypit-render-farm" in cmd
        assert "temp-assets-test-1234" in cmd


def test_delete_temporary_asset_release():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="deleted", stderr="")
        res = delete_temporary_asset_release(
            repo_name="akhmadozy/hypit-render-farm",
            tag_name="temp-assets-test-1234",
        )
        assert res is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "delete" in cmd
        assert "akhmadozy/hypit-render-farm" in cmd
        assert "--cleanup-tag" in cmd


def test_trigger_workflow_run():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        success = trigger_workflow_run(
            repo_name="akhmadozy/hypit-render-farm",
            workflow_name="openshorts-render.yml",
            inputs={"manifest": '{"project_id":"TEST"}', "release_tag": ""},
        )
        assert success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "workflow" in cmd
        assert "run" in cmd
        assert "openshorts-render.yml" in cmd
        assert "akhmadozy/hypit-render-farm" in cmd


def test_download_rendered_artifact(tmp_path):
    out_file = tmp_path / "final" / "output.mp4"
    run_id = "12345678"

    def mock_download_side_effect(cmd, **kwargs):
        # Emulate gh run download writing output.mp4 inside download dir
        dest_dir = Path(cmd[cmd.index("--dir") + 1])
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "output.mp4").write_bytes(b"dummy rendered mp4")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_download_side_effect):
        ok = download_rendered_artifact(
            repo_name="akhmadozy/hypit-render-farm",
            run_id=run_id,
            output_path=str(out_file),
        )
        assert ok is True
        assert out_file.exists()
        assert out_file.read_bytes() == b"dummy rendered mp4"


def test_verify_final_mp4(tmp_path):
    mp4 = tmp_path / "output.mp4"
    mp4.write_bytes(b"dummy")

    with patch("subprocess.run") as mock_run:
        # ffprobe returns 1080x1920, and ffmpeg null-muxer decode succeeds
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="1080x1920\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        assert verify_final_mp4(str(mp4)) is True

    # Test failure on 0 bytes
    empty_mp4 = tmp_path / "empty.mp4"
    empty_mp4.write_bytes(b"")
    assert verify_final_mp4(str(empty_mp4)) is False


def test_find_latest_run_id_with_exclude():
    from scripts.openshorts_render_cloud import find_latest_run_id

    mock_res_old = MagicMock(returncode=0, stdout=json.dumps([{"databaseId": 1111}]), stderr="")
    mock_res_new = MagicMock(returncode=0, stdout=json.dumps([{"databaseId": 2222}]), stderr="")

    with patch("subprocess.run") as mock_run:
        # First call returns old run id, second call returns new run id
        mock_run.side_effect = [mock_res_old, mock_res_new]
        run_id = find_latest_run_id(
            repo_name="akhmadozy/hypit-render-farm",
            workflow_name="openshorts-render.yml",
            exclude_run_id="1111",
            max_wait_seconds=5,
            poll_interval=0,
        )
        assert run_id == "2222"


def test_url_source_with_local_subtitles_staging(tmp_path, valid_manifest_dict):
    from scripts.openshorts_render_cloud import run_orchestrator

    manifest_path = tmp_path / "job_manifest.json"
    manifest_path.write_text(json.dumps(valid_manifest_dict), encoding="utf-8")
    sub_file = tmp_path / "subtitles.srt"
    sub_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch("scripts.openshorts_render_cloud.find_latest_run_id", side_effect=["5555", "5556"]), \
             patch("scripts.openshorts_render_cloud.watch_run_with_timeout", return_value=True), \
             patch("scripts.openshorts_render_cloud.download_rendered_artifact", return_value=True), \
             patch("scripts.openshorts_render_cloud.verify_final_mp4", return_value=True):

            code = run_orchestrator(
                manifest_path=str(manifest_path),
                output_path=str(tmp_path / "out.mp4"),
                repo_name="akhmadozy/hypit-render-farm",
                workflow_name="openshorts-render.yml",
            )
            assert code == 0
            release_calls = [
                call for call in mock_run.call_args_list
                if len(call[0]) > 0 and isinstance(call[0][0], list) and "release" in call[0][0] and "create" in call[0][0]
            ]
            assert len(release_calls) == 1
            args = release_calls[0][0][0]
            assert any("subtitles.srt" in str(a) for a in args)


def test_validate_sample_podcast_manifest_fixture():
    fixture_path = REPO_ROOT / "tests/fixtures/sample_podcast_manifest.json"
    manifest = validate_manifest_file(str(fixture_path))
    assert manifest["project_id"] == "PODCAST-SAMPLE-CLIP01"
    assert manifest["layout"]["mode"] == "SPLIT"


@pytest.mark.parametrize("failing_stage", ["watch_run_with_timeout", "download_rendered_artifact"])
def test_ephemeral_release_cleaned_up_on_exception(tmp_path, valid_manifest_dict, failing_stage):
    from scripts.openshorts_render_cloud import run_orchestrator

    manifest_path = tmp_path / "job_manifest.json"
    manifest_path.write_text(json.dumps(valid_manifest_dict), encoding="utf-8")
    sub_file = tmp_path / "subtitles.srt"
    sub_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    watch_kwargs = {"side_effect": RuntimeError("watch interrupted")} if failing_stage == "watch_run_with_timeout" else {"return_value": True}
    dl_kwargs = {"side_effect": RuntimeError("download failed")} if failing_stage == "download_rendered_artifact" else {"return_value": True}

    with patch("scripts.openshorts_render_cloud.check_github_rate_limit"), \
         patch("scripts.openshorts_render_cloud.create_temporary_asset_release", return_value="temp-assets-tag-1"), \
         patch("scripts.openshorts_render_cloud.delete_temporary_asset_release", return_value=True) as mock_delete, \
         patch("scripts.openshorts_render_cloud.find_latest_run_id", side_effect=["5555", "5556"]), \
         patch("scripts.openshorts_render_cloud.trigger_workflow_run", return_value=True), \
         patch("scripts.openshorts_render_cloud.watch_run_with_timeout", **watch_kwargs), \
         patch("scripts.openshorts_render_cloud.download_rendered_artifact", **dl_kwargs):

        with pytest.raises(RuntimeError):
            run_orchestrator(
                manifest_path=str(manifest_path),
                output_path=str(tmp_path / "out.mp4"),
                repo_name="akhmadozy/hypit-render-farm",
                workflow_name="openshorts-render.yml",
            )

        mock_delete.assert_called_once_with("akhmadozy/hypit-render-farm", "temp-assets-tag-1")


def test_openshorts_workflow_security_and_env_binding():
    import yaml

    wf_path = REPO_ROOT / ".github/workflows/openshorts-render.yml"
    wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    assert wf["permissions"] == {"contents": "read"}

    steps = wf["jobs"]["render"]["steps"]
    for step in steps:
        run_block = step.get("run", "")
        assert "${{ inputs." not in run_block, f"Direct inputs interpolation found in step {step.get('name')}"

    download_step = next(s for s in steps if s.get("name") == "Download Ephemeral Assets from GitHub Release")
    assert download_step["env"]["RELEASE_TAG"] == "${{ inputs.release_tag }}"
    assert '"$RELEASE_TAG"' in download_step["run"]
    assert any("python3 engine/render_worker.py" in s.get("run", "") for s in steps)


def test_verify_final_mp4_fails_closed_on_wrong_resolution(tmp_path):
    mp4 = tmp_path / "wrong_res.mp4"
    mp4.write_bytes(b"dummy")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="1920x1080\n", stderr="")
        assert verify_final_mp4(str(mp4)) is False

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="probe error")
        assert verify_final_mp4(str(mp4)) is False


def test_url_source_with_custom_subtitles_file_path_staging(tmp_path, valid_manifest_dict):
    from scripts.openshorts_render_cloud import run_orchestrator

    sub_dir = tmp_path / "captions"
    sub_dir.mkdir()
    custom_sub = sub_dir / "custom_hook.srt"
    custom_sub.write_text("1\n00:00:00,000 --> 00:00:02,000\nHalo\n", encoding="utf-8")

    manifest = dict(valid_manifest_dict)
    manifest["subtitles"] = {"enabled": True, "file_path": "captions/custom_hook.srt"}
    manifest_path = tmp_path / "job_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with patch("scripts.openshorts_render_cloud.check_github_rate_limit"), \
         patch("scripts.openshorts_render_cloud.create_temporary_asset_release", return_value="temp-tag-sub") as mock_create, \
         patch("scripts.openshorts_render_cloud.delete_temporary_asset_release", return_value=True), \
         patch("scripts.openshorts_render_cloud.find_latest_run_id", side_effect=["10", "11"]), \
         patch("scripts.openshorts_render_cloud.trigger_workflow_run", return_value=True), \
         patch("scripts.openshorts_render_cloud.watch_run_with_timeout", return_value=True), \
         patch("scripts.openshorts_render_cloud.download_rendered_artifact", return_value=True), \
         patch("scripts.openshorts_render_cloud.verify_final_mp4", return_value=True):
        code = run_orchestrator(
            manifest_path=str(manifest_path),
            output_path=str(tmp_path / "out.mp4"),
            repo_name="akhmadozy/hypit-render-farm",
            workflow_name="openshorts-render.yml",
        )
        assert code == 0
        mock_create.assert_called_once()
        staged = mock_create.call_args[0][2]
        assert str(custom_sub.resolve()) in staged


def test_openshorts_workflow_actions_pinned_to_commit_sha():
    import yaml

    wf_path = REPO_ROOT / ".github/workflows/openshorts-render.yml"
    wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    for step in wf["jobs"]["render"]["steps"]:
        uses = step.get("uses")
        if uses:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses), f"Action not pinned to 40-char SHA: {uses}"


def test_requirements_upper_bounded():
    req_lines = [
        line.strip()
        for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for pkg in ("ultralytics", "opencv-python-headless", "torch", "numpy", "jsonschema", "pyyaml", "requests", "pytest"):
        matched = [line for line in req_lines if line.lower().startswith(pkg)]
        assert matched and "<" in matched[0], f"Missing upper bound for {pkg}: {matched}"

# Clipper Unified Render Farm (`akhmadozy/hypit-render-farm`)

Public GitHub Actions cloud render farm for Clipper OS, consolidating two distinct workflows:

1. **Hypit OIDC Trusted Workflow (`.github/workflows/render.yml`)**: Private-media rendering (`analysis`, `preview`, `final`) for persisted Clipper cloud jobs via GitHub OIDC (`aud=clipper-render`, repository ID `1423099026`) and private R2 storage.
2. **OpenShorts Cloud Reframing Workflow (`.github/workflows/openshorts-render.yml`)**: Automated 9:16 vertical podcast/talking-head reframing (`SPLIT`, `TRACK`, `GENERAL`, `SCREENCAST`) executed by `engine/render_worker.py` and `engine/layout_engine.py`, orchestrated via `scripts/openshorts_render_cloud.py`.

## Zero Project Data Policy

This public repository holds **zero** campaign/project media, manifests, or rendered artifacts (`projects/` is gitignored and prohibited in Git `HEAD`). All project source files, transcripts, and historical archives belong in Layer-3 external storage (e.g. `/Users/ozy/Workspace/project-data/clipper/`).

---

## 1. Hypit OIDC Workflow (`.github/workflows/render.yml`)

Heavy processing runs in GitHub Actions; the Mac performs inventory, authoring and lightweight checks only. Source files remain in the private R2 library. The runner never receives Buffer credentials or publication approval tokens.

The canonical dispatcher is the Clipper Worker. It saves the exact GitHub run ID returned by API version `2026-03-10` before authorizing runner requests. Run identity must match repository ID `1423099026`, configured trusted workflow/ref and OIDC audience `clipper-render`.

### Execution Flow

1. Worker validates rights/source evidence, bounded revision and free-tier quota; persists the job and dispatches `.github/workflows/render.yml` with only `job_id`.
2. Runner authenticates the exact job using fresh GitHub OIDC, then installs frozen dependencies from Hypit commit `1efedb925d375686ab107b6e67f914dced7b102b`.
3. Runner streams authorized source objects, verifies their SHA-256 and size, and executes the requested phase.
4. Runner uploads private artifact receipts, then submits the result for that exact revision. Failed, stale or cancelled jobs cannot become publishable through runner claims.

| Phase | Output | Evidence |
|---|---|---|
| analysis | `analysis.json` | Actual source stream metadata, scene changes and silence; semantic analysis and transcription explicitly not performed |
| preview | 540×960 H.264/AAC MP4 + QA JSON | Full-artifact decode, duration/FPS/codecs, measured loudness/true peak, SHA-256 |
| final | 1080×1920 H.264/AAC MP4 + QA JSON | Same actual-artifact QA; human creative/rights review remains required |

`vertical-v1` is trusted Python-generated native Hypit SVML, using only `STORYTELLING`, `PODCAST`, `JJ`. Accepted edit parameters are `clips[{asset_id,start_s,end_s}]`, `title`, timed `subtitles[{start_s,end_s,text}]`, and optional `music_asset_id`. Text is escaped. No user JS, SVML, filesystem paths, URLs, projects or packages are executed. FFmpeg prepares bounded trims, center crops, source audio and optional looped music; Hypit composes clips/title/subtitles/music; FFmpeg masters audio and mechanically validates the final physical file.

Limits: one active workflow globally, 90-minute runner timeout, at most 16 assets / 2 GiB per asset / 4 GiB total, 24 clips, 180-second output, 300 non-overlapping subtitle cues, artifact strictly below 500 MiB. Source clip audio is required. Loudness acceptance is −18..−12 LUFS and true peak ≤−1 dBTP after two-pass mastering. Center cropping and timed plain subtitles require human review; there is no claim of automatic face tracking, word alignment or semantic editorial certification.

### Configuration and Activation

Set repository variable `CLIPPER_API_ORIGIN` to the trusted HTTPS Worker origin. Worker bindings, approved workflow/ref, verified free-tier quota, schema and private R2 must exist first. Workflow content is read-only (`contents: read`) and its checkout cannot push. Dependencies and actions are pinned; no public releases or GitHub artifact storage are used.

The runner consumes shared protocol v1:

- `GET /runner/jobs/:id` → `{job,assets:[{asset_id,sha256,size,mime}]}`
- `GET /runner/assets/:sha?job_id=:id` → authorized private source stream
- `PUT /runner/jobs/:id/artifacts/:kind` with `Content-Type`, `Content-Length`, `X-Content-SHA256` → `{object_key,sha256,size,kind,mime}`
- `POST /runner/jobs/:id/result` → `{status,build_id,artifacts,qa?,error?}`

Every request mints fresh OIDC. Redirects are forbidden; FFmpeg source protocols/containers are allowlisted. No secret appears in URLs, process arguments, callbacks or logs. `build_id` is the exact completed Hypit CLI submission ID, and `null` for analysis or failure before submission. No latest-run/build lookup exists.

---

## 2. OpenShorts Cloud Reframing Workflow (`.github/workflows/openshorts-render.yml`)

Offloads YOLOv8 speaker/person detection (`engine/layout_engine.py`) and FFmpeg 1080×1920 vertical rendering + subtitle/hook/outro composition (`engine/render_worker.py`) to GitHub Actions runners (`ubuntu-latest`, 120-minute timeout, `contents: read`).

- **Orchestrator**: `scripts/openshorts_render_cloud.py` (`DEFAULT_REPO = "akhmadozy/hypit-render-farm"`, `DEFAULT_WORKFLOW = "openshorts-render.yml"`).
- **Worker Entrypoint**: `python3 engine/render_worker.py --manifest job_manifest.json --output output.mp4`.
- **Supported Layout Modes**: `SPLIT`, `TRACK`, `GENERAL`, `SCREENCAST`.
- **Fail-Closed Checks**: Strict manifest validation (`validate_job_manifest`), `-avoid_negative_ts make_zero` post-`-i`, FFmpeg decode integrity + `ffprobe` 1080×1920 verification, and human approval gate (Human Gate 4) before any social publishing.

---

## Local Diagnostics

Use the Clipper virtualenv when this farm has no `.venv`:

```sh
# Hypit OIDC diagnostic dry-run
/Users/ozy/Projects/Clipper/.venv/bin/python scripts/render_cloud.py \
  --job-id job_example --repo akhmadozy/hypit-render-farm --ref refs/heads/main --dry-run

# OpenShorts manifest validation dry-run using test fixture
/Users/ozy/Projects/Clipper/.venv/bin/python scripts/openshorts_render_cloud.py \
  --manifest tests/fixtures/sample_podcast_manifest.json --dry-run

# Full unit & contract test suite
/Users/ozy/Projects/Clipper/.venv/bin/pytest -q tests/ -o cache_dir=/tmp/hypit-farm-pytest-cache
```

Legacy project preflight and asset lookup helpers (`scripts/render_cloud.py --project <slug> --project-dir <external_path> --dry-run`) remain available for external Layer-3 directories; legacy project dispatch, auto Git add/commit/push and public release upload in `render_cloud.py` are disabled. Live `--job-id` dispatch is a low-level integration diagnostic: the authoritative Worker must reconcile and persist its returned run ID. It dispatches once and fails `DISPATCH_UNKNOWN` on ambiguous responses; never redispatch blindly. Production uses the Worker dispatcher so exact run binding is durable.

Full cloud rendering, OIDC interoperability, private R2 transfer and human approval pilots remain activation acceptance checks. Passing local fixtures or the native author compiler does not certify rendered production quality.

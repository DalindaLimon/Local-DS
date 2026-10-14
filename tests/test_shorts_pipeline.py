"""End-to-end test of download_short with a fake yt-dlp and the real ffmpeg."""

import json
import shutil
import subprocess
import sys
import textwrap

import pytest

from app import shorts

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make_source(path, vcodec: str, size: str):
    args = ["-f", "lavfi", "-i", f"testsrc2=s={size}:r=25:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2"]
    if vcodec == "vp9":
        args += ["-c:v", "libvpx-vp9", "-b:v", "200k", "-deadline", "realtime", "-c:a", "libopus"]
    else:
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, "-shortest", str(path)], check=True)


@pytest.fixture
def fake_ytdlp(tmp_path, monkeypatch):
    """Replace yt-dlp with a script that copies a prepared file to the -o target."""

    def install(src_file):
        script = tmp_path / "fake_ytdlp.py"
        script.write_text(
            textwrap.dedent(f"""
            import json, shutil, sys
            args = sys.argv[1:]
            out = args[args.index("-o") + 1]
            ext = "{src_file.suffix.lstrip(".")}"
            shutil.copy("{src_file}", out.replace("%(ext)s", ext))
            json.dump({{"title": "Fake short", "channel": "Fake Channel", "channel_id": "UCfake",
                       "timestamp": 1700000000}}, open(out.replace("%(ext)s", "info.json"), "w"))
            """)
        )
        monkeypatch.setattr(shorts, "ytdlp_base", lambda: [sys.executable, str(script)])

    return install


@pytest.mark.parametrize(
    ("vcodec", "size", "ext", "expect_w", "expect_h"),
    [
        ("h264", "360x640", "mp4", 360, 640),  # already fine -> remux only
        ("vp9", "360x640", "webm", 360, 640),  # wrong codec -> re-encode
        ("h264", "1080x1920", "mp4", 720, 1280),  # too big -> scaled to MAX_HEIGHT short side
    ],
)
def test_download_short_produces_ios_friendly_mp4(
    settings, tmp_path, fake_ytdlp, vcodec, size, ext, expect_w, expect_h
):
    settings.hwaccel = "none"
    if vcodec == "vp9":
        probe = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
        if "libvpx-vp9" not in probe.stdout:
            pytest.skip("ffmpeg without libvpx")
    src = tmp_path / f"source.{ext}"
    _make_source(src, vcodec, size)
    fake_ytdlp(src)

    meta = shorts.download_short("abcdefghijk", settings)

    video = settings.videos_dir / "abcdefghijk.mp4"
    assert video.exists() and meta["file_path"] == "abcdefghijk.mp4"
    assert (settings.thumbs_dir / "abcdefghijk.jpg").exists()
    info = shorts._probe(video)
    assert info["vcodec"] == "h264" and info["acodec"] == "aac"
    assert (info["width"], info["height"]) == (expect_w, expect_h)
    assert meta["title"] == "Fake short" and meta["channel_id"] == "UCfake"
    assert meta["published_at"] == 1700000000
    # faststart: the moov atom comes before mdat so iOS can start playing immediately
    head = video.read_bytes()[:200_000]
    assert head.find(b"moov") < head.find(b"mdat")
    # temp folder cleaned up
    assert not any(settings.tmp_dir.iterdir())


def test_failed_download_leaves_nothing(settings, monkeypatch, tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys; sys.stderr.write('ERROR: Video unavailable\\n'); sys.exit(1)")
    monkeypatch.setattr(shorts, "ytdlp_base", lambda: [sys.executable, str(script)])
    with pytest.raises(shorts.ShortsError, match="Video unavailable"):
        shorts.download_short("abcdefghijk", settings)
    assert not any(settings.videos_dir.iterdir())
    assert not any(settings.tmp_dir.iterdir())


def test_resolve_channel_parses_ytdlp_json(monkeypatch, tmp_path):
    payload = {
        "channel_id": "UC" + "x" * 22,
        "channel": "Jeff Geerling",
        "description": "Pi clusters",
        "tags": ["homelab"],
    }
    script = tmp_path / "chan.py"
    script.write_text(f"import json; print(json.dumps({payload!r}))")
    monkeypatch.setattr(shorts, "ytdlp_base", lambda: [sys.executable, str(script)])
    ch = shorts.resolve_channel("https://www.youtube.com/@JeffGeerling")
    assert ch["channel_id"] == payload["channel_id"]
    assert ch["channel_url"].endswith(payload["channel_id"])
    assert ch["title"] == "Jeff Geerling"
    json.dumps(ch)

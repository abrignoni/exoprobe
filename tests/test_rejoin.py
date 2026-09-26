"""Finding ExoPlayer caches in a folder and rejoining what they hold.

The caches are built here the way ExoPlayer writes them (androidx/media 1.11.1,
``CachedContentIndex``, ``SimpleCacheSpan``), around the ffmpeg fixtures in
``fixtures/dash/``: ffmpeg's test pattern and a 440 Hz tone, 3 s, written as a DASH
SegmentList, so representation 0 is the video (init-0.mp4, seg-0-1 to 3) and
representation 1 the audio (init-1.mp4, seg-1-1 to 4):

    ffmpeg -f lavfi -i testsrc=size=160x120:rate=10 -f lavfi -i sine=frequency=440:sample_rate=22050 \\
        -t 3 -map 0:v -map 1:a -c:v libx264 -g 10 -keyint_min 10 -sc_threshold 0 -pix_fmt yuv420p \\
        -c:a aac -b:a 32k -f dash -seg_duration 1 -use_template 0 -use_timeline 0 \\
        -init_seg_name 'init-$RepresentationID$.mp4' -media_seg_name 'seg-$RepresentationID$-$Number$.m4s' \\
        stream.mpd
"""

# ``(r,) = rejoin(...)`` asserts exactly one record; pylint cannot see the list's length.
# pylint: disable=unbalanced-tuple-unpacking

import hashlib
import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

import exoprobe

FIX = Path(__file__).parent / "fixtures" / "dash"
BASE = "https://cdn.example.net/dash/"
APP = "data/data/com.example.player/cache/exo"
TS = 1_700_000_000_000
VIDEO = ["init-0.mp4", "seg-0-1.m4s", "seg-0-2.m4s", "seg-0-3.m4s"]
AUDIO = ["init-1.mp4", "seg-1-1.m4s", "seg-1-2.m4s", "seg-1-3.m4s", "seg-1-4.m4s"]
ROOT = Path(__file__).resolve().parent.parent


def _utf(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def _meta(length: int) -> bytes:
    return struct.pack(">i", 1) + _utf("exo_len") + struct.pack(">i", 8) + struct.pack(">q", length)


def _exi(entries: dict, *, flags: int = 0) -> bytes:
    body = struct.pack(">i", len(entries))
    for cid, (key, length) in entries.items():
        body += struct.pack(">i", cid) + _utf(key) + _meta(length)
    return struct.pack(">ii", 2, flags) + body + struct.pack(">i", 0)


def _write(folder: Path, files: dict) -> Path:
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return folder


def _v3(items: dict, *, pieces: dict | None = None) -> dict:
    """One cached item per entry of ``items`` ({address: bytes}); ``pieces`` can split
    an item ({address: [(position, size)]})."""
    out, idx = {}, {}
    for cid, (key, data) in enumerate(items.items(), 1):
        for n, (pos, size) in enumerate((pieces or {}).get(key, [(0, len(data))])):
            out[f"{APP}/{cid % 10}/{cid}.{pos}.{TS + cid * 10 + n}.v3.exo"] = data[pos:pos + size]
        idx[cid] = (key, len(data))
    out[f"{APP}/{exoprobe.INDEX_NAME}"] = _exi(idx)
    return out


def _dash_items(extra: dict | None = None) -> dict:
    files = {BASE + n: (FIX / n).read_bytes() for n in ["stream.mpd", *VIDEO, *AUDIO]}
    files.update(extra or {})
    return files


def _one(caches):
    assert len(caches) == 1
    return caches[0]


def test_names():
    assert exoprobe.parse_piece_name(f"{APP}/7/17.1048576.1700000000123.v3.exo") == \
        ("v3", 17, 1048576, 1700000000123)
    got = exoprobe.parse_piece_name("https%3A%2F%2Fa.example%2Fv.mp4.0.5.v2.exo")
    assert got == ("v2", "https://a.example/v.mp4", 0, 5)
    assert exoprobe.is_cache_name("x/cached_content_index.exi.bak")
    assert exoprobe.is_cache_name("1a2b3c.uid") and not exoprobe.is_cache_name("video.mp4")
    assert exoprobe.cache_root(f"{APP}/7/17.0.1.v3.exo") == APP
    assert exoprobe.app_folder(APP) == "com.example.player"


def test_an_item_split_in_pieces_is_joined_in_order(tmp_path):
    data = b"".join((FIX / n).read_bytes() for n in VIDEO)
    key = "https://media.example.net/clip.mp4"
    third = len(data) // 3
    src = _write(tmp_path / "ev", _v3({key: data}, pieces={key: [(2 * third, len(data)),
                                                                 (0, third), (third, third)]}))
    c = _one(exoprobe.find_caches(src))
    assert (c.root, c.version, c.index_from) == (APP, "v3", exoprobe.INDEX_NAME)
    (r,) = exoprobe.rejoin(c, tmp_path / "out")
    assert (tmp_path / "out" / r["file"]).read_bytes() == data
    assert (r["kind"], r["state"], r["key"], r["pieces_joined"]) == ("video", "complete", key, 3)
    assert r["last_touched_ms"] == TS + 12


def test_a_gap_stops_the_join_and_the_rest_is_counted(tmp_path):
    data = bytes(range(256)) * 100
    key = "https://media.example.net/a.bin"
    src = _write(tmp_path / "ev", _v3({key: data}, pieces={key: [(0, 1000), (2000, 1000), (3000, 500)]}))
    (r,) = exoprobe.rejoin(_one(exoprobe.find_caches(src)), tmp_path / "out")
    assert (r["bytes"], r["gap_at"], r["pieces_left_out"], r["state"]) == (1000, 1000, 2, "stops at a gap")
    assert (tmp_path / "out" / r["file"]).read_bytes() == data[:1000]


def test_an_item_with_no_start_is_recorded_not_written(tmp_path):
    key = "https://media.example.net/b.bin"
    src = _write(tmp_path / "ev", _v3({key: b"x" * 50}, pieces={key: [(10, 40)]}))
    (r,) = exoprobe.rejoin(_one(exoprobe.find_caches(src)), tmp_path / "out")
    assert r["status"] == "no start" and "file" not in r
    assert not list((tmp_path / "out").iterdir())


def test_the_backup_index_wins(tmp_path):
    key = "https://media.example.net/c.bin"
    files = _v3({key: b"abc"})
    files[f"{APP}/{exoprobe.INDEX_NAME}"] = _exi({1: ("https://wrong.example/", 3)})
    files[f"{APP}/{exoprobe.INDEX_NAME}.bak"] = _exi({1: (key, 3)})
    c = _one(exoprobe.find_caches(_write(tmp_path / "ev", files)))
    assert (c.index_from, c.key(1)) == (exoprobe.INDEX_NAME + ".bak", key)


def test_an_encrypted_index_is_named_and_no_key_invented(tmp_path):
    files = _v3({"https://media.example.net/d.bin": b"abc"})
    files[f"{APP}/{exoprobe.INDEX_NAME}"] = _exi({1: ("https://x.example/", 3)}, flags=1)
    c = _one(exoprobe.find_caches(_write(tmp_path / "ev", files)))
    assert (c.index_from, c.key(1)) == ("index encrypted", None)


def test_the_index_database_is_read_from_a_copy(tmp_path):
    key = "https://media.example.net/e.mp4"
    data = (FIX / "init-0.mp4").read_bytes()
    src = tmp_path / "ev"
    _write(src, {f"{APP}/1/1.0.{TS}.v3.exo": data, f"{APP}/3f2a.uid": b""})
    db = src / "data/data/com.example.player/databases" / exoprobe.DB_NAME
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute('CREATE TABLE "ExoPlayerCacheIndex3f2a" (id INTEGER PRIMARY KEY, key TEXT, metadata BLOB)')
    con.execute('INSERT INTO "ExoPlayerCacheIndex3f2a" VALUES (1, ?, ?)', (key, _meta(len(data))))
    con.commit()
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in db.parent.iterdir()}
    c = _one(exoprobe.find_caches(src))
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in db.parent.iterdir()}
    con.close()
    assert c.index_from == f"{exoprobe.DB_NAME} table {exoprobe.TABLE_PREFIX}3f2a"
    assert c.key(1) == key and c.entry(1)["length"] == len(data)
    assert after == before


def test_older_caches_carry_the_key_in_the_name(tmp_path):
    key = "https://media.example.net/f.mp4"
    esc = key.replace(":", "%3A").replace("/", "%2F")
    src = _write(tmp_path / "ev", {f"{APP}/{esc}.0.{TS}.v2.exo": b"hello"})
    c = _one(exoprobe.find_caches(src))
    (r,) = exoprobe.rejoin(c, tmp_path / "out")
    assert (c.version, c.index_from, r["key"], r["kind"]) == ("v2", "file names", key, "other")


def test_a_dash_stream_is_joined_from_its_manifest_and_combined(tmp_path):
    src = _write(tmp_path / "ev", _v3(_dash_items()))
    out = tmp_path / "out"
    recs = exoprobe.rejoin(_one(exoprobe.find_caches(src)), out)
    by = {r["file"]: r for r in recs if r["status"] == "written"}
    video = next(r for r in by.values() if r.get("dash") and r["kind"] == "video")
    audio = next(r for r in by.values() if r.get("dash") and r["kind"] == "audio")
    assert (out / video["file"]).read_bytes() == b"".join((FIX / n).read_bytes() for n in VIDEO)
    assert (out / audio["file"]).read_bytes() == b"".join((FIX / n).read_bytes() for n in AUDIO)
    assert video["dash"]["segments_joined"] == 3 and video["key"] == BASE + "stream.mpd"
    (av,) = [r for r in by.values() if r.get("combined")]
    assert exoprobe.file_handlers(out / av["file"]) == ["vide", "soun"]
    assert av["combined"]["audio_tracks"] == [{"file": audio["file"], "bandwidth": "32000",
                                               "segments": "4 of 4"}]
    # the segments a stream holds are not written again one by one
    # the manifest is kept as it was cached, under its item id and with no extension
    assert sorted(p.name for p in out.iterdir()) == sorted(
        [video["file"], audio["file"], av["file"], "exoplayer_1"])
    assert by["exoplayer_1"]["kind"] == "other"


def test_two_languages_both_go_in_as_alternatives(tmp_path):
    mpd = (FIX / "stream.mpd").read_text()
    start = mpd.index('<AdaptationSet id="1"')
    block = mpd[start:mpd.index("</AdaptationSet>", start) + len("</AdaptationSet>")]
    other = (block.replace('AdaptationSet id="1"', 'AdaptationSet id="2" lang="es"')
             .replace('Representation id="1"', 'Representation id="9"')
             .replace("init-1.mp4", "init-9.mp4").replace("seg-1-", "seg-9-"))
    mpd = mpd.replace('AdaptationSet id="1"', 'AdaptationSet id="1" lang="en"')
    extra = {BASE + "stream.mpd": mpd.replace("</Period>", other + "</Period>").encode()}
    for n in AUDIO:
        extra[BASE + n.replace("init-1", "init-9").replace("seg-1-", "seg-9-")] = (FIX / n).read_bytes()
    src = _write(tmp_path / "ev", _v3(_dash_items(extra)))
    recs = exoprobe.rejoin(_one(exoprobe.find_caches(src)), tmp_path / "out")
    (av,) = [r for r in recs if r.get("combined")]
    assert [t["lang"] for t in av["combined"]["audio_tracks"]] == ["en", "es"]
    assert exoprobe.file_handlers(tmp_path / "out" / av["file"]) == ["vide", "soun", "soun"]


def test_whole_file_streams_pair_through_their_manifest(tmp_path):
    video = b"".join((FIX / n).read_bytes() for n in VIDEO)
    audio = b"".join((FIX / n).read_bytes() for n in AUDIO)
    mpd = (b'<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>'
           b'<AdaptationSet><Representation id="v" mimeType="video/mp4"><BaseURL>DASH_120.mp4</BaseURL>'
           b'<SegmentBase indexRange="0-1"/></Representation></AdaptationSet>'
           b'<AdaptationSet lang="en"><Representation id="a" mimeType="audio/mp4"><BaseURL>DASH_audio.mp4'
           b'</BaseURL><SegmentBase indexRange="0-1"/></Representation></AdaptationSet>'
           b'<AdaptationSet lang="es"><Representation id="b" mimeType="audio/mp4"><BaseURL>DASH_b.mp4'
           b'</BaseURL><SegmentBase indexRange="0-1"/></Representation></AdaptationSet></Period></MPD>')
    cut = len((FIX / AUDIO[0]).read_bytes()) + len((FIX / AUDIO[1]).read_bytes())
    items = {BASE + "m.mpd": mpd, BASE + "DASH_120.mp4": video, BASE + "DASH_audio.mp4": audio,
             BASE + "DASH_b.mp4": audio}
    files = _v3(items, pieces={BASE + "DASH_b.mp4": [(0, cut)]})     # cached only in part
    recs = exoprobe.rejoin(_one(exoprobe.find_caches(_write(tmp_path / "ev", files))), tmp_path / "out")
    (av,) = [r for r in recs if r.get("combined")]
    assert [t["lang"] for t in av["combined"]["audio_tracks"]] == ["en"]
    assert av["combined"]["audio_left_out"] == 1
    assert exoprobe.file_handlers(tmp_path / "out" / av["file"]) == ["vide", "soun"]
    v = next(r for r in recs if r.get("representation", {}).get("id") == "v")
    assert v["kind"] == "video" and v["manifest_key"] == BASE + "m.mpd"


def test_the_command_line(tmp_path):
    src = _write(tmp_path / "ev", _v3(_dash_items()))
    scan = subprocess.run([sys.executable, str(ROOT / "exoprobe.py"), "scan", str(src)],
                          capture_output=True, text=True, check=True).stdout
    assert f"{APP}  (v3, 10 items, index: {exoprobe.INDEX_NAME})" in scan
    subprocess.run([sys.executable, str(ROOT / "exoprobe.py"), "rejoin", str(src), "-o", str(tmp_path / "out")],
                   capture_output=True, text=True, check=True)
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert sum(1 for r in report if r.get("combined")) == 1
    assert all((tmp_path / "out" / r["folder"] / r["file"]).is_file() for r in report if r["status"] == "written")


def test_it_needs_nothing_outside_the_standard_library():
    """``-S`` skips site-packages, so only the standard library can be imported."""
    r = subprocess.run([sys.executable, "-S", "-c", "import exoprobe; print(exoprobe.__version__)"],
                       cwd=ROOT, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


def test_a_whole_file_video_cut_short_is_not_combined(tmp_path):
    """A clean fragment boundary would mux, so the cut is made there; the index still
    records the full length, which is what marks the video incomplete."""
    video = b"".join((FIX / n).read_bytes() for n in VIDEO)
    audio = b"".join((FIX / n).read_bytes() for n in AUDIO)
    mpd = (b'<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>'
           b'<AdaptationSet><Representation id="v" mimeType="video/mp4"><BaseURL>v.mp4</BaseURL>'
           b'<SegmentBase indexRange="0-1"/></Representation></AdaptationSet><AdaptationSet>'
           b'<Representation id="a" mimeType="audio/mp4"><BaseURL>a.mp4</BaseURL>'
           b'<SegmentBase indexRange="0-1"/></Representation></AdaptationSet></Period></MPD>')
    cut = len((FIX / VIDEO[0]).read_bytes()) + len((FIX / VIDEO[1]).read_bytes())
    items = {BASE + "m.mpd": mpd, BASE + "v.mp4": video, BASE + "a.mp4": audio}
    files = _v3(items, pieces={BASE + "v.mp4": [(0, cut)]})
    recs = exoprobe.rejoin(_one(exoprobe.find_caches(_write(tmp_path / "ev", files))), tmp_path / "out")
    assert not [r for r in recs if r.get("combined")]
    v = next(r for r in recs if r.get("representation", {}).get("id") == "v")
    assert v["state"] == "partial"


def test_of_two_pieces_at_one_position_the_last_touched_is_used(tmp_path):
    """ExoPlayer renames a piece to its new last-touch time when it touches it
    (``CachedContent.setLastTouchTimestamp``), so a live cache holds one file per
    position; where an extraction holds two, the later time is the later name."""
    key = "https://media.example.net/g.bin"
    files = {f"{APP}/1/1.0.{TS}.v3.exo": b"older",
             f"{APP}/1/1.0.{TS + 5}.v3.exo": b"newer",
             f"{APP}/{exoprobe.INDEX_NAME}": _exi({1: (key, 5)})}
    (r,) = exoprobe.rejoin(_one(exoprobe.find_caches(_write(tmp_path / "ev", files))), tmp_path / "out")
    assert (tmp_path / "out" / r["file"]).read_bytes() == b"newer"
    assert r["pieces_joined"] == 1 and r["pieces_left_out"] == 0


def test_older_pieces_spread_over_numbered_subfolders_are_one_cache(tmp_path):
    """Instagram (samsungs20_a13) writes v2 pieces in subfolders numbered 0 to 28, one
    item's pieces in several of them; they are one cache and join as one item."""
    key = "3788992813690909712_5857222413.null.1376288957371955v"
    data = bytes(range(256)) * 40
    base = "data/data/com.example.player/cache/videocache"
    files = {f"{base}/1/{key}.0.{TS}.v2.exo": data[:4000],
             f"{base}/10/{key}.4000.{TS + 1}.v2.exo": data[4000:7000],
             f"{base}/14/{key}.7000.{TS + 2}.v2.exo": data[7000:]}
    c = _one(exoprobe.find_caches(_write(tmp_path / "ev", files)))
    assert c.root == base
    (r,) = exoprobe.rejoin(c, tmp_path / "out")
    assert (tmp_path / "out" / r["file"]).read_bytes() == data and r["pieces_joined"] == 3


def test_a_raw_userdata_partition_names_the_app():
    assert exoprobe.app_folder("SamsungS20/Volumes/userdata/data/com.pinterest/cache/video") == "com.pinterest"


def test_mp4_layout_names_an_init_segment_a_fragmented_movie_and_a_cut_file(tmp_path):
    init = (FIX / "init-0.mp4").read_bytes()
    whole = b"".join((FIX / n).read_bytes() for n in VIDEO)
    prog = (Path(__file__).parent / "fixtures" / "mux" / "video.mp4").read_bytes()
    cases = {"init.mp4": init, "whole.mp4": whole, "prog.mp4": prog, "cut.mp4": prog[:-100],
             "seg.m4s": (FIX / "seg-0-1.m4s").read_bytes(), "text.txt": b"not a box at all"}
    got = {}
    for name, data in cases.items():
        (tmp_path / name).write_bytes(data)
        got[name] = exoprobe.mp4_layout(tmp_path / name)
    assert got["init.mp4"] == {"moov": True, "mvex": True, "moof": False, "cut": False}
    assert got["whole.mp4"] == {"moov": True, "mvex": True, "moof": True, "cut": False}
    assert got["prog.mp4"] == {"moov": True, "mvex": False, "moof": False, "cut": False}
    assert got["cut.mp4"]["cut"] is True
    assert got["seg.m4s"]["moof"] is True and got["seg.m4s"]["moov"] is False
    assert got["text.txt"] is None

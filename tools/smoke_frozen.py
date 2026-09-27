"""Check that a built exoprobe gives the same output as the Python file it was built from.

    python tools/smoke_frozen.py <source folder> <executable> [<executable args> ...]

<source folder> is a checkout holding exoprobe.py and tests/ (the build workflow checks
out the tag being released there). The caches are built with the tests' own helpers, the
way ExoPlayer writes them, for three apps: a DASH stream under a cached_content_index.exi,
an HLS stream with two audio renditions, and an item indexed in an exoplayer_internal.db
table. Then `scan`, `rejoin` and `mux` are run once through `python exoprobe.py` and once
through the executable, and every file each writes must be byte-identical, report.json
included. The executable's --version must name the source's __version__.
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        sys.exit(f"FAILED ({r.returncode}): {' '.join(cmd)}\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")
    return r.stdout


def tree(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def build_evidence(src: Path, ev: Path) -> None:
    sys.path[:0] = [str(src), str(src / "tests")]
    import exoprobe                     # pylint: disable=import-outside-toplevel
    import test_rejoin as t             # pylint: disable=import-outside-toplevel

    def moved(files: dict, pkg: str) -> dict:
        return {k.replace(t.APP, f"data/data/{pkg}/cache/exo", 1): v for k, v in files.items()}

    t._write(ev, moved(t._v3(t._dash_items()), "com.example.dash"))     # pylint: disable=protected-access
    t._write(ev, moved(t._v3(t._hls_items()), "com.example.hls"))       # pylint: disable=protected-access

    key = "https://media.example.net/e.mp4"
    data = (t.FIX / "init-0.mp4").read_bytes()
    app = "data/data/com.example.db"
    t._write(ev, {f"{app}/cache/exo/1/1.0.{t.TS}.v3.exo": data,          # pylint: disable=protected-access
                  f"{app}/cache/exo/3f2a.uid": b""})
    db = ev / app / "databases" / exoprobe.DB_NAME
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute(f'CREATE TABLE "{exoprobe.TABLE_PREFIX}3f2a" (id INTEGER PRIMARY KEY, key TEXT, metadata BLOB)')
    con.execute(f'INSERT INTO "{exoprobe.TABLE_PREFIX}3f2a" VALUES (1, ?, ?)',
                (key, t._meta(len(data))))                               # pylint: disable=protected-access
    con.commit()
    con.close()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.exit(__doc__)
    src = Path(argv[0]).resolve()
    exe = [str(Path(argv[1]).resolve()) if Path(argv[1]).exists() else argv[1], *argv[2:]]
    py = [sys.executable, str(src / "exoprobe.py")]
    source_version = run(py + ["--version"], src).strip()
    built_version = run(exe + ["--version"], src).strip()
    print("source:", source_version, "| built:", built_version)
    assert built_version == source_version, (built_version, source_version)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        build_evidence(src, work / "ev")
        caches = run(py + ["scan", "ev"], work).count("  (v")
        assert caches == 3, f"expected 3 caches in the evidence, the source found {caches}"

        mux_in = src / "tests" / "fixtures" / "mux"
        for name, cmd in (("py", py), ("exe", exe)):
            (work / name).mkdir()
            (work / name / "scan.txt").write_text(run(cmd + ["scan", "ev"], work), encoding="utf-8")
            run(cmd + ["rejoin", "ev", "-o", f"{name}/rejoin"], work)
            run(cmd + ["mux", str(mux_in / "video.mp4"), str(mux_in / "audio.m4a"),
                       "-o", f"{name}/muxed.mp4"], work)

        want, got = tree(work / "py"), tree(work / "exe")
        combined = sum(1 for n in want if n.startswith("rejoin/") and "report.json" not in n)
        print(f"{len(want)} files from the source, {len(got)} from the executable, "
              f"{combined} of them rejoined media")
        if want != got:
            for n in sorted(set(want) | set(got)):
                if want.get(n) != got.get(n):
                    print("DIFFERS:", n, want.get(n), got.get(n))
            return 1
        assert "rejoin/report.json" in want and "muxed.mp4" in want and combined >= 6, sorted(want)
    print("the executable wrote the same bytes as the source for scan, rejoin and mux")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

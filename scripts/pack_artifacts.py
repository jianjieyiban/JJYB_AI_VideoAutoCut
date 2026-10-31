#!/usr/bin/env python3
"""打包 Executa 发布产物：
- Windows onedir -> dist/jjyb-ai-smartcut-<ver>-windows-x86_64.zip
- Linux onedir   -> dist/jjyb-ai-smartcut-<ver>-linux-x86_64.tar.gz
产物根平铺（entrypoint 位于压缩包根，与 executa.json entrypoint 一致）。

用法：
  python pack_artifacts.py 1.0.5 \\
      --win  executas/jjyb-ai-smartcut/dist/jjyb-ai-smartcut \\
      --linux r'\\\\wsl.localhost\\<wsl-distro>\\home\\<user>\\jjyb\\dist\\jjyb-ai-smartcut'
"""
import argparse
import tarfile
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "executas" / "jjyb-ai-smartcut"


def pack_zip(onedir: Path, out: Path) -> None:
    files = [f for f in sorted(onedir.rglob("*")) if f.is_file()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in files:
            z.write(f, f.relative_to(onedir).as_posix())
    print(f"packed {len(files)} files -> {out.name} ({out.stat().st_size/1e6:.1f} MB)")


def pack_targz(onedir: Path, out: Path) -> None:
    entries = [f for f in sorted(onedir.rglob("*")) if f.is_file() or f.is_symlink()]
    with tarfile.open(out, "w:gz") as t:
        for f in entries:
            t.add(f, arcname=f.relative_to(onedir).as_posix())
    print(f"packed {len(entries)} entries -> {out.name} ({out.stat().st_size/1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--win", default=str(BASE / "dist" / "jjyb-ai-smartcut"))
    ap.add_argument("--linux", default=None)
    args = ap.parse_args()

    jobs = []
    win_dir = Path(args.win)
    if (win_dir / "jjyb-ai-smartcut.exe").is_file():
        jobs.append((pack_zip, win_dir, BASE / "dist" / f"jjyb-ai-smartcut-{args.version}-windows-x86_64.zip"))
    if args.linux:
        lin_dir = Path(args.linux)
        if (lin_dir / "jjyb-ai-smartcut").is_file():
            jobs.append((pack_targz, lin_dir, BASE / "dist" / f"jjyb-ai-smartcut-{args.version}-linux-x86_64.tar.gz"))
    if not jobs:
        print("no onedir artifacts found to pack", file=sys.stderr)
        return 2
    for fn, src, out in jobs:
        if out.exists():
            out.unlink()
        fn(src, out)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

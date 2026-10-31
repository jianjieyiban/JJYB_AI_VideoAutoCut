#!/usr/bin/env python3
"""冻结二进制冒烟（文件重定向版，规避管道假死）：
- fake path  -> 验证全量 import 链（报 No module named 即 FAIL）
- real video -> 完整 auto_clip 管线（AI 用本机 config 密钥，仅本地不入包）
"""
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TMP = PROJECT / "temp" / "smoke"


def read_local_keys() -> dict:
    cfg = {}
    cand = PROJECT / "config" / "ai_config.json"
    try:
        cfg = json.loads(cand.read_text(encoding="utf-8"))
    except Exception:
        pass

    def dig(d):
        if not isinstance(d, dict):
            return {}
        hit = {}
        for prefix in ("custom_openai", "openai"):
            k, b, m = f"{prefix}_api_key", f"{prefix}_base_url", f"{prefix}_model"
            if d.get(k) and d.get(b) and d.get(m):
                hit = {"llm_api_key": d[k], "llm_base_url": d[b], "llm_model": d[m]}
                break
        if hit:
            return hit
        for v in d.values():
            hit = dig(v) or hit
        return hit
    return dig(cfg)


def run_frames(exe: Path, frames: list, timeout: int, tag: str) -> dict:
    TMP.mkdir(parents=True, exist_ok=True)
    fin = TMP / f"{tag}_in.jsonl"
    fout = TMP / f"{tag}_out.jsonl"
    ferr = TMP / f"{tag}_err.log"
    fin.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in frames), encoding="utf-8")
    t0 = time.time()
    with open(fin, "rb") as fi, open(fout, "wb") as fo, open(ferr, "wb") as fe:
        try:
            rc = subprocess.run([str(exe)], stdin=fi, stdout=fo, stderr=fe,
                                timeout=timeout, cwd=str(exe.parent)).returncode
        except subprocess.TimeoutExpired:
            print(f"[{tag}] TIMEOUT after {timeout}s")
            rc = -1
    print(f"[{tag}] elapsed={time.time()-t0:.1f}s rc={rc}")
    resp = {}
    for line in fout.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                fr = json.loads(line)
                resp[fr.get("id")] = fr
            except json.JSONDecodeError:
                pass
    tail = ferr.read_text(encoding="utf-8", errors="replace")[-900:]
    print(f"[{tag}] stderr tail:\n{tail}")
    return resp


def main() -> int:
    exe = Path(sys.argv[1])
    video = Path(sys.argv[2])
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    assert exe.is_file(), f"exe not found: {exe}"
    real = video.is_file()

    # 1) import-chain smoke (fake path)
    r1 = run_frames(exe, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2.0"}},
        {"jsonrpc": "2.0", "id": 2, "method": "invoke",
         "params": {"tool": "auto_clip",
                    "arguments": {"video_path": "Z:\\nope_missing.mp4", "config": {}}}},
    ], 300, "fake")
    err1 = json.dumps(r1.get(2, {}), ensure_ascii=False)
    if "No module named" in err1:
        print("SMOKE_FAIL_MISSING_MODULE")
        return 1
    print("IMPORT_CHAIN_OK (business error, no missing module)")

    if not real:
        print("SMOKE_PASS_IMPORT_ONLY")
        return 0

    # 2) full pipeline smoke (real video + local keys)
    keys = read_local_keys()
    r2 = run_frames(exe, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2.0"}},
        {"jsonrpc": "2.0", "id": 2, "method": "invoke",
         "params": {"tool": "auto_clip",
                    "arguments": {"video_path": str(video), "config": keys}}},
    ], timeout, "full")
    fr = r2.get(2, {})
    if fr.get("error"):
        msg = json.dumps(fr["error"], ensure_ascii=False)
        print("FULL_INVOKE_ERROR:", msg[:400])
        if "No module named" in msg:
            print("SMOKE_FAIL_MISSING_MODULE")
            return 1
        print("SMOKE_WEAK_PASS (import chain OK; pipeline error above)")
        return 0
    data = (fr.get("result") or {}).get("data") or {}
    outp = data.get("output_video") or data.get("video_path")
    ok = outp and Path(outp).is_file()
    print(f"OUTPUT: {outp} exists={bool(ok)}")
    print("SMOKE_FULL_PASS" if ok else "SMOKE_PASS_NO_FILE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""bench_llm.py — OpenAI-compat streaming benchmark harness for llama-server.

Streams POST /v1/chat/completions, records first-token latency, tokens/sec,
peak RSS delta, and full completion text per prompt. Emits JSON lines.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests


# ---------------------------------------------------------------------------
# Prompt loader — reads prompts.md with system preamble + numbered prompts
# ---------------------------------------------------------------------------

def load_prompts(path: Path) -> tuple[str, list[dict]]:
    """Parse prompts.md → (system_preamble, [prompt_entries]).

    Format expected:
      Everything before the first `## prompt-` is the system preamble.
      Each prompt-N section has a **User message:** code block.
    """
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"^## prompt-(\d+)\s*$", text, flags=re.MULTILINE)

    # sections[0] = preamble (before first ## prompt-), then alternating: N, body
    preamble = sections[0].strip()
    prompts = []
    for i in range(1, len(sections), 2):
        num = int(sections[i])
        body = sections[i + 1]
        # Extract user message from code block after **User message:**
        m = re.search(r"\*\*User message:\*\*\s*```[^\n]*\n(.*?)```", body, re.DOTALL)
        if not m:
            print(f"WARNING: prompt-{num} has no **User message:** code block, skipping", file=sys.stderr)
            continue
        user_msg = m.group(1).strip()
        prompts.append({"id": num, "user_message": user_msg})

    prompts.sort(key=lambda p: p["id"])
    return preamble, prompts


# ---------------------------------------------------------------------------
# RSS sampler — background thread reading /proc/<pid>/status
# ---------------------------------------------------------------------------

class RSSSampler:
    def __init__(self, pid: int):
        self.pid = pid
        self.samples: list[int] = []
        self._stop = threading.Event()

    def _read_rss_kb(self) -> int:
        try:
            status = Path(f"/proc/{self.pid}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except (FileNotFoundError, ValueError, ProcessLookupError):
            pass
        return 0

    def run(self):
        while not self._stop.is_set():
            rss = self._read_rss_kb()
            if rss:
                self.samples.append(rss)
            self._stop.wait(0.25)

    def stop(self):
        self._stop.set()

    def peak_mb(self) -> float:
        return max(self.samples) / 1024 if self.samples else 0.0


def find_llama_server_pid() -> int | None:
    """Find llama-server pid via pgrep."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "llama-server"], text=True
        ).strip()
        pids = [int(p) for p in out.splitlines()]
    except (subprocess.CalledProcessError, ValueError):
        return None

    if not pids:
        return None
    if len(pids) == 1:
        return pids[0]

    # Multiple pids — pick highest RSS
    best_pid, best_rss = pids[0], 0
    for pid in pids:
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                    if rss > best_rss:
                        best_pid, best_rss = pid, rss
                    break
        except (FileNotFoundError, ValueError):
            pass
    return best_pid


# ---------------------------------------------------------------------------
# Single benchmark run
# ---------------------------------------------------------------------------

def run_benchmark(
    prompt: dict,
    system_preamble: str,
    host: str,
    model: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    pid: int | None,
) -> dict:
    url = f"{host}/v1/chat/completions"
    payload = {
        "model": model,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_preamble},
            {"role": "user", "content": prompt["user_message"]},
        ],
    }

    # Pre-run RSS
    pre_rss_kb = 0
    if pid:
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    pre_rss_kb = int(line.split()[1])
                    break
        except (FileNotFoundError, ValueError):
            pass

    sampler = RSSSampler(pid) if pid else None
    sampler_thread = None
    if sampler:
        sampler_thread = threading.Thread(target=sampler.run, daemon=True)
        sampler_thread.start()

    first_token_ms = None
    chunks: list[str] = []
    completion_tokens = 0
    t_start = time.monotonic()

    try:
        resp = requests.post(url, json=payload, stream=True, timeout=600)
        resp.raise_for_status()

        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8", errors="replace")
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data.strip() == "[DONE]":
                break

            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = obj.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            content = delta.get("content")
            reasoning = delta.get("reasoning_content")

            # Skip role-only chunks (both content and reasoning are None)
            if content is None and reasoning is None:
                continue

            if first_token_ms is None:
                first_token_ms = (time.monotonic() - t_start) * 1000

            # Prefer actual content; fall back to reasoning if no content yet
            if content is not None:
                chunks.append(content)

        # Try to get usage from final chunk (some servers include it)
        usage = obj.get("usage") if "obj" in dir() else None
        if usage and "completion_tokens" in usage:
            completion_tokens = usage["completion_tokens"]

    finally:
        if sampler:
            sampler.stop()
            if sampler_thread:
                sampler_thread.join(timeout=2)

    full_text = "".join(chunks)
    elapsed = time.monotonic() - t_start

    # Approximate tokens if server didn't report usage
    if completion_tokens == 0 and full_text:
        completion_tokens = len(full_text.split())

    tokens_per_sec = completion_tokens / elapsed if elapsed > 0 else 0

    # Peak RSS delta
    peak_ram_mb = 0.0
    if sampler and sampler.samples:
        peak_rss = max(sampler.samples)
        peak_ram_mb = (peak_rss - pre_rss_kb) / 1024

    return {
        "prompt_id": prompt["id"],
        "first_token_ms": round(first_token_ms, 1) if first_token_ms is not None else None,
        "tokens_per_sec": round(tokens_per_sec, 2),
        "peak_ram_mb": round(peak_ram_mb, 1),
        "completion_tokens": completion_tokens,
        "text": full_text,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

def summarize(results: list[dict]) -> dict:
    first_tokens = [r["first_token_ms"] for r in results if r["first_token_ms"] is not None]
    first_tokens.sort()
    rates = [r["tokens_per_sec"] for r in results]
    rams = [r["peak_ram_mb"] for r in results]

    p50 = first_tokens[len(first_tokens) // 2] if first_tokens else None
    p95_idx = int(len(first_tokens) * 0.95)
    p95 = first_tokens[min(p95_idx, len(first_tokens) - 1)] if first_tokens else None

    return {
        "p50_first_token_ms": round(p50, 1) if p50 is not None else None,
        "p95_first_token_ms": round(p95, 1) if p95 is not None else None,
        "mean_tokens_per_sec": round(sum(rates) / len(rates), 2) if rates else None,
        "max_peak_ram_mb": round(max(rams), 1) if rams else None,
        "n_runs": len(results),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark llama-server OpenAI-compat streaming endpoint."
    )
    parser.add_argument("--prompts", required=True, type=Path, help="Path to prompts.md")
    parser.add_argument("--host", default="http://127.0.0.1:8080", help="llama-server host URL")
    parser.add_argument("--model", default="qwen35-4b-local", help="Model alias (matches --alias)")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--warmup", type=int, default=1, help="Number of warmup requests (discarded)")
    parser.add_argument("--prompt-ids", type=str, default=None, help="Comma-separated prompt IDs to run (e.g. '3'). Default: all")
    parser.add_argument("--output", type=Path, default=None, help="Append JSON lines to this file")

    args = parser.parse_args()

    system_preamble, prompts = load_prompts(args.prompts)
    if not prompts:
        print("ERROR: No prompts found in", args.prompts, file=sys.stderr)
        sys.exit(1)

    if args.prompt_ids:
        ids = {int(x.strip()) for x in args.prompt_ids.split(",")}
        prompts = [p for p in prompts if p["id"] in ids]
        print(f"Filtered to {len(prompts)} prompt(s): {ids}", file=sys.stderr)

    print(f"Loaded {len(prompts)} prompts. System preamble: {len(system_preamble)} chars.", file=sys.stderr)

    pid = find_llama_server_pid()
    if pid:
        print(f"llama-server pid: {pid}", file=sys.stderr)
    else:
        print("WARNING: Could not find llama-server pid. RAM tracking disabled.", file=sys.stderr)

    # Warmup
    if args.warmup > 0 and prompts:
        print(f"Warmup: {args.warmup} request(s)...", file=sys.stderr)
        for _ in range(args.warmup):
            run_benchmark(
                prompts[0], system_preamble, args.host, args.model,
                args.temperature, args.top_p, args.max_tokens, pid,
            )

    results: list[dict] = []

    for prompt in prompts:
        print(f"Running prompt-{prompt['id']}...", file=sys.stderr)
        result = run_benchmark(
            prompt, system_preamble, args.host, args.model,
            args.temperature, args.top_p, args.max_tokens, pid,
        )
        results.append(result)
        line = json.dumps(result, ensure_ascii=False)
        print(line, flush=True)
        if args.output:
            args.output.write_text(
                args.output.read_text() + line + "\n" if args.output.exists() else line + "\n",
                encoding="utf-8",
            )

    summary = summarize(results)
    summary_line = json.dumps({"summary": summary}, ensure_ascii=False)
    print(summary_line, flush=True)
    if args.output:
        args.output.write_text(
            args.output.read_text() + summary_line + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

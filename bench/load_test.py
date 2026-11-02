from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class RequestResult:
    scenario: str
    request_id: int
    success: bool
    ttft_seconds: float | None
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower

    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def create_prompt(scenario: str, request_id: int) -> str:
    marker = f"benchmark-request-{scenario}-{request_id}-{time.time_ns()}"

    if scenario == "short":
        return (
            f"{marker}\n"
            "Напиши короткую функцию Python, которая возвращает квадрат числа. "
            "Ответь только кодом."
        )

    code_lines = "\n".join(
        f"value_{request_id}_{index} = "
        f"({index} * 17 + {request_id}) % 97"
        for index in range(60)
    )

    return (
        f"{marker}\n"
        "Проанализируй следующий фрагмент Python-кода. "
        "Кратко опиши закономерность вычислений, возможные проблемы и предложи более компактную реализацию.\n\n"
        f"```python\n{code_lines}\n```"
    )


def send_request(
    *,
    scenario: str,
    request_id: int,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: float,
) -> RequestResult:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": create_prompt(scenario, request_id),
            }
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {
            "include_usage": True,
        },
    }

    request = urllib.request.Request(
        url=f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    started_at = time.perf_counter()
    first_token_at: float | None = None
    prompt_tokens = 0
    completion_tokens = 0

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()

                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()

                if data == "[DONE]":
                    break

                chunk: dict[str, Any] = json.loads(data)

                usage = chunk.get("usage")
                if usage:
                    prompt_tokens = int(usage.get("prompt_tokens", 0))
                    completion_tokens = int(
                        usage.get("completion_tokens", 0)
                    )

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                content = delta.get("content")

                if content and first_token_at is None:
                    first_token_at = time.perf_counter()

        finished_at = time.perf_counter()

        if first_token_at is None:
            return RequestResult(
                scenario=scenario,
                request_id=request_id,
                success=False,
                ttft_seconds=None,
                latency_seconds=finished_at - started_at,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error="Сервер не вернул ни одного токена.",
            )

        return RequestResult(
            scenario=scenario,
            request_id=request_id,
            success=True,
            ttft_seconds=first_token_at - started_at,
            latency_seconds=finished_at - started_at,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        message = f"HTTP {error.code}: {body[:500]}"

    except Exception as error:
        message = f"{type(error).__name__}: {error}"

    return RequestResult(
        scenario=scenario,
        request_id=request_id,
        success=False,
        ttft_seconds=None,
        latency_seconds=time.perf_counter() - started_at,
        prompt_tokens=0,
        completion_tokens=0,
        error=message,
    )


def summarize(
    scenario: str,
    results: list[RequestResult],
    wall_seconds: float,
    concurrency: int,
) -> dict[str, Any]:
    successful = [result for result in results if result.success]
    failed = [result for result in results if not result.success]

    if not successful:
        raise RuntimeError(
            f"Все запросы сценария {scenario!r} завершились ошибкой."
        )

    ttft = [
        result.ttft_seconds
        for result in successful
        if result.ttft_seconds is not None
    ]
    latencies = [result.latency_seconds for result in successful]

    prompt_tokens = sum(result.prompt_tokens for result in successful)
    completion_tokens = sum(
        result.completion_tokens for result in successful
    )

    return {
        "scenario": scenario,
        "requests": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "concurrency": concurrency,
        "wall_seconds": wall_seconds,
        "mean_prompt_tokens": statistics.mean(
            result.prompt_tokens for result in successful
        ),
        "mean_completion_tokens": statistics.mean(
            result.completion_tokens for result in successful
        ),
        "ttft_p50_seconds": percentile(ttft, 50),
        "ttft_p95_seconds": percentile(ttft, 95),
        "latency_p50_seconds": percentile(latencies, 50),
        "latency_p95_seconds": percentile(latencies, 95),
        "request_throughput_rps": len(successful) / wall_seconds,
        "output_throughput_tokens_per_second": (
            completion_tokens / wall_seconds
        ),
        "total_throughput_tokens_per_second": (
            (prompt_tokens + completion_tokens) / wall_seconds
        ),
    }


def run_scenario(
    *,
    scenario: str,
    request_count: int,
    concurrency: int,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: float,
) -> tuple[list[RequestResult], dict[str, Any]]:
    print(f"\nРазогрев сценария: {scenario}.")

    warmup = send_request(
        scenario=scenario,
        request_id=-1,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    if not warmup.success:
        raise RuntimeError(
            f"Разогрев {scenario!r} завершился ошибкой: {warmup.error}."
        )

    print(
        f"Запуск: scenario={scenario}, requests={request_count}, "
        f"concurrency={concurrency}."
    )

    started_at = time.perf_counter()
    results: list[RequestResult] = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                send_request,
                scenario=scenario,
                request_id=request_id,
                base_url=base_url,
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            for request_id in range(request_count)
        ]

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            status = "OK" if result.success else "ERROR"
            print(
                f"  request={result.request_id}: {status}, "
                f"latency={result.latency_seconds:.3f}s"
            )

            if result.error:
                print(f"    {result.error}")

    wall_seconds = time.perf_counter() - started_at

    return results, summarize(
        scenario,
        results,
        wall_seconds,
        concurrency,
    )


def print_markdown_table(summaries: list[dict[str, Any]]) -> None:
    print("\nТаблица для README.md:\n")
    print(
        "| Промпт | Средний input, токенов | TTFT p50, с | "
        "TTFT p95, с | Latency p50, с | Latency p95, с | "
        "Requests/s | Output tok/s | Total tok/s |"
    )
    print(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    )

    for item in summaries:
        print(
            f"| {item['scenario']} "
            f"| {item['mean_prompt_tokens']:.1f} "
            f"| {item['ttft_p50_seconds']:.3f} "
            f"| {item['ttft_p95_seconds']:.3f} "
            f"| {item['latency_p50_seconds']:.3f} "
            f"| {item['latency_p95_seconds']:.3f} "
            f"| {item['request_throughput_rps']:.3f} "
            f"| {item['output_throughput_tokens_per_second']:.2f} "
            f"| {item['total_throughput_tokens_per_second']:.2f} |"
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Нагрузочный тест OpenAI-совместимого vLLM API"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:18000",
    )
    parser.add_argument(
        "--model",
        default="deepseek-coder",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=6,
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=32,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600,
    )
    parser.add_argument(
        "--output",
        default="bench/results/load-test.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    api_key = os.environ.get("VLLM_API_KEY")

    if not api_key:
        raise SystemExit(
            "Переменная окружения VLLM_API_KEY не установлена."
        )

    if args.requests < 1:
        raise SystemExit("--requests должен быть не меньше 1.")

    if args.concurrency < 1:
        raise SystemExit("--concurrency должен быть не меньше 1.")

    all_results: dict[str, list[dict[str, Any]]] = {}
    summaries: list[dict[str, Any]] = []

    for scenario in ("short", "long"):
        results, summary = run_scenario(
            scenario=scenario,
            request_count=args.requests,
            concurrency=args.concurrency,
            base_url=args.base_url,
            api_key=api_key,
            model=args.model,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )

        all_results[scenario] = [
            asdict(result) for result in results
        ]
        summaries.append(summary)

    report = {
        "configuration": {
            "base_url": args.base_url,
            "model": args.model,
            "requests_per_scenario": args.requests,
            "concurrency": args.concurrency,
            "max_tokens": args.max_tokens,
        },
        "summaries": summaries,
        "results": all_results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print_markdown_table(summaries)
    print(f"\nПолный отчёт сохранён в: {output_path}")


if __name__ == "__main__":
    main()
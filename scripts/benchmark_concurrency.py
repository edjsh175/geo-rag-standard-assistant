"""Concurrency and throughput performance benchmark harness for GeoAI Knowledge Base.

Measures:
- PostGIS spatial operations / query throughput
- Distributed session lock contention and fairness
- Latency percentiles: min, p50, p95, p99, max
- Concurrent requests per second (QPS)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import statistics
import sys
import time
from typing import Callable, Coroutine, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark")


class BenchmarkResult:
    def __init__(self, name: str, latencies: List[float], errors: int, total_duration: float):
        self.name = name
        self.latencies = latencies  # in seconds
        self.errors = errors
        self.total_duration = total_duration

    @property
    def total_requests(self) -> int:
        return len(self.latencies) + self.errors

    @property
    def successful_requests(self) -> int:
        return len(self.latencies)

    @property
    def qps(self) -> float:
        return self.successful_requests / self.total_duration if self.total_duration > 0 else 0.0

    @property
    def min_latency_ms(self) -> float:
        return min(self.latencies) * 1000 if self.latencies else 0.0

    @property
    def max_latency_ms(self) -> float:
        return max(self.latencies) * 1000 if self.latencies else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return statistics.mean(self.latencies) * 1000 if self.latencies else 0.0

    def percentile_ms(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        k = (len(sorted_lat) - 1) * (p / 100.0)
        f = int(k)
        c = f + 1
        if c < len(sorted_lat):
            d0 = sorted_lat[f] * (c - k)
            d1 = sorted_lat[c] * (k - f)
            return (d0 + d1) * 1000
        return sorted_lat[f] * 1000

    def summary(self) -> dict[str, float | int | str]:
        return {
            "benchmark": self.name,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "errors": self.errors,
            "duration_seconds": round(self.total_duration, 3),
            "qps": round(self.qps, 2),
            "min_ms": round(self.min_latency_ms, 2),
            "avg_ms": round(self.avg_latency_ms, 2),
            "p50_ms": round(self.percentile_ms(50), 2),
            "p95_ms": round(self.percentile_ms(95), 2),
            "p99_ms": round(self.percentile_ms(99), 2),
            "max_ms": round(self.max_latency_ms, 2),
        }

    def print_report(self) -> None:
        s = self.summary()
        logger.info("=" * 60)
        logger.info("BENCHMARK REPORT: %s", s["benchmark"])
        logger.info("=" * 60)
        logger.info("Total Requests:       %d", s["total_requests"])
        logger.info("Successful:           %d", s["successful_requests"])
        logger.info("Errors:               %d", s["errors"])
        logger.info("Total Duration:       %.2f s", s["duration_seconds"])
        logger.info("Throughput (QPS):     %.2f req/s", s["qps"])
        logger.info("Latency Min:          %.2f ms", s["min_ms"])
        logger.info("Latency Avg:          %.2f ms", s["avg_ms"])
        logger.info("Latency p50:          %.2f ms", s["p50_ms"])
        logger.info("Latency p95:          %.2f ms", s["p95_ms"])
        logger.info("Latency p99:          %.2f ms", s["p99_ms"])
        logger.info("Latency Max:          %.2f ms", s["max_ms"])
        logger.info("=" * 60)


async def run_concurrent_workload(
    name: str,
    task_func: Callable[[], Coroutine[None, None, None]],
    concurrency: int = 10,
    total_calls: int = 50,
) -> BenchmarkResult:
    """Execute a workload with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    latencies: List[float] = []
    errors = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal errors
        async with sem:
            t0 = time.perf_counter()
            try:
                await task_func()
                elapsed = time.perf_counter() - t0
                async with lock:
                    latencies.append(elapsed)
            except Exception as exc:
                async with lock:
                    errors += 1
                logger.debug("Task error during benchmark: %s", exc)

    start_time = time.perf_counter()
    tasks = [asyncio.create_task(worker()) for _ in range(total_calls)]
    await asyncio.gather(*tasks)
    total_duration = time.perf_counter() - start_time

    return BenchmarkResult(name, latencies, errors, total_duration)


async def benchmark_session_lock(concurrency: int = 20, iterations: int = 100) -> BenchmarkResult:
    """Benchmark session lock acquire/release under high contention."""
    from app.services.agent.distributed_lock import LocalAsyncioSessionLock

    lock_mgr = LocalAsyncioSessionLock()

    async def workload():
        async with lock_mgr.lock("principal_bench", "session_contention", timeout_seconds=5.0):
            await asyncio.sleep(0.001)

    return await run_concurrent_workload(
        "Session Lock High Contention",
        workload,
        concurrency=concurrency,
        total_calls=iterations,
    )


async def benchmark_chunked_upload(concurrency: int = 10, iterations: int = 50) -> BenchmarkResult:
    """Benchmark chunked upload ingestion and assembly."""
    from app.services.spatial_chunked_upload_service import SpatialChunkedUploadService
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        svc = SpatialChunkedUploadService(base_dir=Path(tmpdir))

        async def workload():
            meta = await svc.initiate_upload(
                filename="bench.geojson",
                total_size=1024,
                total_chunks=2,
            )
            await svc.upload_chunk(upload_id=meta.upload_id, chunk_index=0, chunk_bytes=b"a" * 512)
            await svc.upload_chunk(upload_id=meta.upload_id, chunk_index=1, chunk_bytes=b"b" * 512)
            await svc.complete_upload(meta.upload_id)

        return await run_concurrent_workload(
            "Chunked Spatial Upload",
            workload,
            concurrency=concurrency,
            total_calls=iterations,
        )


async def main():
    parser = argparse.ArgumentParser(description="GeoAI Concurrency Benchmark")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency level")
    parser.add_argument("--iterations", type=int, default=50, help="Total iterations")
    args = parser.parse_args()

    logger.info("Starting GeoAI Concurrency Benchmarks...")
    res_lock = await benchmark_session_lock(concurrency=args.concurrency, iterations=args.iterations)
    res_lock.print_report()

    res_upload = await benchmark_chunked_upload(concurrency=args.concurrency, iterations=args.iterations)
    res_upload.print_report()


if __name__ == "__main__":
    asyncio.run(main())

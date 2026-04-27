# Bulk Domain Traffic Checker

A quota-aware, asynchronous traffic logging library and CLI utility for high-volume domain analytics through the Similarweb RapidAPI endpoint.

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Build](https://img.shields.io/badge/Build-Passing-2ea44f?style=for-the-badge)](#)
[![Version](https://img.shields.io/badge/Version-1.0.0-informational?style=for-the-badge)](#)
[![Coverage](https://img.shields.io/badge/Coverage-Not%20Configured-lightgrey?style=for-the-badge)](#)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge)](LICENSE)

## 2. Table of Contents

- [Bulk Domain Traffic Checker](#bulk-domain-traffic-checker)
- [2. Table of Contents](#2-table-of-contents)
- [3. Features](#3-features)
- [4. Tech Stack \\& Architecture](#4-tech-stack--architecture)
  - [Core Stack](#core-stack)
  - [Project Structure](#project-structure)
  - [Key Design Decisions](#key-design-decisions)
- [5. Getting Started](#5-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [6. Testing](#6-testing)
- [7. Deployment](#7-deployment)
- [8. Usage](#8-usage)
- [9. Configuration](#9-configuration)
- [10. License](#10-license)
- [11. Contacts \\& Community Support](#11-contacts--community-support)

## 3. Features

- Fully asynchronous domain processing pipeline built on `asyncio` + `aiohttp` for efficient network I/O.
- URL canonicalization and normalization (`scheme`, `wwwN`, path, query, fragment, port stripping) before API calls.
- Multi-source domain ingestion from all files matching `domains*.txt`.
- Recursive payload parsing that can extract visit metrics from heterogeneous JSON structures.
- Startup cache reconciliation that preserves only successful numeric historical values.
- Idempotent rerun behavior: already successful domains are skipped automatically.
- Buffered persistence (`FLUSH_INTERVAL`) to mitigate data loss during long runs.
- Graceful shutdown handling for `SIGINT` and `SIGTERM` with final forced flush.
- Retry orchestration with progressive delay for transient API/network failures.
- Dedicated quota preflight call before workers start processing.
- Runtime quota signal propagation (`quota_exceeded_event`) to stop all workers safely.
- Progress visualization via `tqdm`, including live remaining request metadata.
- Straightforward function-level reuse (`clean_url`, `find_visits`) for embedding in custom pipelines.

> [!IMPORTANT]
> Default worker concurrency is intentionally conservative (`CONCURRENCY_LIMIT = 1`) to reduce quota burn and rate-limiting pressure.

## 4. Tech Stack & Architecture

### Core Stack

- Language: `Python 3.9+`
- Runtime model: `asyncio` event loop with cooperative multitasking
- HTTP transport: `aiohttp`
- CLI UX: `tqdm`
- Dependency management: `pip` + `requirements.txt`

### Project Structure

<details>
<summary>Repository file tree</summary>

```text
bulk-domain-traffic-checker/
├── similarwebchecker.py      # Core library + CLI entrypoint
├── requirements.txt          # Runtime dependencies
├── README.md                 # Project documentation
├── cmd_commands.txt          # Quick command helper
├── domain_traffic.txt        # Result cache/output file
├── api_key(test).txt         # Example key file
└── LICENSE                   # GPL-3.0 license
```

</details>

### Key Design Decisions

1. **Cache-first reruns**
   - Numeric records in `domain_traffic.txt` are treated as successful and skipped in future runs.
2. **Error row scrubbing before execution**
   - Non-numeric rows are removed so failed domains are retried automatically.
3. **Loose coupling to API schema**
   - `find_visits` recursively traverses nested dictionaries/lists and probes multiple potential traffic keys.
4. **Quota-aware lifecycle control**
   - A preflight quota check and runtime quota-exhaustion event prevent wasteful request storms.
5. **At-least-once write durability**
   - Periodic buffer flush plus final flush on teardown ensures durable progress.

<details>
<summary>Mermaid architecture and data flow</summary>

```mermaid
flowchart TD
    A[Load api_key.txt] --> B[Read domains*.txt]
    B --> C[Normalize and deduplicate domains]
    C --> D[Rewrite output to numeric rows only]
    D --> E[Load already successful domains]
    E --> F[Compute domains_to_check]
    F --> G[Quota preflight request]

    G -->|status 200| H[Spawn async workers]
    G -->|non-200| X[Abort run]

    H --> I[fetch_traffic(domain)]
    I --> J{HTTP status}
    J -->|200| K[Parse JSON and find visits]
    J -->|429 monthly exceeded| L[Set quota_exceeded_event]
    J -->|429 transient| M[Backoff and retry]
    J -->|401/403| N[Return key error]
    J -->|404| O[Return 0]
    J -->|other| P[Retry then return error]

    K --> Q[Append result to buffer]
    M --> I
    N --> Q
    O --> Q
    P --> Q

    Q --> R{flush_counter >= FLUSH_INTERVAL}
    R -->|yes| S[Append to domain_traffic.txt]
    R -->|no| T[Continue]
    S --> T

    L --> U[Stop workers globally]
    T --> U
    U --> V[Final flush and summary output]
```

</details>

## 5. Getting Started

### Prerequisites

- `Python 3.9` or newer.
- A valid RapidAPI subscription/key with access to `similarweb-insights` (`/traffic`) endpoint.
- Shell access for running the script (`bash`, `zsh`, PowerShell, etc.).

> [!WARNING]
> Runtime expects an `api_key.txt` file in the project root. If it is missing, execution exits immediately.

### Installation

1. Clone the repository:

```bash
git clone https://github.com/<your-org>/bulk-domain-traffic-checker.git
cd bulk-domain-traffic-checker
```

2. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
```

3. Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Add your API key:

```bash
printf "%s" "<YOUR_RAPIDAPI_KEY>" > api_key.txt
```

5. Add one or more input files (`domains*.txt`):

```bash
cat > domains1.txt <<'TXT'
google.com
https://www.github.com/
example.org/path?q=1
TXT
```

> [!TIP]
> Keep one domain/URL per line to maximize normalization accuracy and deterministic deduplication.

<details>
<summary>Troubleshooting and alternative setup paths</summary>

### Common installation issues

- **`ModuleNotFoundError: aiohttp`**: Ensure the active interpreter is from `.venv` and reinstall requirements.
- **`Permission denied` on activation**: On Windows, run PowerShell as admin or enable script execution policy.
- **Corporate TLS interception issues**: Configure `pip` trust settings or use an internal package mirror.

### Build-from-source style bootstrap

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install aiohttp tqdm
```

</details>

## 6. Testing

The repository currently does not include a formal test suite, but these checks are recommended:

```bash
python -m py_compile similarwebchecker.py
python -m pip check
python similarwebchecker.py
```

Recommended optional dev quality gates:

```bash
python -m pip install pytest ruff
pytest -q
ruff check .
```

> [!NOTE]
> `pytest` and `ruff` are not pinned in `requirements.txt`; install them in a dev environment only.

## 7. Deployment

Production deployment guidance:

1. Use immutable runtime images and inject secrets at runtime.
2. Mount a persistent volume for `domain_traffic.txt` to preserve cache state.
3. Run on a schedule aligned to API quota windows.
4. Pipe stdout/stderr to centralized log aggregation.

Example container image:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "similarwebchecker.py"]
```

Example run:

```bash
docker build -t bulk-domain-traffic-checker .
docker run --rm -v "$PWD:/app" bulk-domain-traffic-checker
```

> [!CAUTION]
> Never hardcode or bake real API keys into source code, container layers, CI logs, or shell history.

<details>
<summary>CI/CD integration recommendations</summary>

- Execute `py_compile` and static checks in pull request pipelines.
- Gate scheduled production jobs behind key-presence and quota-preflight checks.
- Export telemetry around success rate, quota remaining, and error classes.
- Treat `domain_traffic.txt` as operational state (artifact or persistent volume), not as source-controlled data.

</details>

## 8. Usage

Basic execution:

```bash
python similarwebchecker.py
```

Expected output behavior:

- Quota preflight diagnostics (remaining/limit/status).
- Domain cardinality summary (total/cached/pending).
- Progress bar updates while workers process domains.
- Incremental persistence to `domain_traffic.txt`.

Basic programmatic usage:

```python
from similarwebchecker import clean_url, find_visits

raw = "https://www2.Example.com/path?q=1#anchor"
normalized = clean_url(raw)
print(normalized)  # example.com

payload = {
    "meta": {"region": "global"},
    "engagement": {"monthly_visits": 987654},
}

visits = find_visits(payload)
print(visits)  # 987654
```

<details>
<summary>Advanced usage: custom worker orchestration and edge-case handling</summary>

### Advanced orchestration considerations

- Tune `CONCURRENCY_LIMIT` slowly and monitor 429 rates.
- Increase `WORKER_DELAY` under aggressive throttling.
- Adjust `FLUSH_INTERVAL` to trade off I/O overhead vs. crash-safety granularity.

### Custom formatter strategy

If integrating into another app, wrap return values (`int` or localized error string) into structured events:

```python
record = {
    "domain": domain,
    "traffic": traffic_value if isinstance(traffic_value, (int, float)) else None,
    "error": None if isinstance(traffic_value, (int, float)) else str(traffic_value),
    "source": "similarweb-rapidapi",
}
```

### Edge cases

- Empty lines or malformed URLs normalize to empty and are ignored.
- Domains with prior non-numeric results are retried on next run.
- Monthly quota exhaustion triggers global stop to avoid useless retries.

</details>

## 9. Configuration

Current configuration is code-driven through constants in `similarwebchecker.py`.

| Constant | Default | Description |
|---|---:|---|
| `OUTPUT_FILE` | `domain_traffic.txt` | Persistent result/cache file path. |
| `KEY_FILE` | `api_key.txt` | Path to file containing the RapidAPI key. |
| `CONCURRENCY_LIMIT` | `1` | Number of asynchronous workers. |
| `FLUSH_INTERVAL` | `20` | Number of buffered records before disk flush. |
| `MAX_RETRIES` | `3` | Per-domain retry attempts for transient failures. |
| `TIMEOUT_SECONDS` | `10` | HTTP request timeout in seconds. |
| `WORKER_DELAY` | `1` | Delay between worker iterations. |
| `API_HOST` | `similarweb-insights.p.rapidapi.com` | RapidAPI host header value. |
| `API_URL` | `https://similarweb-insights.p.rapidapi.com/traffic` | Traffic endpoint URL. |

Environment variables and startup flags are not natively implemented yet.

> [!NOTE]
> You can still externalize configuration by generating files (for example `api_key.txt`) at startup from environment variables.

<details>
<summary>Configuration deep dive: `.env` pattern and schema examples</summary>

### Suggested `.env` mapping (user-managed wrapper)

```dotenv
RAPIDAPI_KEY=your-key-here
TRAFFIC_OUTPUT_FILE=domain_traffic.txt
TRAFFIC_CONCURRENCY_LIMIT=1
TRAFFIC_FLUSH_INTERVAL=20
TRAFFIC_MAX_RETRIES=3
TRAFFIC_TIMEOUT_SECONDS=10
TRAFFIC_WORKER_DELAY=1
```

### Suggested JSON schema for wrapper-based runtime config

```json
{
  "output_file": "domain_traffic.txt",
  "key_file": "api_key.txt",
  "concurrency_limit": 1,
  "flush_interval": 20,
  "max_retries": 3,
  "timeout_seconds": 10,
  "worker_delay": 1,
  "endpoint": {
    "host": "similarweb-insights.p.rapidapi.com",
    "url": "https://similarweb-insights.p.rapidapi.com/traffic"
  }
}
```

### Suggested startup flags for a future wrapper CLI

```bash
python run_checker.py \
  --api-key-file api_key.txt \
  --input-glob 'domains*.txt' \
  --output-file domain_traffic.txt \
  --concurrency 1 \
  --flush-interval 20
```

</details>

## 10. License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for the full text.

## 11. Contacts & Community Support

## Support the Project

[![Patreon](https://img.shields.io/badge/Patreon-OstinFCT-f96854?style=flat-square&logo=patreon)](https://www.patreon.com/OstinFCT)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-fctostin-29abe0?style=flat-square&logo=ko-fi)](https://ko-fi.com/fctostin)
[![Boosty](https://img.shields.io/badge/Boosty-Support-f15f2c?style=flat-square)](https://boosty.to/ostinfct)
[![YouTube](https://img.shields.io/badge/YouTube-FCT--Ostin-red?style=flat-square&logo=youtube)](https://www.youtube.com/@FCT-Ostin)
[![Telegram](https://img.shields.io/badge/Telegram-FCTostin-2ca5e0?style=flat-square&logo=telegram)](https://t.me/FCTostin)

If you find this tool useful, consider leaving a star on GitHub or supporting the author directly.

import asyncio
import aiohttp
import sys
import os
import glob
import re
import signal
import logging
import warnings
from tqdm import tqdm

logging.getLogger('asyncio').setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

OUTPUT_FILE = 'domain_traffic.txt'
KEY_FILE = 'api_key.txt'
CONCURRENCY_LIMIT = 1
FLUSH_INTERVAL = 20
MAX_RETRIES = 3
TIMEOUT_SECONDS = 10
WORKER_DELAY = 1

API_HOST = "similarweb-insights.p.rapidapi.com"
API_URL = f"https://{API_HOST}/traffic"

HEADERS = {'Content-Type': 'application/json'}

shutdown_event = asyncio.Event()
quota_exceeded_event = asyncio.Event()

def clean_url(url):
    if not url:
        return ""
    url = str(url).strip().lower()
    url = re.sub(r'^[a-z0-9]+:\/\/', '', url)
    url = re.sub(r'^www\d*\.', '', url)
    url = url.split('/')[0]
    url = url.split('?')[0]
    url = url.split('#')[0]
    url = url.split(':')[0]
    return url.strip()

def find_visits(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in ['visits', 'total_visits', 'traffic', 'monthly_visits', 'engagements_visits']:
                return v
        for k, v in obj.items():
            res = find_visits(v)
            if res is not None:
                return res
    elif isinstance(obj, list):
        for item in obj:
            res = find_visits(item)
            if res is not None:
                return res
    return None

async def check_quota(session, api_key):
    headers = HEADERS.copy()
    headers["x-rapidapi-host"] = API_HOST
    headers["x-rapidapi-key"] = api_key
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(API_URL, headers=headers, params={"domain": "google.com"}, timeout=timeout) as response:
            remaining = response.headers.get('x-ratelimit-requests-remaining', 'Unknown')
            limit = response.headers.get('x-ratelimit-requests-limit', 'Unknown')
            body_preview = ""
            if response.status != 200:
                try:
                    body_preview = (await response.text())[:250]
                except Exception:
                    pass
            return remaining, limit, response.status, body_preview
    except Exception as e:
        return "Unknown", "Unknown", f"Err: {type(e).__name__}", str(e)

async def fetch_traffic(session, domain, api_key):
    querystring = {"domain": domain}
    headers = HEADERS.copy()
    headers["x-rapidapi-host"] = API_HOST
    headers["x-rapidapi-key"] = api_key

    last_error = "Ошибка сети"
    requests_left = "Unknown"

    for attempt in range(MAX_RETRIES):
        if shutdown_event.is_set() or quota_exceeded_event.is_set():
            return "Квота исчерпана" if quota_exceeded_event.is_set() else "Отменено", requests_left
        try:
            timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
            async with session.get(API_URL, headers=headers, params=querystring, timeout=timeout) as response:
                requests_left = response.headers.get('x-ratelimit-requests-remaining', requests_left)

                if response.status == 200:
                    data = await response.json()
                    traffic = find_visits(data)
                    return traffic if traffic is not None else 0, requests_left

                if response.status == 429:
                    try:
                        body = await response.text()
                    except Exception:
                        body = ""
                    body_lower = body.lower()
                    if "monthly" in body_lower or "exceeded" in body_lower or "upgrade" in body_lower:
                        quota_exceeded_event.set()
                        return "Месячная квота исчерпана", requests_left
                    await asyncio.sleep(2 ** (attempt + 1))
                    last_error = "Rate limit"
                    continue

                if response.status in (401, 403):
                    return "Ошибка ключа", requests_left

                if response.status == 404:
                    return 0, requests_left

                last_error = f"Ошибка {response.status}"
                await asyncio.sleep(1)

        except asyncio.TimeoutError:
            last_error = "Таймаут"
            await asyncio.sleep(1 * (attempt + 1))
            continue
        except aiohttp.ClientError as e:
            last_error = f"Сеть: {type(e).__name__}"
            await asyncio.sleep(1)
            continue
        except Exception as e:
            last_error = f"Err: {type(e).__name__}"
            await asyncio.sleep(1)
            continue

    return last_error, requests_left

def load_existing_results(filepath):
    """
    Загружает только УСПЕШНЫЕ результаты (где трафик — число).
    Строки с ошибками игнорируются, домены будут перепроверены.
    """
    existing = set()
    if not os.path.exists(filepath):
        return existing
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            domain, value = parts[0], parts[1]
            try:
                int(float(value))
                existing.add(domain)
            except ValueError:
                continue
    return existing

def rewrite_output_without_errors(filepath):
    """
    Очищает файл от строк с ошибками, оставляет только числовые результаты.
    """
    if not os.path.exists(filepath):
        return
    good_lines = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line_strip = line.strip()
            if not line_strip:
                continue
            parts = line_strip.split()
            if len(parts) < 2:
                continue
            try:
                int(float(parts[1]))
                good_lines.append(f"{parts[0]} {parts[1]}\n")
            except ValueError:
                continue
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(good_lines)

def flush_buffer(buffer):
    if not buffer:
        return
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        for domain, traffic in buffer:
            f.write(f"{domain} {traffic}\n")
    buffer.clear()

async def worker(queue, session, api_key, results_lock, pbar, buffer, flush_counter):
    while not shutdown_event.is_set() and not quota_exceeded_event.is_set():
        try:
            domain = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        traffic, req_left = await fetch_traffic(session, domain, api_key)

        async with results_lock:
            buffer.append((domain, str(traffic)))
            flush_counter[0] += 1
            if flush_counter[0] >= FLUSH_INTERVAL:
                flush_buffer(buffer)
                flush_counter[0] = 0

        pbar.set_postfix({"осталось": req_left})
        pbar.update(1)
        queue.task_done()

        if quota_exceeded_event.is_set():
            return

        await asyncio.sleep(WORKER_DELAY)

async def main():
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda loop, context: None)

    def _signal_handler():
        if not shutdown_event.is_set():
            print("\n\nЗавершение работы. Сохраняю остатки...")
            shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            signal.signal(sig, lambda s, f: _signal_handler())

    if not os.path.exists(KEY_FILE):
        print(f"Ошибка: Файл {KEY_FILE} не найден.")
        return
    with open(KEY_FILE, 'r', encoding='utf-8') as f:
        api_key = f.read().strip()

    input_files = glob.glob('domains*.txt')
    if not input_files:
        print("Ошибка: Не найдены файлы domains*.txt")
        return

    all_domains = set()
    for file in input_files:
        with open(file, 'r', encoding='utf-8') as f:
            for line in f:
                d = clean_url(line)
                if d:
                    all_domains.add(d)

    rewrite_output_without_errors(OUTPUT_FILE)
    existing_domains = load_existing_results(OUTPUT_FILE)
    domains_to_check = list(all_domains - existing_domains)

    connector = aiohttp.TCPConnector(limit=CONCURRENCY_LIMIT * 2, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        print("Проверяю квоту API...")
        remaining, limit, status, body = await check_quota(session, api_key)
        print(f"API:             {API_URL}")
        print(f"Квота:           {remaining} / {limit} (статус: {status})")
        if status != 200 and body:
            print(f"Ответ сервера:   {body}")
        print(f"Всего доменов:   {len(all_domains)}")
        print(f"Уже в кэше:      {len(existing_domains)}")
        print(f"Будет проверено: {len(domains_to_check)}\n")

        if status != 200:
            print("⚠ Проверь тариф/ключ — API вернул ошибку. Запуск отменён.")
            return

        if not domains_to_check:
            return

        queue = asyncio.Queue()
        for domain in domains_to_check:
            queue.put_nowait(domain)

        results_lock = asyncio.Lock()
        buffer = []
        flush_counter = [0]

        try:
            with tqdm(total=len(domains_to_check), desc="Трафик", unit="dom") as pbar:
                workers = [
                    asyncio.create_task(
                        worker(queue, session, api_key, results_lock, pbar, buffer, flush_counter)
                    )
                    for _ in range(CONCURRENCY_LIMIT)
                ]
                await asyncio.gather(*workers, return_exceptions=True)

                if quota_exceeded_event.is_set():
                    print("\n⚠ Месячная квота RapidAPI исчерпана. Остановлено.")
        finally:
            flush_buffer(buffer)
            print(f"\nГотово. Результаты в {OUTPUT_FILE}")

if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
#!/usr/bin/env python3
"""
log_processor.py - потоковая обработка access.log

Работает как крон-джоба (каждые 5 минут):
1. Читает только НОВЫЕ строки из access.log
2. Обновляет servers.json инкрементально
3. Сохраняет позицию в .log_state.json

При логротации автоматически переходит на новый лог.

Использование:
    python3 scripts/log_processor.py
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs
from metrics import compute_availability_stats

# Пути (относительные от текущей директории)
# В контейнере логи в /var/log/nginx, локально в ./logs
LOG_DIR = '/var/log/nginx' if os.path.exists('/var/log/nginx') else './logs'
ACCESS_LOG = os.path.join(LOG_DIR, 'access.log')
STATE_FILE = '.log_state.json'
OUTPUT_JSON = './nginx/html/api/servers.json' if not os.path.exists('/var/log/nginx') else '/usr/share/nginx/html/api/servers.json'

# Конфиги
MAX_TIMELINE_POINTS = 30  # Максимум точек в timeline
MAX_HISTORY_DAYS = 7      # Максимум дней истории

# Для отладки
DEBUG = os.environ.get('DEBUG', '0') == '1'


def log_msg(level, msg):
    """Логировать с таймстэмпом"""
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] [{level}] {msg}", flush=True)


def read_state():
    """Прочитать сохранённое состояние обработки"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
                if DEBUG:
                    log_msg("DEBUG", f"Loaded state: {state}")
                return state
        except Exception as e:
            log_msg("WARN", f"Failed to load state: {e}")
    
    initial_state = {
        'current_log': 'access.log',
        'position': 0,
        'last_update': None,
        'processed_lines': 0,
        'processed_metrics': 0
    }
    
    if DEBUG:
        log_msg("DEBUG", f"Created new state: {initial_state}")
    
    return initial_state


def save_state(state):
    """Сохранить состояние обработки"""
    state['last_update'] = datetime.now(timezone.utc).isoformat()
    
    try:
        # Атомарная запись (write to temp, then rename)
        temp_file = STATE_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(temp_file, STATE_FILE)
        
        if DEBUG:
            log_msg("DEBUG", f"Saved state: {state}")
    except Exception as e:
        log_msg("ERROR", f"Failed to save state: {e}")


def read_new_lines():
    """Прочитать только новые строки из логов"""
    state = read_state()
    log_path = os.path.join(LOG_DIR, state['current_log'])
    
    if not os.path.exists(log_path):
        log_msg("WARN", f"Log file not found: {log_path}")
        return [], state
    
    current_size = os.path.getsize(log_path)
    
    # Проверка логротации (размер уменьшился = новый лог создан)
    if current_size < state['position']:
        log_msg("INFO", f"Log rotation detected: {current_size} < {state['position']}")
        state['current_log'] = 'access.log'
        state['position'] = 0
        log_path = os.path.join(LOG_DIR, state['current_log'])
    
    # Читаем с последней сохранённой позиции
    new_lines = []
    try:
        with open(log_path, 'rb') as f:
            file_size = f.seek(0, 2)  # Seek to end
            
            if file_size == state['position']:
                # Нет новых данных
                return [], state
            
            f.seek(state['position'])
            content = f.read()
            
            if content:
                new_lines = content.decode('utf-8', errors='ignore').strip().split('\n')
                state['position'] = f.tell()
                
                if DEBUG:
                    log_msg("DEBUG", f"Read {len(new_lines)} new lines, position now: {state['position']}")
    except Exception as e:
        log_msg("ERROR", f"Failed to read log: {e}")
        return [], state
    
    return new_lines, state


def parse_log_lines(lines):
    """Распарсить строки access.log и вернуть метрики"""
    # Паттерн: IP - - [дата] "GET /api/logs?query HTTP/1.1" статус
    pattern = re.compile(
        r'(\d+\.\d+\.\d+\.\d+) - - \[(.+?)\] '
        r'"GET /api/logs\?(.+?) HTTP/1.1" (\d+)'
    )
    
    # Маппинг уровня логирования на доступность (availability)
    level_map = {
        'DEBUG': 1.0,
        'INFO': 1.0,
        'NOTICE': 1.0,
        'WARNING': 0.6,
        'ERROR': 0.2,
        'CRIT': 0.0,
        'ALERT': 0.0,
    }
    
    metrics = []  # Список метрик: [{service_id, ts, availability}, ...]
    skipped = 0
    
    for line in lines:
        if not line.strip():
            continue
        
        match = pattern.search(line)
        if not match:
            skipped += 1
            continue
        
        ip, raw_ts, raw_query, status = match.groups()
        
        # Пропускаем не-200 ответы
        if status != '200':
            skipped += 1
            continue
        
        # Распарсить query параметры
        try:
            params = parse_qs(raw_query, keep_blank_values=True)
        except:
            skipped += 1
            continue
        
        # Извлечь service_id
        service_id = (params.get('id') or ['unknown'])[0]
        
        if service_id == 'unknown':
            skipped += 1
            continue
        
        # Извлечь уровень логирования
        level = (params.get('level') or ['INFO'])[0].upper()
        
        # Определить timestamp (приоритет: evt_ts > raw_ts)
        ts_iso = None
        evt_ts_param = (params.get('evt_ts') or [None])[0]
        
        if evt_ts_param:
            try:
                ts_obj = datetime.fromisoformat(evt_ts_param)
                if ts_obj.tzinfo is None:
                    ts_iso = ts_obj.isoformat()
                else:
                    ts_iso = ts_obj.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
            except:
                pass
        
        if not ts_iso:
            try:
                # Формат: 24/Dec/2025:15:52:10 +0000
                ts = datetime.strptime(raw_ts, '%d/%b/%Y:%H:%M:%S %z')
                ts_iso = ts.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
            except:
                try:
                    # Fallback: без тайм-зоны
                    ts = datetime.strptime(raw_ts.split()[0], '%d/%b/%Y:%H:%M:%S')
                    ts_iso = ts.isoformat()
                except:
                    ts_iso = datetime.utcnow().isoformat()
        
        # Получить availability из уровня логирования
        availability = level_map.get(level, 1.0)
        
        metrics.append({
            'service_id': service_id,
            'ts': ts_iso,
            'availability': availability,
            'level': level
        })
    
    if DEBUG and skipped > 0:
        log_msg("DEBUG", f"Skipped {skipped} lines during parsing")
    
    return metrics


def load_servers_json():
    """Загрузить текущий servers.json"""
    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON) as f:
                data = json.load(f)
                if DEBUG:
                    services = data.get('services', [])
                    services_count = len(services) if isinstance(services, list) else len(services)
                    log_msg("DEBUG", f"Loaded servers.json with {services_count} services")
                return data
        except Exception as e:
            log_msg("WARN", f"Failed to load servers.json: {e}")
    
    return {'services': []}


def save_servers_json(data):
    """Сохранить servers.json атомарно"""
    temp_file = OUTPUT_JSON + '.tmp'
    try:
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, OUTPUT_JSON)
        
        if DEBUG:
            log_msg("DEBUG", "Saved servers.json")
    except Exception as e:
        log_msg("ERROR", f"Failed to save servers.json: {e}")
        raise


def compute_stats(timeline):
    """Вычислить статистику по timeline"""
    if not timeline:
        return {
            'current_status': 'ok',
            'uptime_24h': 1.0,
            'prediction': 1.0,
            'ewma_prediction': 1.0,
            'availability_ci_low': 1.0,
            'availability_ci_high': 1.0,
            'volatility': 0.0,
            'incident_rate': 0.0,
            'anomaly_score': 0.0,
            'risk_score': 0.0,
            'risk': 'LOW',
        }

    values = [p['availability'] for p in timeline]
    stats = compute_availability_stats(values)
    
    if DEBUG:
        log_msg(
            "DEBUG",
            f"Computed stats: avg={stats['uptime_24h']:.3f}, "
            f"sma={stats['prediction']:.3f}, ewma={stats['ewma_prediction']:.3f}, "
            f"risk_score={stats['risk_score']:.3f}, risk={stats['risk']}"
        )
    
    return stats


def cleanup_old_logs(max_days=MAX_HISTORY_DAYS):
    """Удалить логи старше MAX_HISTORY_DAYS дней"""
    try:
        cutoff_time = datetime.now() - timedelta(days=max_days)
        deleted_count = 0
        
        for filename in os.listdir(LOG_DIR):
            if not filename.startswith('access.log'):
                continue
            
            file_path = os.path.join(LOG_DIR, filename)
            
            # Не трогаем текущий access.log
            if filename == 'access.log':
                continue
            
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            
            if file_mtime < cutoff_time:
                try:
                    os.remove(file_path)
                    log_msg("INFO", f"Deleted old log: {filename}")
                    deleted_count += 1
                except Exception as e:
                    log_msg("WARN", f"Failed to delete {filename}: {e}")
        
        if deleted_count > 0:
            log_msg("INFO", f"Cleaned up {deleted_count} old log files")
        
    except Exception as e:
        log_msg("ERROR", f"Cleanup failed: {e}")


def update_servers_json(metrics):
    """Обновить servers.json инкрементально (добавить новые метрики)"""
    if not metrics:
        return 0
    
    data = load_servers_json()
    now = datetime.now(timezone.utc)
    cutoff_time = (now - timedelta(days=MAX_HISTORY_DAYS)).isoformat()
    
    # Убедимся что services это список
    if not isinstance(data['services'], list):
        data['services'] = []
    
    # Создать словарь для быстрого поиска по id
    services_dict = {svc['id']: svc for svc in data['services']}
    
    updated_services = set()
    
    for metric in metrics:
        service_id = metric['service_id']
        updated_services.add(service_id)
        
        # Создать новый сервис если его ещё нет
        if service_id not in services_dict:
            services_dict[service_id] = {
                'id': service_id,
                'name': service_id,
                'description': f'Service {service_id}',
                'current_status': 'ok',
                'uptime_24h': 1.0,
                'timeline': []
            }
            log_msg("INFO", f"Created new service: {service_id}")
        
        # Проверка на дубликаты - не добавлять точку если уже есть с таким timestamp (без миллисекунд)
        existing_timestamps = {p['ts'][:16] for p in services_dict[service_id]['timeline']}
        if metric['ts'][:16] not in existing_timestamps:
            # Добавить новую точку в timeline
            services_dict[service_id]['timeline'].append({
                'ts': metric['ts'],
                'availability': metric['availability']
            })
        
        # Удалить точки старше MAX_HISTORY_DAYS
        timeline = services_dict[service_id]['timeline']
        timeline = [p for p in timeline if p['ts'] > cutoff_time]
        services_dict[service_id]['timeline'] = timeline
        
        # Оставить только последние MAX_TIMELINE_POINTS
        if len(timeline) > MAX_TIMELINE_POINTS:
            timeline = timeline[-MAX_TIMELINE_POINTS:]
            services_dict[service_id]['timeline'] = timeline
        
        # Пересчитать статистику
        stats = compute_stats(timeline)
        services_dict[service_id].update(stats)
    
    # Конвертировать обратно в список
    data['services'] = list(services_dict.values())
    
    # Сохранить обновлённый JSON
    save_servers_json(data)
    
    return len(updated_services)


def main():
    """Основной процесс обработки"""
    log_msg("START", "=" * 60)
    
    try:
        # Убедиться, что директории существуют
        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
        
        # Удалить старые логи (>7 дней)
        cleanup_old_logs()
        
        # Прочитать новые строки из логов
        new_lines, state = read_new_lines()
        
        if not new_lines or (len(new_lines) == 1 and not new_lines[0]):
            log_msg("INFO", "No new lines in log")
            save_state(state)
            log_msg("END", "=" * 60)
            return 0
        
        log_msg("INFO", f"Read {len(new_lines)} new lines from {state['current_log']}")
        
        # Распарсить метрики из логов
        metrics = parse_log_lines(new_lines)
        
        if not metrics:
            log_msg("INFO", "No metrics parsed from lines")
            save_state(state)
            log_msg("END", "=" * 60)
            return 0
        
        log_msg("INFO", f"Parsed {len(metrics)} metrics")
        
        # Обновить servers.json
        updated_services_count = update_servers_json(metrics)
        log_msg("INFO", f"Updated {updated_services_count} services in servers.json")
        
        # Обновить состояние
        state['processed_lines'] = state.get('processed_lines', 0) + len(new_lines)
        state['processed_metrics'] = state.get('processed_metrics', 0) + len(metrics)
        save_state(state)
        
        log_msg("SUCCESS", f"Processed {len(metrics)} metrics successfully")
        log_msg("END", "=" * 60)
        
        return 0
    
    except Exception as e:
        log_msg("CRITICAL", f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        log_msg("END", "=" * 60)
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)

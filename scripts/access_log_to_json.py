import re
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, unquote_plus

ACCESS_LOG_FILE = './logs/access.log'
OUTPUT_JSON_FILE = './nginx/html/api/servers.json'


def compute_prediction(timeline, n=5):
    """
    Вычисляет прогноз доступности на основе скользящего среднего.
    Берет последние N точек и считает среднее.
    """
    if not timeline:
        return 1.0
    
    # Берем последние N точек
    recent_points = timeline[-n:] if len(timeline) >= n else timeline
    
    # Считаем среднее availability
    avg = sum(p['availability'] for p in recent_points) / len(recent_points)
    return round(avg, 3)


def compute_risk(prediction):
    """
    Оценивает риск на основе прогноза.
    """
    if prediction >= 0.8:
        return 'LOW'
    elif prediction >= 0.5:
        return 'MEDIUM'
    else:
        return 'HIGH'


def parse_access_log(max_points=30):
    pattern = re.compile(r'(\d+\.\d+\.\d+\.\d+) - - \[(.+?)\] "GET /api/logs\?(.+?) HTTP/1.1" (\d+)')
    services = {}

    # более детальная шкала доступности по уровням
    level_map = {
        'DEBUG': 1.0,
        'INFO': 1.0,
        'NOTICE': 1.0,
        'WARNING': 0.6,
        'ERROR': 0.2,
        'CRIT': 0.0,
        'ALERT': 0.0,
    }

    with open(ACCESS_LOG_FILE, 'r') as file:
        for line in file:
            match = pattern.search(line)
            if not match:
                continue
            ip, raw_ts, raw_query, status = match.groups()
            if status != '200':
                continue

            # try to prefer event timestamp passed in query (evt_ts)
            params = parse_qs(raw_query, keep_blank_values=True)
            evt_ts_param = (params.get('evt_ts') or [None])[0]
            ts_iso = None
            if evt_ts_param:
                try:
                    # expect ISO-like: YYYY-MM-DDTHH:MM:SS[.mmm]
                    ts_obj = datetime.fromisoformat(evt_ts_param)
                    if ts_obj.tzinfo is None:
                        ts_iso = ts_obj.isoformat()
                    else:
                        ts_iso = ts_obj.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
                except Exception:
                    ts_iso = None

            if not ts_iso:
                # raw_ts looks like: 24/Dec/2025:15:52:10 +0000
                try:
                    ts = datetime.strptime(raw_ts, '%d/%b/%Y:%H:%M:%S %z')
                    # convert to ISO without microseconds
                    ts_iso = ts.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
                except Exception:
                    # fallback: try without tz
                    try:
                        ts = datetime.strptime(raw_ts.split()[0], '%d/%b/%Y:%H:%M:%S')
                        ts_iso = ts.isoformat()
                    except Exception:
                        ts_iso = datetime.utcnow().isoformat()

            # корректно распарсить query с URL-кодировкой
            # (params already read earlier to check evt_ts; reuse)
            # values in params are lists
            service_id = (params.get('id') or ['unknown'])[0]

            # skip events that don't carry an explicit id to avoid 'unknown' blobs
            if not service_id or service_id == 'unknown':
                continue
            level = (params.get('level') or ['INFO'])[0].upper()

            # if explicit availability provided in params, honor it
            if 'availability' in params and params.get('availability'):
                try:
                    availability = float(params.get('availability')[0])
                    availability = max(0.0, min(1.0, availability))
                except Exception:
                    availability = level_map.get(level, 1.0)
            else:
                availability = level_map.get(level, 1.0)

            if service_id not in services:
                services[service_id] = {
                    'id': service_id,
                    'name': service_id,
                    'description': f'Service {service_id}',
                    'current_status': 'ok',
                    'uptime_24h': 0.0,
                    'timeline': []
                }

            services[service_id]['timeline'].append({
                'ts': ts_iso,
                'availability': availability,
                'level': level
            })

    # postprocess: sort timeline, trim, compute uptime and current_status
    result_services = []
    for svc in services.values():
        timeline = sorted(svc['timeline'], key=lambda p: p['ts'])
        # skip services without any timeline points
        if not timeline:
            continue
        # keep last N points
        if len(timeline) > max_points:
            timeline = timeline[-max_points:]
        # remove 'level' field from output timeline (keep only ts and availability)
        out_timeline = [{'ts': p['ts'], 'availability': p['availability']} for p in timeline]

        # uptime = average availability
        if out_timeline:
            avg = sum(p['availability'] for p in out_timeline) / len(out_timeline)
        else:
            avg = 1.0

        if avg > 0.9:
            status = 'ok'
        elif avg > 0.5:
            status = 'degraded'
        else:
            status = 'down'

        # Вычисляем прогноз и риск
        prediction = compute_prediction(out_timeline)
        risk = compute_risk(prediction)
        
        svc['timeline'] = out_timeline
        svc['uptime_24h'] = round(avg, 3)
        svc['current_status'] = status
        svc['prediction'] = prediction
        svc['risk'] = risk
        result_services.append(svc)

    return {'generated_at': datetime.utcnow().isoformat(), 'services': result_services}


def write_to_json(data):
    with open(OUTPUT_JSON_FILE, 'w') as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    data = parse_access_log()
    write_to_json(data)
    print(f"Generated {OUTPUT_JSON_FILE}")
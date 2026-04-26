import json
from datetime import datetime
from collections import defaultdict, Counter
import matplotlib.pyplot as plt
import os

SERVERS_JSON = './nginx/html/api/servers.json'
REPORTS_DIR = './reports'
os.makedirs(REPORTS_DIR, exist_ok=True)

def load_data():
    with open(SERVERS_JSON, 'r') as f:
        return json.load(f)

def service_stats(data):
    stats = []
    for svc in data.get('services', []):
        timeline = svc.get('timeline', [])
        total = len(timeline)
        down = sum(1 for p in timeline if p.get('availability', 1.0) == 0.0)
        degraded = sum(1 for p in timeline if 0.0 < p.get('availability', 1.0) < 1.0)
        ok = sum(1 for p in timeline if p.get('availability', 1.0) == 1.0)
        stats.append({
            'id': svc['id'],
            'name': svc.get('name', svc['id']),
            'total': total,
            'ok': ok,
            'degraded': degraded,
            'down': down,
            'uptime_24h': svc.get('uptime_24h', 0.0)
        })
    return stats

def plot_availability(data):
    from datetime import datetime
    for svc in data.get('services', []):
        timeline = svc.get('timeline', [])
        if not timeline:
            continue
        times = []
        for p in timeline:
            ts = p.get('ts')
            try:
                dt = datetime.fromisoformat(ts)
                times.append(dt.strftime('%H:%M'))
            except Exception:
                times.append(ts)
        values = [p.get('availability', 1.0)*100 for p in timeline]
        plt.figure(figsize=(8,3))
        plt.plot(times, values, marker='o', label=svc['id'])
        plt.title(f"Динамика доступности: {svc['id']}")
        plt.xlabel('Время (часы:минуты)')
        plt.ylabel('Доступность, %')
        plt.ylim(0, 100)
        plt.grid(True)
        plt.tight_layout()
        fname = os.path.join(REPORTS_DIR, f"availability_{svc['id']}.png")
        plt.savefig(fname)
        plt.close()

def generate_text_report(stats):
    lines = [f"Отчет сгенерирован: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    lines.append("id;name;ok;degraded;down;total;uptime_24h")
    for s in stats:
        lines.append(f"{s['id']};{s['name']};{s['ok']};{s['degraded']};{s['down']};{s['total']};{s['uptime_24h']:.3f}")
    report_path = os.path.join(REPORTS_DIR, 'summary.csv')
    with open(report_path, 'w') as f:
        f.write('\n'.join(lines))
    return report_path

def plot_top_problematic(stats):
    # Топ-5 по количеству down+degraded
    stats_sorted = sorted(stats, key=lambda s: s['down']+s['degraded'], reverse=True)
    top = stats_sorted[:5]
    labels = [s['id'] for s in top]
    values = [s['down']+s['degraded'] for s in top]
    plt.figure(figsize=(7,4))
    plt.bar(labels, values, color='red')
    plt.title('Топ-5 проблемных сервисов (down+degraded)')
    plt.ylabel('Инциденты')
    plt.tight_layout()
    fname = os.path.join(REPORTS_DIR, 'top_problematic.png')
    plt.savefig(fname)
    plt.close()

def main():
    data = load_data()
    stats = service_stats(data)
    print('Генерация графиков доступности...')
    plot_availability(data)
    print('Генерация отчета summary.csv...')
    report_path = generate_text_report(stats)
    print(f'Генерация топ-5 проблемных сервисов...')
    plot_top_problematic(stats)
    print(f'Все отчеты и графики сохранены в {REPORTS_DIR}/')
    print(f'Табличный отчет: {report_path}')

if __name__ == '__main__':
    main()

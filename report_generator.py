import os
import sys
import json
from datetime import datetime

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:
    plt = None

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from metrics import compute_availability_stats

SERVERS_JSON = './nginx/html/api/servers.json'
REPORTS_DIR = './reports'
os.makedirs(REPORTS_DIR, exist_ok=True)


def svg_polyline(points, width, height, y_min=0.0, y_max=100.0):
    if len(points) == 1:
        points = [(0, points[0][1]), (1, points[0][1])]
    x_min = min(x for x, _ in points)
    x_max = max(x for x, _ in points)
    coords = []
    for x, y in points:
        sx = 50 + (x - x_min) / (x_max - x_min) * (width - 80)
        sy = 35 + (y_max - y) / (y_max - y_min) * (height - 80)
        coords.append(f'{sx:.1f},{sy:.1f}')
    return ' '.join(coords)


def write_line_svg(path, title, labels, values):
    width, height = 800, 320
    points = list(enumerate(values))
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="50" y="24" font-family="Arial" font-size="17" font-weight="700">{title}</text>',
        '<line x1="50" y1="270" x2="770" y2="270" stroke="#94a3b8"/>',
        '<line x1="50" y1="35" x2="50" y2="270" stroke="#94a3b8"/>',
        f'<polyline points="{svg_polyline(points, width, height)}" fill="none" stroke="#2563eb" stroke-width="3"/>',
        '<text x="55" y="294" font-family="Arial" font-size="12">время наблюдения</text>',
        '<text x="10" y="155" font-family="Arial" font-size="12" transform="rotate(-90 10 155)">доступность, %</text>',
    ]
    if labels:
        lines.append(f'<text x="55" y="288" font-family="Arial" font-size="10">{labels[0]}</text>')
        lines.append(f'<text x="700" y="288" font-family="Arial" font-size="10">{labels[-1]}</text>')
    lines.append('</svg>')
    with open(path, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))


def write_bar_svg(path, title, labels, values, colors=None):
    width, height = 800, 320
    max_value = max(values or [1])
    colors = colors or ['#ef4444'] * len(values)
    bar_gap = 18
    bar_width = max(24, int((width - 100 - bar_gap * len(values)) / max(1, len(values))))
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="50" y="24" font-family="Arial" font-size="17" font-weight="700">{title}</text>',
        '<line x1="50" y1="270" x2="770" y2="270" stroke="#94a3b8"/>',
        '<line x1="50" y1="35" x2="50" y2="270" stroke="#94a3b8"/>',
    ]
    for idx, (label, value) in enumerate(zip(labels, values)):
        x = 70 + idx * (bar_width + bar_gap)
        h = 0 if max_value == 0 else value / max_value * 220
        color = colors[idx % len(colors)]
        lines.append(f'<rect x="{x}" y="{270 - h:.1f}" width="{bar_width}" height="{h:.1f}" fill="{color}"/>')
        lines.append(f'<text x="{x}" y="{270 - h - 6:.1f}" font-family="Arial" font-size="11">{value}</text>')
        lines.append(f'<text x="{x}" y="292" font-family="Arial" font-size="10">{label}</text>')
    lines.append('</svg>')
    with open(path, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))

def load_data():
    with open(SERVERS_JSON, 'r') as f:
        return json.load(f)

def service_stats(data):
    stats = []
    for svc in data.get('services', []):
        timeline = svc.get('timeline', [])
        values = [p.get('availability', 1.0) for p in timeline]
        computed = compute_availability_stats(values)
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
            'uptime_24h': svc.get('uptime_24h', computed['uptime_24h']),
            'prediction': svc.get('prediction', computed['prediction']),
            'ewma_prediction': svc.get('ewma_prediction', computed['ewma_prediction']),
            'volatility': svc.get('volatility', computed['volatility']),
            'incident_rate': svc.get('incident_rate', computed['incident_rate']),
            'risk_score': svc.get('risk_score', computed['risk_score']),
            'risk': svc.get('risk', computed['risk']),
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
        if plt is None:
            fname = os.path.join(REPORTS_DIR, f"availability_{svc['id']}.svg")
            write_line_svg(fname, f"Динамика доступности: {svc['id']}", times, values)
            continue
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
    lines = [f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    lines.append("id;name;ok;degraded;down;total;uptime_24h;prediction;ewma_prediction;volatility;incident_rate;risk_score;risk")
    for s in stats:
        lines.append(
            f"{s['id']};{s['name']};{s['ok']};{s['degraded']};{s['down']};{s['total']};"
            f"{s['uptime_24h']:.3f};{s['prediction']:.3f};{s['ewma_prediction']:.3f};"
            f"{s['volatility']:.3f};{s['incident_rate']:.3f};{s['risk_score']:.3f};{s['risk']}"
        )
    report_path = os.path.join(REPORTS_DIR, 'summary.csv')
    with open(report_path, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))
    return report_path

def plot_top_problematic(stats):
    # Топ-5 по количеству down+degraded
    stats_sorted = sorted(stats, key=lambda s: s['down']+s['degraded'], reverse=True)
    top = stats_sorted[:5]
    labels = [s['id'] for s in top]
    values = [s['down']+s['degraded'] for s in top]
    if plt is None:
        fname = os.path.join(REPORTS_DIR, 'top_problematic.svg')
        write_bar_svg(fname, 'Топ-5 проблемных сервисов (down+degraded)', labels, values)
        return
    plt.figure(figsize=(7,4))
    plt.bar(labels, values, color='red')
    plt.title('Топ-5 проблемных сервисов (down+degraded)')
    plt.ylabel('Инциденты')
    plt.tight_layout()
    fname = os.path.join(REPORTS_DIR, 'top_problematic.png')
    plt.savefig(fname)
    plt.close()

def plot_risk_distribution(stats):
    risks = ['LOW', 'MEDIUM', 'HIGH']
    values = [sum(1 for s in stats if s.get('risk') == risk) for risk in risks]
    colors = ['#22c55e', '#f59e0b', '#ef4444']
    if plt is None:
        fname = os.path.join(REPORTS_DIR, 'risk_distribution.svg')
        write_bar_svg(fname, 'Распределение сервисов по уровню риска', risks, values, colors)
        return
    plt.figure(figsize=(6,4))
    plt.bar(risks, values, color=colors)
    plt.title('Распределение сервисов по уровню риска')
    plt.ylabel('Количество сервисов')
    plt.tight_layout()
    fname = os.path.join(REPORTS_DIR, 'risk_distribution.png')
    plt.savefig(fname)
    plt.close()

def generate_recommendations(stats):
    lines = [f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    lines.append("id;risk;risk_score;recommendation")
    for s in sorted(stats, key=lambda item: item['risk_score'], reverse=True):
        if s['risk'] == 'HIGH':
            recommendation = 'Проверить SIP-транк, сетевую доступность и последние ERROR/CRIT события'
        elif s['risk'] == 'MEDIUM':
            recommendation = 'Усилить наблюдение и проверить рост WARNING/ERROR событий'
        else:
            recommendation = 'Плановый мониторинг без срочных действий'
        lines.append(f"{s['id']};{s['risk']};{s['risk_score']:.3f};{recommendation}")
    report_path = os.path.join(REPORTS_DIR, 'recommendations.csv')
    with open(report_path, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))
    return report_path

def main():
    data = load_data()
    stats = service_stats(data)
    print('Генерация графиков доступности...')
    plot_availability(data)
    print('Генерация отчета summary.csv...')
    report_path = generate_text_report(stats)
    print(f'Генерация топ-5 проблемных сервисов...')
    plot_top_problematic(stats)
    print('Генерация распределения рисков...')
    plot_risk_distribution(stats)
    recommendations_path = generate_recommendations(stats)
    print(f'Все отчеты и графики сохранены в {REPORTS_DIR}/')
    print(f'Табличный отчет: {report_path}')
    print(f'Рекомендации: {recommendations_path}')

if __name__ == '__main__':
    main()

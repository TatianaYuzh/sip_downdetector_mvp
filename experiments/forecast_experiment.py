#!/usr/bin/env python3
"""Numerical experiments for availability forecasting methods."""

import csv
import math
import os
import random
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(ROOT_DIR, 'scripts')
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from metrics import ewma_forecast, moving_average, risk_score, classify_risk


OUT_DIR = os.path.join(ROOT_DIR, 'reports', 'experiments')
WINDOW = 5
ALPHA = 0.35
RANDOM_SEED = 42


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def build_scenarios(length=60):
    random.seed(RANDOM_SEED)

    stable = [clamp(0.96 + random.gauss(0, 0.025)) for _ in range(length)]

    degradation = []
    for idx in range(length):
        trend = 0.98 - idx * 0.010
        degradation.append(clamp(trend + random.gauss(0, 0.025)))

    burst_failure = [clamp(0.95 + random.gauss(0, 0.02)) for _ in range(length)]
    for idx in range(28, 36):
        burst_failure[idx] = clamp(0.18 + random.gauss(0, 0.05))
    for idx in range(36, 44):
        burst_failure[idx] = clamp(0.55 + random.gauss(0, 0.08))

    oscillation = []
    for idx in range(length):
        wave = 0.75 + 0.22 * math.sin(idx / 3.0)
        oscillation.append(clamp(wave + random.gauss(0, 0.035)))

    return {
        'stable_service': stable,
        'gradual_degradation': degradation,
        'burst_failure': burst_failure,
        'oscillating_service': oscillation,
    }


def one_step_predictions(values):
    rows = []
    for idx in range(WINDOW, len(values)):
        history = values[:idx]
        actual = values[idx]
        sma = moving_average(history, WINDOW)
        ewma = ewma_forecast(history, ALPHA)
        score = risk_score(history, ewma)
        rows.append({
            't': idx,
            'actual': actual,
            'sma': sma,
            'ewma': ewma,
            'risk_score': score,
            'risk': classify_risk(score),
        })
    return rows


def mae(rows, key):
    return sum(abs(row[key] - row['actual']) for row in rows) / len(rows)


def rmse(rows, key):
    return math.sqrt(sum((row[key] - row['actual']) ** 2 for row in rows) / len(rows))


def classification_metrics(rows):
    tp = fp = tn = fn = 0
    for row in rows:
        actual_incident = row['actual'] < 0.7
        predicted_incident = row['risk'] in {'MEDIUM', 'HIGH'}
        if actual_incident and predicted_incident:
            tp += 1
        elif not actual_incident and predicted_incident:
            fp += 1
        elif not actual_incident and not predicted_incident:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return tp, fp, tn, fn, precision, recall, f1


def write_prediction_rows(scenario_rows):
    path = os.path.join(OUT_DIR, 'forecast_points.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['scenario', 't', 'actual', 'sma', 'ewma', 'risk_score', 'risk'])
        for scenario, rows in scenario_rows.items():
            for row in rows:
                writer.writerow([
                    scenario,
                    row['t'],
                    f"{row['actual']:.3f}",
                    f"{row['sma']:.3f}",
                    f"{row['ewma']:.3f}",
                    f"{row['risk_score']:.3f}",
                    row['risk'],
                ])
    return path


def write_summary(scenario_rows):
    path = os.path.join(OUT_DIR, 'forecast_metrics.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            'scenario', 'mae_sma', 'rmse_sma', 'mae_ewma', 'rmse_ewma',
            'tp', 'fp', 'tn', 'fn', 'precision', 'recall', 'f1'
        ])
        for scenario, rows in scenario_rows.items():
            tp, fp, tn, fn, precision, recall, f1 = classification_metrics(rows)
            writer.writerow([
                scenario,
                f"{mae(rows, 'sma'):.3f}",
                f"{rmse(rows, 'sma'):.3f}",
                f"{mae(rows, 'ewma'):.3f}",
                f"{rmse(rows, 'ewma'):.3f}",
                tp, fp, tn, fn,
                f"{precision:.3f}",
                f"{recall:.3f}",
                f"{f1:.3f}",
            ])
    return path


def svg_polyline(points, width, height, x_min, x_max, y_min=0.0, y_max=1.05):
    coords = []
    for x, y in points:
        sx = 50 + (x - x_min) / (x_max - x_min) * (width - 80)
        sy = 20 + (y_max - y) / (y_max - y_min) * (height - 70)
        coords.append(f'{sx:.1f},{sy:.1f}')
    return ' '.join(coords)


def write_line_svg(path, title, series):
    width, height = 900, 360
    max_x = max(x for values in series.values() for x, _ in values)
    colors = {
        'Фактическая доступность': '#2563eb',
        'SMA(5)': '#f59e0b',
        'EWMA(alpha=0.35)': '#16a34a',
    }
    dashes = {
        'Фактическая доступность': '',
        'SMA(5)': ' stroke-dasharray="8 5"',
        'EWMA(alpha=0.35)': ' stroke-dasharray="3 5"',
    }

    incident_y = 20 + (1.05 - 0.7) / 1.05 * (height - 70)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="50" y="22" font-family="Arial" font-size="18" font-weight="700">{title}</text>',
        '<line x1="50" y1="290" x2="870" y2="290" stroke="#94a3b8"/>',
        '<line x1="50" y1="20" x2="50" y2="290" stroke="#94a3b8"/>',
        f'<line x1="50" y1="{incident_y:.1f}" x2="870" y2="{incident_y:.1f}" stroke="#ef4444" stroke-opacity="0.55"/>',
        '<text x="55" y="312" font-family="Arial" font-size="12">номер наблюдения</text>',
        '<text x="8" y="155" font-family="Arial" font-size="12" transform="rotate(-90 8 155)">доступность</text>',
        f'<text x="760" y="{incident_y - 6:.1f}" font-family="Arial" font-size="12" fill="#ef4444">порог 0.7</text>',
    ]
    legend_x = 540
    for idx, (name, values) in enumerate(series.items()):
        points = svg_polyline(values, width, height, 0, max_x)
        color = colors[name]
        dash = dashes[name]
        legend_y = 42 + idx * 20
        lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"{dash}/>')
        lines.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 32}" y2="{legend_y}" stroke="{color}" stroke-width="3"{dash}/>')
        lines.append(f'<text x="{legend_x + 40}" y="{legend_y + 4}" font-family="Arial" font-size="12">{name}</text>')
    lines.append('</svg>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def write_bar_svg(path, labels, sma, ewma):
    width, height = 900, 360
    max_value = max(max(sma), max(ewma), 0.01) * 1.2
    plot_top, plot_bottom = 50, 290
    plot_height = plot_bottom - plot_top
    group_width = 180
    start_x = 80
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="50" y="24" font-family="Arial" font-size="18" font-weight="700">Сравнение средней абсолютной ошибки прогноза</text>',
        '<line x1="50" y1="290" x2="870" y2="290" stroke="#94a3b8"/>',
        '<line x1="50" y1="50" x2="50" y2="290" stroke="#94a3b8"/>',
        '<text x="18" y="170" font-family="Arial" font-size="12" transform="rotate(-90 18 170)">MAE</text>',
        '<rect x="620" y="48" width="14" height="14" fill="#f59e0b"/><text x="642" y="60" font-family="Arial" font-size="12">SMA(5)</text>',
        '<rect x="720" y="48" width="14" height="14" fill="#16a34a"/><text x="742" y="60" font-family="Arial" font-size="12">EWMA</text>',
    ]
    for idx, label in enumerate(labels):
        x = start_x + idx * group_width
        sma_h = sma[idx] / max_value * plot_height
        ewma_h = ewma[idx] / max_value * plot_height
        lines.append(f'<rect x="{x}" y="{plot_bottom - sma_h:.1f}" width="48" height="{sma_h:.1f}" fill="#f59e0b"/>')
        lines.append(f'<rect x="{x + 54}" y="{plot_bottom - ewma_h:.1f}" width="48" height="{ewma_h:.1f}" fill="#16a34a"/>')
        lines.append(f'<text x="{x - 15}" y="316" font-family="Arial" font-size="11">{label}</text>')
        lines.append(f'<text x="{x}" y="{plot_bottom - sma_h - 6:.1f}" font-family="Arial" font-size="10">{sma[idx]:.3f}</text>')
        lines.append(f'<text x="{x + 54}" y="{plot_bottom - ewma_h - 6:.1f}" font-family="Arial" font-size="10">{ewma[idx]:.3f}</text>')
    lines.append('</svg>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def plot_scenarios(scenarios, scenario_rows):
    for scenario, values in scenarios.items():
        rows = scenario_rows[scenario]
        write_line_svg(
            os.path.join(OUT_DIR, f'{scenario}.svg'),
            f'Сценарий: {scenario}',
            {
                'Фактическая доступность': list(enumerate(values)),
                'SMA(5)': [(row['t'], row['sma']) for row in rows],
                'EWMA(alpha=0.35)': [(row['t'], row['ewma']) for row in rows],
            },
        )


def plot_summary(scenario_rows):
    scenarios = list(scenario_rows.keys())
    sma = [mae(scenario_rows[name], 'sma') for name in scenarios]
    ewma = [mae(scenario_rows[name], 'ewma') for name in scenarios]
    write_bar_svg(os.path.join(OUT_DIR, 'forecast_mae_comparison.svg'), scenarios, sma, ewma)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    scenarios = build_scenarios()
    scenario_rows = {
        scenario: one_step_predictions(values)
        for scenario, values in scenarios.items()
    }

    points_path = write_prediction_rows(scenario_rows)
    metrics_path = write_summary(scenario_rows)
    plot_scenarios(scenarios, scenario_rows)
    plot_summary(scenario_rows)

    print(f'Experiment points: {points_path}')
    print(f'Experiment metrics: {metrics_path}')
    print(f'Experiment plots: {OUT_DIR}')


if __name__ == '__main__':
    main()

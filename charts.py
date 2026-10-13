#!/usr/bin/env python3
"""Generate three monthly PNG charts from the recorded observations."""
import argparse
import calendar
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from settings import load as load_config

BASE = Path(__file__).resolve().parent
os.environ['MPLCONFIGDIR'] = str(BASE / '.cache/matplotlib')
os.environ['XDG_CACHE_HOME'] = str(BASE / '.cache')
MONTHS = ('styczeń', 'luty', 'marzec', 'kwiecień', 'maj', 'czerwiec',
          'lipiec', 'sierpień', 'wrzesień', 'październik', 'listopad', 'grudzień')
SPECS = (
    ('temperatura', 'Temperatura', '°C', '#C15E29', 2),
    ('wilgotnosc', 'Wilgotność powietrza', '%', '#2176B5', 3),
    ('cisnienie', 'Ciśnienie atmosferyczne', 'hPa', '#18847B', 4),
)


def month_bounds(year, month, tz):
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=tz)
    return start, end


def load_rows(db_path, start, end, now):
    with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return db.execute('''SELECT checked_at,status,temperature_c,humidity_percent,pressure_hpa
            FROM readings WHERE checked_at >= ? AND checked_at < ? AND checked_at <= ?
            ORDER BY checked_at,id''', tuple(
                value.astimezone(timezone.utc).isoformat(timespec='seconds')
                for value in (start, end, now))).fetchall()


def series(rows, column, tz, max_gap_minutes=90):
    x, y = [], []
    previous = None
    for row in rows:
        stamp = datetime.fromisoformat(row[0])
        if previous is not None and (stamp - previous).total_seconds() > max_gap_minutes * 60:
            x.append((previous + timedelta(seconds=1)).astimezone(tz))
            y.append(float('nan'))
        x.append(stamp.astimezone(tz))
        value = row[column]
        y.append(float(value) if row[1] == 'ok' and value is not None else float('nan'))
        previous = stamp
    return x, y


def number(value):
    return f'{value:.1f}'.replace('.', ',')


def generate(month=None, *, db_path=None, output=None, now=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    os.umask(0o077)
    config = load_config()
    tz = ZoneInfo(config['timezone'])
    now = now or datetime.now(tz)
    local_now = now.astimezone(tz)
    year, month_number = map(int, month.split('-')) if month else (local_now.year, local_now.month)
    start, end = month_bounds(year, month_number, tz)
    rows = load_rows(db_path or BASE / 'data/meteo.sqlite3', start, end, now)
    output = output or BASE / 'wykresy'
    output.mkdir(parents=True, exist_ok=True)
    month_label = f'{MONTHS[month_number - 1]} {year}'
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 12,
                         'axes.unicode_minus': True, 'axes.formatter.useoffset': False})
    manifest = {'month': f'{year:04d}-{month_number:02d}',
                'generated_at': local_now.isoformat(timespec='seconds'),
                'timezone': config['timezone'], 'charts': {}}
    for slug, title, unit, color, column in SPECS:
        x, y = series(rows, column, tz, config["stale_after_minutes"])
        valid = [(stamp, value) for stamp, value in zip(x, y) if math.isfinite(value)]
        # Use a 16:9 canvas compatible with common image preview crops.
        fig, ax = plt.subplots(figsize=(14, 7.875), dpi=120)
        fig.patch.set_facecolor('#F5F7FA')
        ax.set_facecolor('white')
        fig.subplots_adjust(left=.09, right=.96, bottom=.22, top=.69)
        fig.text(.09, .92, 'STACJA METEO  /  ' + month_label.upper(),
                 color='#64748B', fontsize=11, weight='bold')
        fig.text(.09, .845, title, fontsize=25, weight='bold', color='#172B42')
        if valid:
            last_time, last_value = valid[-1]
            vals = [v for _, v in valid]
            fig.text(.96, .845, f'{number(last_value)} {unit}', ha='right',
                     fontsize=29, weight='bold', color=color)
            fig.text(.96, .79, 'Ostatni pomiar: ' + last_time.strftime('%d.%m, %H:%M'),
                     ha='right', fontsize=10, color='#64748B')
            fig.text(.09, .775,
                     f'Minimum: {number(min(vals))} {unit}     •     Maksimum: {number(max(vals))} {unit}',
                     fontsize=12, color='#475569')
            ax.plot(x, y, color=color, linewidth=1.7, marker='o',
                    markersize=4 if len(valid) < 15 else 2, zorder=3)
            ax.scatter([last_time], [last_value], s=55, facecolor=color,
                       edgecolor='white', linewidth=1.3, zorder=4)
            if slug == 'wilgotnosc':
                ax.set_ylim(0, 100)
            else:
                padding = max((max(vals) - min(vals)) * .15, 1 if slug == 'temperatura' else 2)
                ax.set_ylim(min(vals) - padding, max(vals) + padding)
        else:
            fig.text(.96, .845, 'Brak pomiarów', ha='right', fontsize=19, color='#64748B')
            ax.text(.5, .5, 'Brak poprawnych pomiarów w tym miesiącu', transform=ax.transAxes,
                    ha='center', va='center', color='#64748B', fontsize=14)
            ax.set_ylim(0, 100 if slug == 'wilgotnosc' else 1)
            ax.set_yticks([])
        ax.set_xlim(start, end - timedelta(seconds=1))
        if start <= local_now < end:
            ax.axvspan(local_now, end, color='#F1F5F9', zorder=0)
        days = [1, 5, 10, 15, 20, 25, calendar.monthrange(year, month_number)[1]]
        ax.set_xticks([datetime(year, month_number, day, tzinfo=tz) for day in days])
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d', tz=tz))
        ax.set_xlabel('Dzień miesiąca', labelpad=10, color='#475569')
        ax.set_ylabel(unit, labelpad=12, color='#475569')
        if valid:
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f'{value:g}'.replace('.', ',')))
        ax.grid(axis='y', color='#E2E8F0', linewidth=.8)
        ax.grid(axis='x', color='#EDF1F5', linewidth=.6)
        ax.set_axisbelow(True)
        ax.tick_params(axis='both', length=0, pad=9, colors='#475569')
        for spine in ax.spines.values():
            spine.set_visible(False)
        footer = f'Liczba poprawnych pomiarów: {len(valid)}'
        if valid:
            footer += '  •  Dane od ' + valid[0][0].strftime('%d.%m, %H:%M')
        fig.text(.09, .095, footer, fontsize=10, color='#64748B')
        fig.text(.09, .052, 'Przerwy oznaczają brak danych. Czas lokalny: ' + config['timezone'],
                 fontsize=9, color='#64748B')
        fig.text(.96, .052, 'Aktualizacja: ' + local_now.strftime('%d.%m.%Y, %H:%M'),
                 ha='right', fontsize=9, color='#64748B')
        target = output / f'{slug}.png'
        temporary = target.with_suffix('.tmp')
        try:
            fig.savefig(temporary, format='png', dpi=120, facecolor=fig.get_facecolor(),
                        metadata={'Title': f'{title} — {month_label}'})
            temporary.replace(target)
        finally:
            plt.close(fig)
        manifest['charts'][slug] = {'file': target.name, 'count': len(valid),
            'last_success_at': valid[-1][0].isoformat() if valid else None}
    temp_manifest = output / 'manifest.tmp'
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp_manifest.replace(output / 'manifest.json')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', help='Optional month YYYY-MM; defaults to current local month')
    args = parser.parse_args()
    print(json.dumps(generate(args.month), ensure_ascii=False, indent=2))

"""Render the two timing comparisons from the ordinary paired trials."""
import csv
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

CASES = ('batch_total', 'threshold_guard', 'fib_updates_8', 'split_counter', 'airline_reservations_6')
COLORS = {'before': '#525d72', 'after': '#00766a'}


def draw(folder):
    with (folder / 'trials.csv').open(encoding='utf8') as stream:
        data = {(r['case'], r['variant'], r['mode'], int(r['rep'])): r
                for r in csv.DictReader(stream) if r['group'] == 'formal'}
    fig, (front, fib) = plt.subplots(1, 2, figsize=(10.4, 4.2), width_ratios=(1.22, 1),
                                     layout='constrained')
    front.axvline(110, color='#aa6e18', linestyle='--', linewidth=1.2)
    front.text(113, 0.91, '110 ms target', transform=front.get_xaxis_transform(), color='#855510', fontsize=9)
    for y, case in enumerate(CASES):
        vals = {v: [float(data[case, v, 'I3', i]['front_ms']) for i in range(1, 6)] for v in COLORS}
        med = {v: statistics.median(values) for v, values in vals.items()}
        front.plot([med['before'], med['after']], [y, y], color='#b8c3c7', linewidth=2, zorder=1)
        for variant, color in COLORS.items():
            front.scatter(vals[variant], [y]*5, s=22, color=color, alpha=.36, zorder=2)
            front.scatter(med[variant], y, s=53, color=color, zorder=3)
    front.set(yticks=range(len(CASES)), yticklabels=CASES, ylim=(4.55, -0.85),
              xlabel='Candidate frontend wall time (ms)', title='Five cases · samples and medians')
    for variant, color in COLORS.items():
        delta = [float(data['fib_updates_8', variant, 'I3', i]['p1_ms']) -
                 float(data['fib_updates_8', variant, 'F1', i]['p1_ms']) for i in range(1, 6)]
        fib.plot(range(1, 6), delta, 'o-', color=color, linewidth=1.8, markersize=6, zorder=3)
    fib.axhline(0, color='#34494b', linewidth=1)
    fib.set(xticks=range(1, 6), xlabel='Paired repeat', ylabel='I3 − F1 wall time (ms)',
            title='Fibonacci, 8 updates · complete candidate')
    for axis in (front, fib):
        axis.title.set_fontsize(12)
        axis.spines[['right','top']].set_visible(False)
        axis.grid(axis='x' if axis is front else 'y', linewidth=.5, alpha=.3)
        axis.set_axisbelow(True)
    fig.legend([Line2D([], [], color=c, marker='o') for c in COLORS.values()],
               ['Stage 8 control', 'Stage 9 frontend'], loc='outside lower center', ncol=2, frameon=False)
    fig.savefig(folder / 'frontend-and-fibonacci.png', dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    draw(Path(sys.argv[1]))

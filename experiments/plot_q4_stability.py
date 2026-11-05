"""Optional figure renderer: matplotlib 3.4.3; never used by the controller."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT=Path(__file__).resolve().parents[1]
p=json.loads((ROOT/'experiments/q4_stability_final_analysis.json').read_text())
h=json.loads((ROOT/'experiments/q4_stability_final_holdout.json').read_text())
colors=['#3869a8','#da6b35']
fig,axes=plt.subplots(1,2,figsize=(11.2,4.1))
for variant,label,color in zip(('Q4_FORK_VIEWS','Q4_STABLE15'),('Baseline','Q4_STABLE15'),colors):
    xs=sorted(r['seconds_per_source'] for r in h['rows'] if r['variant']==variant)
    axes[0].step(xs,[(i+1)/len(xs) for i in range(len(xs))],where='post',label=label,color=color,lw=2)
axes[0].axvline(700,color='#777777',ls='--',lw=1)
axes[0].axhline(.95,color='#bbbbbb',ls=':',lw=1)
axes[0].set(xlabel='Virtual seconds / source',ylabel='Fraction of cases',title='Independent holdout: 240 paired cases',ylim=(0,1.015))
axes[0].legend(loc='lower right',frameon=False)
for j,key in enumerate(('baseline','final')):
    values=[p['by_source_count'][str(k)][key] for k in (10,11,15,16)]
    xs=[i+(j-.5)*.30 for i in range(4)]
    axes[1].bar(xs,[v['mean'] for v in values],width=.27,color=colors[j],alpha=.80)
    axes[1].scatter(xs,[v['p95'] for v in values],marker='D',s=40,color=colors[j],edgecolor='white',lw=.7,zorder=3)
axes[1].set_xticks(range(4));axes[1].set_xticklabels((10,11,15,16))
axes[1].axhline(700,color='#777777',ls='--',lw=1)
axes[1].set(xlabel='Source count (60 cases in each group)',ylabel='Virtual seconds / source',title='Bars: mean; diamonds: P95',ylim=(0,1000))
for ax in axes:
    ax.spines['top'].set_visible(False);ax.spines['right'].set_visible(False)
    ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
fig.tight_layout(pad=1.3)
for ext in ('png','pdf','svg'):
    fig.savefig(ROOT/f'experiments/q4_stability_holdout.{ext}',dpi=200,bbox_inches='tight')
svg=ROOT/'experiments/q4_stability_holdout.svg'
svg_text='\n'.join(line.rstrip() for line in svg.read_text(encoding='utf8').splitlines())+'\n'
with svg.open('w',encoding='utf8',newline='\n') as stream:
    stream.write(svg_text)

"""Create static figures from the exported distributions and cross-input replay receipts."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm

NAMES=['batch_total','threshold_guard','split_counter','partial_counter','batch_retained','fib_updates','airline_reservations','fib_updates_8','airline_reservations_6']
LABELS=['Batch total','Threshold guard','Split counter','Partial counter','Retained multiplier','Fibonacci (4)','Airline (4)','Fibonacci (8)','Airline (6)']
MODES=['F0','F1','F2','I1','I2','I3']
COLORS=['#64748b','#172554','#b45309','#38a169','#0d9488','#7c3aed']
def save(path):
    plt.savefig(path,dpi=165,bbox_inches='tight',facecolor='white',metadata={'Software':'stage8 matplotlib'})
    plt.close()
def draw(dest):
    data=json.loads((dest/'summary.json').read_bytes())
    groups={(s['case'],s['mode']):s for s in data['groups'] if not s['detail']}
    fig,ax=plt.subplots(figsize=(10.2,6))
    for j,(mode,color) in enumerate(zip(MODES,COLORS)):
        for i,c in enumerate(NAMES):
            d=groups[c,mode]['wall_ms']
            y=i+(j-2.5)*.105
            ax.plot([d['min'],d['max']],[y,y],lw=1.7,color=color,alpha=.65)
            ax.scatter(d['median'],y,s=27,marker=['o','s','^','D','P','v'][j],color=color,label=mode if i==0 else None,zorder=3)
    ax.set_xscale('log');ax.set_yticks(range(len(NAMES)),LABELS);ax.invert_yaxis()
    ax.set_xlabel('Candidate wall time (ms, log scale)');ax.grid(axis='x',alpha=.2,which='both')
    ax.set_title('Six verification modes on the same frozen candidates',loc='left',weight='bold',pad=12)
    ax.legend(ncol=6,loc='upper center',bbox_to_anchor=(.50,-.12),frameon=False)
    for side in ('right','top'):ax.spines[side].set_visible(False)
    fig.subplots_adjust(left=.20,bottom=.2)
    save(dest/'ablation.png')
    fig,ax=plt.subplots(figsize=(9.4,5.5))
    bounds={s['case']:s for s in data['bounds']}
    for i,c in enumerate(NAMES):
        share=bounds[c]['targeted_share_pct']
        ax.barh(i,share,color='#0d9488' if share else '#cbd5e1',height=.55)
        ax.text(share+.026,i,f'{share:.3f}%',va='center',fontsize=9)
    maxval=max(r['targeted_share_pct'] for r in bounds.values())
    ax.set_xlim(0,max(1,maxval*1.24));ax.set_yticks(range(9),LABELS);ax.invert_yaxis()
    ax.set_xlabel('F1 candidate wall time inside the matched prefix and SC regions (%)')
    ax.set_title('Measured time available to existing model reuse',loc='left',weight='bold',pad=12)
    ax.grid(axis='x',alpha=.2)
    for side in ('right','top'):ax.spines[side].set_visible(False)
    fig.subplots_adjust(left=.22,bottom=.15)
    save(dest/'reusable-work.png')
    ledgers={r['case']:r for r in data['ledgers']}
    keys=['front','dispatch','sc','encode','solver','restore','change','theory','observer','residual']
    cols=['Frontend','Dispatch','SC','Encoding','Solver','Restore','Change','Lemma\naudit','Model\nexport','Other']
    matrix=[[ledgers[c][k+'_ms'] for k in keys] for c in NAMES]
    limit=max(abs(v) for row in matrix for v in row)
    fig,ax=plt.subplots(figsize=(11,5.1))
    colors=SymLogNorm(linthresh=2,vmin=-limit,vmax=limit)
    ax.imshow(matrix,aspect='auto',cmap='RdBu_r',norm=colors)
    for i,row in enumerate(matrix):
        for j,v in enumerate(row):
            ink='white' if colors(v)<.19 or colors(v)>.81 else '#101828'
            ax.text(j,i,f'{v:+.1f}',ha='center',va='center',color=ink,fontsize=8)
    ax.set_yticks(range(len(NAMES)),LABELS);ax.set_xticks(range(len(keys)),cols);ax.tick_params(length=0)
    ax.set_title('Where candidate wall time changed (I3 minus F1)',loc='left',weight='bold',pad=12)
    ax.set_xlabel('Paired mean in ms, five detailed runs per mode. Red adds time and blue saves time.',labelpad=10)
    for edge in ax.spines.values():edge.set_visible(False)
    fig.subplots_adjust(left=.22,bottom=.17)
    save(dest/'cost-ledger.png')
    solver=json.loads((dest/'solver.json').read_bytes())
    controls=solver['cross_controls']
    if len(controls)==4 and all(r['matching_searches']==5 for r in controls):
        fig,ax=plt.subplots(figsize=(7,3.7))
        for j,core in enumerate(('baseline','enhanced')):
            series=[next(r for r in controls if r['input']==i and r['solver']==core)['solver_ms'] for i in ('baseline','enhanced')]
            y=[k+(j-.5)*.22 for k in range(2)]
            ax.barh(y,[s['median']/1000 for s in series],height=.19,color=('#25446e','#0d9488')[j],label=core+' core')
            for v,s in zip(y,series):ax.text(s['median']/1000+.08,v,f"{s['median']/1000:.2f} s",va='center',fontsize=9)
        ax.set_yticks([0,1],['Original input','Enhanced input']);ax.invert_yaxis()
        ax.set_xlim(0,max(r['solver_ms']['max'] for r in controls)/1000*1.22)
        ax.set_title('Six-agent P0: identical-input Closure replay',loc='left',weight='bold')
        ax.set_xlabel('Solver wall time (s), median of five');ax.legend(frameon=False)
        for k in ('top','right'):ax.spines[k].set_visible(False)
        fig.subplots_adjust(left=.22,bottom=.2)
        save(dest/'solver-replay.png')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('evidence',type=Path);draw(p.parse_args().evidence)

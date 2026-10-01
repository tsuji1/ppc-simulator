# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.7"]
# ///
"""Generate power heatmaps for MP3 and compare its best point with VIL."""
import argparse, csv, math, re
from dataclasses import dataclass
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

TRACES=(("chicago","Chicago anon"),("wide","WIDE anon 2026-03"),("nyc","NYC anon"))
L2S,L3S=tuple(range(23,10,-1)),tuple(range(22,9,-1))
LAYERS=re.compile(r"(\d+)@(\d+)w(\d+)")
INDEX=re.compile(r"way\d+:index(\d+):")
CAPS={1024,2048,4096,8192}

@dataclass(frozen=True)
class P:
    trace:str; label:str; method:str; power:float; dynamic:float; static:float
    throughput:float; hitrate:float; area:float; entries:int; caps:tuple[int,...]
    detail:str; source_id:str; l2:int|None=None; l3:int|None=None

def cap(caps): return " ".join(f"{x//1024}K" for x in caps)
def n(row,key): return float(row[key])

def read(path,trace,label,threshold):
    out=[]
    with path.open(newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if n(row,"throughput_gbps")+1e-9<threshold: continue
            desc=row["tag_desc"]; layers=LAYERS.findall(desc)
            if row["type"]=="MultiLayerCacheExclusive" and len(layers)==3:
                parsed=tuple((int(r),int(c),int(w)) for r,c,w in layers)
                refs=tuple(x[0] for x in parsed); caps=tuple(x[1] for x in parsed); ways=tuple(x[2] for x in parsed)
                if not(refs[0]==24 and 23>=refs[1]>refs[2]>=10 and all(x in CAPS for x in caps) and ways==(8,8,8)): continue
                method,detail,l2,l3="MP3",f"/{refs[0]} /{refs[1]} /{refs[2]}",refs[1],refs[2]
            elif row["type"]=="UnifiedCache":
                m=INDEX.search(desc); size=int(float(row["entry_count"]))
                if not(m and "way8:" in desc and int(m.group(1)) in ({2}|set(range(16,25))) and desc.count("9-24")==8 and "policy=exclusive" in desc and size in {1024,2048,4096,8192,16384,32768}): continue
                method,caps,detail,l2,l3="VIL",(size,),f"index {m.group(1)}",None,None
            else: continue
            out.append(P(trace,label,method,n(row,"power_mw"),n(row,"dynamic_power_mw"),n(row,"static_power_mw"),n(row,"throughput_gbps"),n(row,"hitrate")*100,n(row,"area_mm2"),int(float(row["entry_count"])),caps,detail,row["id"],l2,l3))
    return out

def save_csv(path,points):
    rows=[]
    for p in points:
        rows.append({"trace_key":p.trace,"trace_label":p.label,"method":p.method,"power_mw":p.power,
        "dynamic_power_mw":p.dynamic,"static_power_mw":p.static,"throughput_gbps":p.throughput,
        "hitrate_percent":p.hitrate,"area_mm2":p.area,"total_entries":p.entries,"capacities":cap(p.caps),
        "refbits_or_index":p.detail,"source_id":p.source_id,"l2_refbits":"" if p.l2 is None else p.l2,
        "l3_refbits":"" if p.l3 is None else p.l3})
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def cell_best(points):
    out={}
    for p in points:
        if p.method!="MP3": continue
        key=(p.l2,p.l3)
        if key not in out or p.power<out[key].power: out[key]=p
    return out

def heatmap(path,grouped,threshold):
    fig,axes=plt.subplots(1,3,figsize=(24,8.7),constrained_layout=True)
    cmap=plt.colormaps["viridis_r"].copy(); cmap.set_bad("#eeeeee")
    for ax,(trace,label) in zip(axes,TRACES):
        cells=cell_best(grouped[trace])
        matrix=[[cells[(l2,l3)].power if (l2,l3) in cells else math.nan for l2 in L2S] for l3 in L3S]
        values=[p.power for p in cells.values()]; lo,hi=min(values),max(values)
        image=ax.imshow(matrix,cmap=cmap,aspect="equal",vmin=lo,vmax=hi)
        winner=min(cells.values(),key=lambda p:p.power)
        for yi,l3 in enumerate(L3S):
            for xi,l2 in enumerate(L2S):
                p=cells.get((l2,l3))
                if not p: continue
                shade=(p.power-lo)/max(hi-lo,1e-12)
                ax.text(xi,yi,f"{p.power:.0f} mW\n{cap(p.caps)}",ha="center",va="center",fontsize=5.2,color="white" if shade>.52 else "#111",linespacing=1.08)
                if p==winner: ax.add_patch(Rectangle((xi-.48,yi-.48),.96,.96,fill=False,edgecolor="#ff2d2d",linewidth=2.2))
        ax.set_xticks(range(13),[f"/{x}" for x in L2S],fontsize=8); ax.set_yticks(range(13),[f"/{x}" for x in L3S],fontsize=8)
        ax.set_xlabel("Layer 2 refbits"); ax.set_ylabel("Layer 3 refbits")
        ax.set_title(f"{label}\nBest {winner.power:.1f} mW • {winner.detail} • {cap(winner.caps)}",fontsize=12,weight="bold")
        fig.colorbar(image,ax=ax,shrink=.78,pad=.02,label="Minimum power (mW)")
    fig.suptitle(f"MP3 minimum power by refbits (throughput ≥ {threshold:g} Gbps)\nEach cell: power and Layer 1 / Layer 2 / Layer 3 capacity; red outline = trace minimum",fontsize=17,weight="bold")
    fig.savefig(path,dpi=190,bbox_inches="tight",facecolor="white"); plt.close(fig)

def compare(path,best,threshold):
    fig,ax=plt.subplots(figsize=(12.5,6.4),constrained_layout=True); width=.34
    for method,offset,color in (("MP3",-width/2,"#2878b5"),("VIL",width/2,"#e07a28")):
        points=[next(p for p in best if p.trace==t and p.method==method) for t,_ in TRACES]
        bars=ax.bar([x+offset for x in range(3)],[p.power for p in points],width,label=method,color=color)
        for bar,p in zip(bars,points):
            config=cap(p.caps) if method=="MP3" else f"IDEAL {cap(p.caps)}"
            ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+10,f"{p.power:.1f} mW\n{config}",ha="center",fontsize=9,weight="bold")
    ax.set_xticks(range(3),[x[1] for x in TRACES]); ax.set_ylabel("Minimum power (mW)")
    ax.set_title(f"Best MP3 vs proposed VIL at throughput ≥ {threshold:g} Gbps",fontsize=16,weight="bold")
    ax.grid(axis="y",alpha=.25); ax.legend(frameon=False); ax.set_ylim(0,max(p.power for p in best)*1.22)
    fig.savefig(path,dpi=190,bbox_inches="tight",facecolor="white"); plt.close(fig)

def report(path,best,threshold):
    lines=["# Power comparison","",f"Selection: minimum power at throughput >= {threshold:g} Gbps.","Model: CACTI SRAM + DRAM burst energy (4000 pJ) + DRAM background power (320.1 mW).","","| Trace | Method | Power | Configuration | Throughput | Hitrate |","|---|---:|---:|---|---:|---:|"]
    for t,label in TRACES:
        for method in ("MP3","VIL"):
            p=next(x for x in best if x.trace==t and x.method==method); config=cap(p.caps) if method=="MP3" else f"IDEAL {cap(p.caps)}"
            lines.append(f"| {label} | {method} | {p.power:.3f} mW | {p.detail}; {config} | {p.throughput:.1f} Gbps | {p.hitrate:.4f}% |")
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")

def main():
    parser=argparse.ArgumentParser(); default=Path(__file__).resolve().parent/"reports"/"mp3_sweep_results"
    parser.add_argument("--report-dir",type=Path,default=default); parser.add_argument("--throughput",type=float,default=1024.0); a=parser.parse_args()
    out=a.report_dir.resolve(); grouped={}; all_points=[]
    for trace,label in TRACES:
        grouped[trace]=read(out/"power_raw"/trace/"comparison_detail.csv",trace,label,a.throughput); all_points+=grouped[trace]
    best=[min((p for p in grouped[t] if p.method==m),key=lambda p:p.power) for t,_ in TRACES for m in ("MP3","VIL")]
    save_csv(out/"power_points.csv",all_points); save_csv(out/"best_power_by_trace.csv",best)
    heatmap(out/"power_heatmap.png",grouped,a.throughput); compare(out/"power_best_comparison.png",best,a.throughput); report(out/"POWER_REPORT.md",best,a.throughput)
    for p in best: print(f"{p.label:20s} {p.method:3s} {p.power:9.3f} mW  {p.detail:13s} {cap(p.caps)}")

if __name__=="__main__": main()

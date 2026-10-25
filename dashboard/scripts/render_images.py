"""Render immutable, aggregate-only dashboard snapshots as PNG, SVG and CSV."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[2]
COLORS = ['#285b91', '#9ec3e5', '#deebf7', '#fae1dc', '#e6a69a', '#a84236']
REG = FontProperties(fname='/usr/share/fonts/gsfonts/NimbusSans-Regular.otf')
BOLD = FontProperties(fname='/usr/share/fonts/gsfonts/NimbusSans-Bold.otf')
INK = '#17212b'
GRID = '#dce3ea'
COUNTIES_PER_PAGE = 9


def comparison_dates(period):
    def date_range(first, iso):
        day=int(iso[-2:]);month=iso[5:7]
        return (f'Oct {first}' if day==first else f'Oct {first}–{day}') if month=='10' else f'Oct {first}–Nov {day}'
    return f"{date_range(19,period['through_2026'])}, 2026 / {date_range(21,period['through_2024'])}, 2024"


def pct(value, small=False):
    return '—' if value is None else f'{value:.1%}' + ('†' if small else '')


def is_small(cohort):
    return cohort['groups'] < 3 or cohort['votes_2024'] < 100


def figure(counties, periods, destination, cohort='matched', comparison=False):
    combined = comparison or len(counties) > 1
    columns = len(counties) if combined else 2
    width, height = (19.6, 7.1) if combined else (9, 7.7)
    fig = plt.figure(figsize=(width, height), facecolor='white')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis('off')
    def text(x,y,s,size=12,bold=False,align='left',color=INK):
        ax.text(x,y,s,ha=align,va='center',fontsize=size,fontproperties=BOLD if bold else REG,color=color)
    def cell(x,y,w,h,s,bg='white',color=INK,size=17,bold=False,align='center'):
        ax.add_patch(Rectangle((x,y),w,h,facecolor=bg,edgecolor=GRID,linewidth=.7))
        text(x+w/2 if align=='center' else x+.018,y+h/2,s,size,bold,align,color)
    p = periods[0]
    title = 'Texas early vote' if combined else counties[0]['name']
    text(.035,.938,title,26,True)
    text(.965,.938,comparison_dates(p),13,align='right')
    text(.035,.875,'2026 in-person votes as % of 2024',15)
    if combined:
        text(.965,.875,'Crosswalk matched' if cohort=='matched' else 'Unchanged only',12,align='right',color='#526275')
    left=.035; span=.93; labelw=.145 if combined else .36; colw=(span-labelw)/columns
    cell(left,.758,labelw,.069,'2024 margin (pp)',bg='#f5f8fb',size=13,bold=True,align='left')
    names=[c['name'] for c in counties] if combined else ['Crosswalk matched','Unchanged only']
    for i,name in enumerate(names):cell(left+labelw+i*colw,.758,colw,.069,name,bg='#f5f8fb',size=14,bold=True)
    for b in range(6):
        y=.758-(b+1)*.075
        cell(left,y,labelw,.075,p['buckets'][b]['label'],bg=COLORS[b],color='white' if b in (0,5) else INK,size=16,bold=True,align='left')
        for col in range(columns):
            period=periods[col] if combined else p
            method=cohort if combined else ['matched','unchanged'][col]
            c=period['buckets'][b][method]
            cell(left+labelw+col*colw,y,colw,.075,pct(c['ratio'],is_small(c)),size=21,bold=True)
    y=.217
    cell(left,y,labelw,.091,'Matched precincts',bg='#f5f8fb',size=13,align='left')
    for col in range(columns if combined else 1):
        period=periods[col] if combined else p
        label=f"{pct(period['county_ratio'])}\n{period['county_2026']:,} / {period['county_2024']:,}"
        cell(left+labelw+col*colw,y,colw if combined else 2*colw,.091,label,bg='#f5f8fb',size=12)
    cell(left,.165,labelw,.052,'2024 vote coverage',bg='#f5f8fb',size=11,align='left')
    for col in range(columns):
        period=periods[col] if combined else p
        method=cohort if combined else ['matched','unchanged'][col]
        coverage=period[method]['votes_2024']/period['county_2024'] if period['county_2024'] else None
        cell(left+labelw+col*colw,.165,colw,.052,pct(coverage),bg='#f5f8fb',size=12)
    text(.035,.107,'† Fewer than 3 groups or 100 baseline votes.  — No baseline.  Mixed/unknown groups excluded.',10,color='#526275')
    text(.035,.071,'2026-primary precinct maps remain a November proxy. Source revisions and county/state discrepancies: see report.',10,color='#526275')
    for suffix in ['png','svg']:
        with plt.rc_context({'svg.fonttype':'path'}):
            fig.savefig(destination.with_suffix('.'+suffix),dpi=200,facecolor='white',metadata={'Title':title})
    plt.close(fig)


def write_csv(path, rows):
    if not rows:return
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def current_source_note(county, period):
    notes=[]; links=[]
    for year in (2024, 2026):
        through=period[f'through_{year}']
        sources=[s for s in county.get('sources', [])
                 if s['date'].startswith(str(year)) and s['date'] <= through]
        if not sources:continue
        source=max(sources,key=lambda s:(s['date'],s.get('retrieved_at','')))
        note=source.get('note','').strip()
        if note and note not in notes:notes.append(note)
        links.append(f"[{year} source, {source['date']}](<{source['source']}>)")
    return ' '.join(notes + [' · '.join(links)])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot',type=Path,default=ROOT/'dashboard/data/latest.json');parser.add_argument('--output',type=Path);parser.add_argument('--controls',type=Path,default=ROOT/'dashboard/data/completeness.json')
    args=parser.parse_args();snapshot=json.loads(args.snapshot.read_text())
    if len(snapshot.get('completeness_sha256','')) != 64:
        raise ValueError('Snapshot lacks matched-geography qualification; rebuild with the current Rust dashboard before rendering')
    control_bytes=args.controls.read_bytes()
    control_hash=hashlib.sha256(json.dumps(json.loads(control_bytes),separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if control_hash != snapshot['completeness_sha256']:
        raise ValueError('Completion controls changed; rebuild or provide the frozen --controls used by this snapshot')
    out=args.output or ROOT/'analysis'/f"matched-through-{snapshot['through']}";out.mkdir(parents=True,exist_ok=True)
    selected=[];periods=[];rows=[];audits=[]
    for county in snapshot['counties']:
        period=next((p for p in county['periods'] if p['day']==snapshot['days']),None)
        if not period:continue
        selected.append(county);periods.append(period)
        figure([county],[period],out/f"{county['id']}-margin-table")
        for bucket in period['buckets']:
            for cohort in ['matched','unchanged']:
                rows.append({'county':county['name'],'through_2026':period['through_2026'],'through_2024':period['through_2024'],'margin_band':bucket['label'],'cohort':cohort,**bucket[cohort]})
        for group in period['groups']:
            audits.append({'county':county['id'],**{k:';'.join(v) if isinstance(v,list) else v for k,v in group.items()}})
    image_links=[]
    if selected:
        page_count=(len(selected)+COUNTIES_PER_PAGE-1)//COUNTIES_PER_PAGE
        page_size,extra=divmod(len(selected),page_count)
        start=0
        for page in range(page_count):
            end=start+page_size+(page<extra)
            suffix='' if page==0 else f'-{page+1}'
            label='' if page_count==1 else f' {page+1}'
            for cohort,stem,title in [('matched','county-comparison','Combined image'),
                                      ('unchanged','county-comparison-unchanged','Unchanged-only image')]:
                name=stem+suffix
                figure(selected[start:end],periods[start:end],out/name,cohort=cohort,comparison=True)
                image_links.append(f'[{title}{label}]({name}.png)')
            start=end
    write_csv(out/'margin-buckets.csv',rows);write_csv(out/'group-inclusion-audit.csv',audits)
    lines=[f"# Texas precinct buckets through {snapshot['through']}","",
        f"Retrieved {snapshot['generated_at']}. {snapshot['days']} completed early-voting days: {comparison_dates(periods[0]) if periods else 'unavailable'}. Current-day partial voting is excluded.","",
        ' · '.join(image_links+["[Bucket CSV](margin-buckets.csv)","[Group inclusion audit](group-inclusion-audit.csv)"]),"",
        "| County | 2026 votes | 2024 votes | 2026 / 2024 | Matched coverage | Unchanged coverage |", "|---|---:|---:|---:|---:|---:|"]
    for county,period in zip(selected,periods):
        lines.append(f"| [{county['name']}]({county['id']}-margin-table.png) | {period['county_2026']:,} | {period['county_2024']:,} | {pct(period['county_ratio'])} | {pct(period['matched']['votes_2024']/period['county_2024'])} | {pct(period['unchanged']['votes_2024']/period['county_2024'])} |")
    lines.extend(["", "Percentages compare vote counts, not registered-voter turnout rates. Bucket ratios divide summed 2026 in-person votes by summed 2024 votes; they are not averages of precinct percentages. Winning margins use Harris and Trump votes only, with boundaries 0–<15, 15–<30 and ≥30 percentage points. Ties and absent presidential returns are unclassified. A common geographic group enters a bucket only when all its 2024 precincts belong to that same bucket. Unchanged-only additionally requires an exact equal-shape precinct pair. A zero denominator remains undefined; † marks fewer than three groups or 100 baseline votes.","", snapshot['geography'],"", "County totals compare the same available precinct geography in both cycles; missing observations are excluded from both sides. The coverage rows measure each cohort's share of 2024 cumulative votes. Hays has especially limited matched coverage. These are ecological descriptions, with no causal or individual-party inference.","", "Source selection and October 23 four-day audit controls (later source revisions may differ):",""])
    notes={
        'travis':'County daily ordinary Early Vote workbooks in both years; limited and mail workbooks excluded. Four-day totals reconcile to the vendor graph; current daily ±1 differences cancel.',
        'dallas':'County dated in-person workbooks in both years, deduplicated by voter identity. The 2026 roster exceeds county location totals by 64; 2024 daily controls match. Current/historical unassigned totals are 158/120. Current day one was revised since the archived analysis.',
        'montgomery':'County ordinary E only; exclude L and mail. Deduplicate identities across jurisdictions and daily files. Two historical cross-day repeats reduce the daily sum 70,907 to 70,905 unique voters; the graph is 70,903. No precinct counts were arbitrarily changed to force graph reconciliation.',
        'bell':'State IN-PERSON daily rosters. State total 28,049 differs from broader county total 28,094. The state lacks separate limited/provisional flags. Five current votes have labels outside the geographic universe and remain unassigned; no suffix repair is guessed.',
        'hays':'County dated current roster, EARLY VOTED plus Prov. N only, filtered before deduplication. Limited/provisional votes excluded. State current 38,369 differs from the accepted county ordinary 38,190; historical state 38,590 matches summary controls.',
        'ellis':'County ordinary cumulative workbook through October 22, 26,788, matches the official county summary; the state roster is 11 lower. No per-voter date field exists, so earlier current precinct cutoffs are unavailable. Historical state 32,582 matches controls.',
        'mclennan':'Current state daily in-person exports are now available, including 4,912 on day one; the original mail-only response was correctly treated as missing. Historical state cumulative 24,166 matches its summary. Numeric labels 59 and 059 are normalized and summed.',
        'hockley':'One state in-person roster series in each year. Historical roster 2,684 is 11 below countywide state summary 2,695; absent records cannot be placed into precincts. Presidential returns and the qualified 1:1 bridge are inherited unchanged.',
        'madison':'One state in-person roster series in each year. Current state 1,081 differs from dated county PDFs 1,086. Historical roster 1,678 is eight below summary 1,686. Conflicting county/state series are preserved separately and never blended.'}
    for county,period in zip(selected,periods):
        lines.append(f"- **{county['name']}**: {notes.get(county['id']) or current_source_note(county,period)}")
    lines.extend(["", "Source URLs, retrieval timestamps and hashes are in [snapshot.json](snapshot.json). Fetch recipes, independent controls and aggregate-only evidence: [county A](../../sources/refresh-2026-10-23/county-a/findings.md), [county B](../../sources/refresh-2026-10-23/county-b/findings.md), [county C](../../sources/refresh-2026-10-23/county-c/findings.md). Original day-one inputs and graphics are preserved.","", "Run [the Rust dashboard](../../dashboard/README.md) for automatic refresh, cumulative-day selection, county/cohort views, precinct search and CSV export. Only precinct aggregates and provenance are saved; raw voter names, IDs and source rosters remain in memory."])
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    (out/'reference-data.json').write_bytes((ROOT/'dashboard/data/reference.json').read_bytes())
    # Freeze the aggregate inputs to every image alongside its exports.
    (out/'snapshot.json').write_text(json.dumps(snapshot,indent=2)+'\n')
    (out/'completion-controls.json').write_bytes(control_bytes)
    print(json.dumps({'output':str(out),'counties':len(selected),'comparison_pages':len(image_links)//2,'bucket_rows':len(rows),'groups':len(audits)}))

if __name__=='__main__':main()

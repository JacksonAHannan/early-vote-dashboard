#!/usr/bin/env python3
"""Adversarial Texas source audit. Read-only; no network or voter detail records.

Reconstruct controls from immutable publisher bytes using independent site-level
sums where possible. Surface revisions and suspicious zeros without inventing a
replacement count or silently changing the publisher's observations.
"""
from __future__ import annotations
import collections
import datetime as dt
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

PROJECT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('TURNOUT_AUDIT_ROOT', str(PROJECT)))
TAG = os.environ.get('TURNOUT_AUDIT_TAG', '')
OUT = PROJECT / ('analysis/texas-stress/source-audit' + ('-' + TAG if TAG else '') + '.json')
CHECKS = 0

def check(condition, message):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(message)

def eq(actual, expected, label):
    check(actual == expected, f'{label}: {actual!r} != {expected!r}')

class Table(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = None; self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('td', 'th') and self.row is not None: self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row); self.row = None

def count(s):
    if s in ('', '-', '—', 'N/A', 'NA', None): return None
    s = str(s).replace(',', '')
    check(s.isascii() and s.isdigit(), 'non-count in official aggregate')
    return int(s)

def canonical(s): return ''.join(c.lower() for c in s if c.isascii() and c.isalnum())

def pdf(raw):
    check(raw.startswith(b'%PDF'), 'aggregate PDF magic')
    return subprocess.check_output(['pdftotext', '-layout', '-', '-'], input=raw).decode()

def suffix_numbers(line):
    cells = line.split(); result = []
    for value in reversed(cells):
        if not re.fullmatch(r'[\d,]+', value): break
        result.append(int(value.replace(',', '')))
    return list(reversed(result))

def workbook(raw):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            shared = [''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rows = []
        for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//m:row', ns):
            cells = {}
            for cell in row:
                value = cell.find('m:v', ns)
                value = value.text if value is not None else ''
                if cell.get('t') == 's': value = shared[int(value)]
                if cell.get('t') == 'inlineStr': value = ''.join(cell.find('m:is', ns).itertext())
                if value: cells[re.sub(r'\d+', '', cell.get('r'))] = value
            rows.append(cells)
        return rows

def native_control(county, year, raw):
    """Return full-site daily values and cumulative series, not collector output."""
    first = dt.date(year, 10, 21 if year == 2024 else 19)
    if county == 'harris':
        text = pdf(raw)
        sites = [suffix_numbers(line) for line in text.splitlines()
                 if re.match(r'^\s*\d+\s', line) and len(suffix_numbers(line)) == 13]
        check(len(sites) >= 60, 'Harris site universe')
        sums = [sum(r[i] for r in sites) for i in range(13)]
        for row in sites: eq(sum(row[:12]), row[12], 'Harris per-site row arithmetic')
        published = suffix_numbers(next(line for line in text.splitlines() if 'Early In-Person Voters:' in line))
        eq(sums, published, 'Harris all site rows vs published IP total')
        return {str(first + dt.timedelta(days=i)): (sums[i], sum(sums[:i+1])) for i in range(12)}, len(sites)
    if county == 'tarrant':
        text = pdf(raw)
        header = next(line for line in text.splitlines() if re.search(r'\bTotal\s+\d\d/\d\d', line))
        dates = [dt.datetime.strptime(f'{x}/{year}', '%m/%d/%Y').date() for x in re.findall(r'\d\d/\d\d', header)]
        published = suffix_numbers(next(line for line in text.splitlines() if line.startswith('Total ')))
        sites = [suffix_numbers(line) for line in text.splitlines() if len(suffix_numbers(line)) == len(dates)+1 and not line.startswith('Total ')]
        check(len(sites) >= 40, 'Tarrant site universe')
        for row in sites: eq(row[0], sum(row[1:]), 'Tarrant per-site row arithmetic')
        eq([sum(r[i] for r in sites) for i in range(len(dates)+1)], published, 'Tarrant all site rows vs published total')
        return {str(d): (published[i+1], sum(published[1:i+2])) for i,d in enumerate(dates)}, len(sites)
    if county == 'dallas':
        rows = workbook(raw)
        totals = next(r for r in rows if r.get('A') == 'Daily Unofficial Total')
        header = next(r for r in rows if r.get('A') in ('Vote Center', 'Vote Center Name'))
        dates = {c:dt.date(1899,12,30)+dt.timedelta(days=int(float(v))) for c,v in header.items() if re.fullmatch(r'\d{5}', v)}
        cumulcol = next(c for c,v in header.items() if v == 'Cumulative Total')
        sites = [r for r in rows[rows.index(totals)+1:] if r.get('A')]
        check(len(sites) >= 10, 'Dallas site universe')
        for c in dates: eq(sum(int(r.get(c,'0')) for r in sites), int(totals[c]), 'Dallas site sum')
        for r in sites: eq(sum(int(r.get(c,'0')) for c in dates), int(r[cumulcol]), 'Dallas site cumulative')
        values = sorted((d,int(totals[c])) for c,d in dates.items())
        return {str(d):(n,sum(x[1] for x in values[:i+1])) for i,(d,n) in enumerate(values)}, len(sites)
    if county in ('travis', 'montgomery'):
        text = raw.decode('utf-8-sig')
        # Inspect separate arrays; never add provisional or mailed records to EV.
        pairs = re.findall(r"evData\.push\(\['([^']+)',(\d+)\]\)", text)
        values = [(dt.datetime.strptime(d,'%m/%d/%Y').date(), int(n)) for d,n in pairs]
        eq(len(values),len({d for d,n in values}), 'ElectionLink unique dates')
        check(all(d.year == year for d,n in values), 'ElectionLink year')
        return {str(d):(n,sum(x[1] for x in values[:i+1])) for i,(d,n) in enumerate(values)}, len(values)
    if county == 'bexar':
        parser = Table(); text = raw.decode(); parser.feed(text)
        when = dt.datetime.strptime(re.search(r'BALLOTS CAST THIS DATE\s+(\d\d/\d\d/\d{4})',text)[1], '%m/%d/%Y').date()
        sites = [r for r in parser.rows if len(r)==4 and all(re.fullmatch(r'[\d,]+',v) for v in r[1:]) and r[0] != 'TOTAL']
        check(len(sites) >= 10, 'Bexar site universe')
        for r in sites: eq(count(r[1])+count(r[2]), count(r[3]), 'Bexar site daily plus previous')
        return {str(when):(sum(count(r[1]) for r in sites),sum(count(r[3]) for r in sites))}, len(sites)
    if county == 'fortbend':
        text = pdf(raw); sites,grand = text.split('Grand Totals',1)
        values = collections.defaultdict(int)
        for line in sites.splitlines():
            m = re.match(r'^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d\d/\d\d/\d\d)\s+(.+)',line)
            if m:
                date = dt.datetime.strptime(m[1],'%m/%d/%y').date()
                if re.fullmatch(r'[\d, \t]+',m[2]): values[date] += sum(int(n.replace(',','')) for n in m[2].split())
        published={dt.datetime.strptime(d,'%m/%d/%y').date():int(n.replace(',','')) for d,n in re.findall(r'^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d\d/\d\d/\d\d)\s+([\d,]+)\s*$',grand.split('TOTALS BY JURISDICTION')[0],re.M)}
        for d,n in published.items(): eq(values[d],n,'Fort Bend site sums vs grand totals')
        values=sorted(published.items())
        return {str(d):(n,sum(x[1] for x in values[:i+1])) for i,(d,n) in enumerate(values)}, len(values)
    raise AssertionError(f'Unrecognized native control {county}')

def historical_equal_total_conflict():
    """Pinned anonymous publisher aggregates prove equality cannot certify zeros."""
    known_zip='b070ed9b8064425482f7fc9cee62ac801d2c3fd913a4376ae60fb4b8eaac7d49'
    known_sos='5974b86a73ca7613967018faa4e9cb0bf52fadf957b2dd4141ef3eb4631adc15'
    history=json.loads((ROOT/'dashboard/data/history.json').read_text())['counties']
    native=next(row for row in history['harris']['sources'] if row['date']=='2024-10-27' and not row['cumulative'])
    alternate=json.loads((PROJECT/'sources/precinct-expansion/discovery/harris-sos-2024-series.json').read_text())
    sos=next(row for row in alternate if row['date']=='2024-10-27')
    eq(native['sha256'],known_zip,'known native Harris immutable archive provenance')
    eq(sos['sha256'],known_sos,'known alternative SOS immutable roster provenance')
    eq(sum(native['counts'].values()),43535,'known native Harris Day 7 county total')
    eq(sum(sos['counts'].values()),43535,'known SOS Harris Day 7 county total')
    eq(native['counts'].get('UNASSIGNED',0),0,'known conflict has no unassigned votes')
    check('934' not in native['counts'],'known native Harris Day 7 precinct934 absent')
    eq(native['counts']['970'],5,'known native Harris Day 7 precinct970 explicit')
    eq(sos['counts']['934'],1,'known SOS Harris Day 7 precinct934 positive')
    refs=json.loads((ROOT/'dashboard/data/reference.json').read_text())
    harris=next(row for row in refs if row['id']=='harris')
    check(any(set(g['old'])=={'934','970'} and g['new']==['934'] for g in harris['groups']),
          'known equal-total conflict belongs to a live mixed historical geography')
    return {'date':'2024-10-27','native_zip_sha256':known_zip,'alternative_sos_sha256':known_sos,
            'county_total_both_sources':43535,'unassigned_native':0,'native934':None,'native970':5,'sos934':1,
            'policy':'Retain every explicit count; this disputed immutable archive cannot certify missing-precinct zeros. No alternative counts are merged.'}

def main():
    data = json.loads((ROOT/'dashboard/data/statewide.json').read_text())
    controls = json.loads((ROOT/'dashboard/data/completeness.json').read_text())['controls']
    raw_by_hash = {}; sources = {}; identities = {}; native = {}; anomalies=[]
    for year in (2024,2026):
        for p in sorted((ROOT/f'dashboard/data/statewide-cache/{year}').glob('????-??-??.json')):
            cache=json.loads(p.read_text()); src=cache['source']; ext='html' if year==2024 else 'json'
            rawpath=p.parent/f"{cache['date']}.{src['sha256']}.response.{ext}"
            raw=rawpath.read_bytes(); eq(hashlib.sha256(raw).hexdigest(),src['sha256'],'immutable source SHA')
            raw_by_hash[src['sha256']]=raw
            if year==2026:
                body=json.loads(raw); eq(body['early_voting_date'],cache['date'],'current publisher date');eq(body['election_id'],53815,'current election')
                rows={r['id']:{'name':r['name'],'votes':count(r['in_person_votes_on_date']),'cumulative':count(r['total_in_person_votes_for_election']),'mail_cumulative':count(r['total_mail_votes_for_election']),'registered':count(r['registered_voters'])} for r in body['turnout_by_county']}
            else:
                table=Table();table.feed(raw.decode()); rows={}
                h=next(r for r in table.rows if r and r[0]=='County');eq(h[5:7],['Cumulative By Mail Voters','Cumulative In-Person And Mail Voters'],'historical mail headers')
                names={canonical(r['name']):r['state_id'] for r in cache['rows']}
                for r in table.rows:
                    if len(r)==9 and canonical(r[0]) in names:
                        rows[names[canonical(r[0])]]={'name':r[0].upper(),'votes':count(r[2]),'cumulative':count(r[3]),'mail_cumulative':count(r[5]),'registered':count(r[1])}
                        eq(count(r[6]),count(r[3])+count(r[5]),'historical published combined')
                totals=next(r for r in table.rows if r and r[0]=='TOTAL')
                for f,col in [('registered',1),('votes',2),('cumulative',3),('mail_cumulative',5)]:eq(sum(r[f] for r in rows.values()),count(totals[col]),'historical statewide sum '+f)
            eq(len(rows),254,'official county universe');eq(len(cache['rows']),254,'cache county universe')
            for r in cache['rows']:
                expected=rows[r['state_id']]
                for f in ['votes','cumulative','registered','mail_cumulative']:eq(r[f],expected[f],'cache transforms '+f)
                check(r['votes']<=r['cumulative']<=r['registered'],'IP physical bounds')
                identities[r['state_id']]=canonical(r['name'])
            native[year,cache['date']]=rows;sources[year,cache['date']]=src
    # Closed historical controls may be independently superseded by a county report.
    parsed={};native_summaries=[]
    for c in controls:
        if c['sha256'] in raw_by_hash:
            src=sources[c['year'],c['date']]
            eq(c['sha256'],src['sha256'],'SOS control provenance')
            row=next(r for k,r in native[c['year'],c['date']].items() if identities[k]==c['county'])
            eq((c['daily'],c['cumulative']),(row['votes'],row['cumulative']),'historical SOS control independently parsed')
        else:
            key=c['county'],c['year'],c['sha256']
            if key not in parsed:
                matches=list((ROOT/'sources/completeness/raw').glob(c['sha256']+'.*'))
                if not matches: matches=list((PROJECT/'sources/completeness/raw').glob(c['sha256']+'.*'))
                if not matches and c['county']=='dallas' and c['year']==2024:matches=[PROJECT/'sources/refresh-2026-10-23/county-a/dallas-2024-location-totals.xlsx']
                eq(len(matches),1,'unique native immutable control source')
                raw=matches[0].read_bytes();eq(hashlib.sha256(raw).hexdigest(),c['sha256'],'native control hash')
                values,sites=native_control(c['county'],c['year'],raw); parsed[key]=values
                native_summaries.append({'county':c['county'],'year':c['year'],'sha256':c['sha256'],'site_or_date_rows':sites})
            eq((c['daily'],c['cumulative']),parsed[key][c['date']],'native independent control totals')
        check(c['year']!=2026 or c['date']<=data['through'],'no active or future certified control')
    for year in (2024,2026):
        previous=None
        for y,date in sorted(k for k in native if k[0]==year):
            rows=native[y,date]
            if previous:
                for ident,row in rows.items():
                    old=previous[ident]
                    if row['mail_cumulative']<old['mail_cumulative']:
                        anomalies.append({'type':'mail_downward_revision','county':identities[ident],'year':year,'date':date,'previous':old['mail_cumulative'],'current':row['mail_cumulative'],'action':'negative daily delta must be unavailable; cumulative is a publisher revision, not a reconstructed estimate'})
                    eq(row['cumulative']-old['cumulative'],row['votes'],'official daily IP matches cumulative delta')
            previous=rows
    stale_ip=[]
    zero_mail=[]
    refs=json.loads((ROOT/'dashboard/data/county-reference.json').read_text())['counties']
    def partisan_band(ident):
        r=refs[ident]; h,t=r['harris'],r['trump']
        if h==t: return 'Tied'
        margin=100*abs(h-t)/(h+t)
        band='30+' if margin>=30 else '15–30' if margin>=15 else '0–15'
        return ('Harris ' if h>t else 'Trump ')+band
    prev=None
    for y,date in sorted(k for k in native if k[0]==2026):
        rows=native[y,date]
        for ident,row in rows.items():
            county=identities[ident]
            if row['mail_cumulative']==0:
                zero_mail.append({'county':county,'date':date,'day':(dt.date.fromisoformat(date)-dt.date(2026,10,19)).days+1,'partisan_margin_band':partisan_band(county),'in_person_cumulative':row['cumulative']})
            if prev and row['votes']==0 and row['cumulative']>0:
                eq(row['cumulative'],prev[ident]['cumulative'],'unconfirmed zero IP repeated prior cumulative')
                stale_ip.append({'county':county,'date':date,'partisan_margin_band':partisan_band(county),'current_cumulative':row['cumulative'],'previous_cumulative':prev[ident]['cumulative'],'independent_current_control':any(c['county']==county and c['date']==date and c['year']==2026 for c in controls)})
        prev=rows
    version_changes=[]
    for y,date in sorted(native):
        if y!=2026:continue
        variants=[]
        for p in (ROOT/'dashboard/data/statewide-cache/2026').glob(date+'.*.response.json'):
            body=json.loads(p.read_text());variants.append((p.name,{r['id']:r['total_mail_votes_for_election'] for r in body['turnout_by_county']}))
        for ident in identities:
            values={v[1][ident] for v in variants}
            if len(values)>1:version_changes.append({'county':identities[ident],'date':date,'retained_mail_values':sorted(values)})
    known_conflict=historical_equal_total_conflict()
    report={'known_historical_equal_total_conflict':known_conflict,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'assertions':CHECKS,'official_reports':len(native),'county_report_cells':len(native)*254,'independently_checked_controls':len(controls),'native_controls':native_summaries,'mail_decreases':anomalies,'same_date_mail_revisions':version_changes,'unconfirmed_zero_mail_cells':zero_mail,'unconfirmed_zero_ip_repeated_cumulative':stale_ip,'mail_zero_current_cells':sum(r['mail_cumulative']==0 for (y,d),rows in native.items() if y==2026 for r in rows.values()),'limits':['Official SOS mail zeros have no per-county completion flag. Literal zero alone does not establish independent completion.','A publisher downward cumulative revision is not automatically an error; no carry-forward or maximum has been invented.','This offline source audit does not verify voter-file identity deduplication or precinct boundary equivalence.']}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['assertions','official_reports','county_report_cells','independently_checked_controls','mail_zero_current_cells']}))

if __name__=='__main__': main()

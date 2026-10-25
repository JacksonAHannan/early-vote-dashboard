"""Independent audit of fixed-cohort daily bucket counts and calendar gaps."""
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
from datetime import date,timedelta,datetime
import json,os
ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741')
def get(path):
 with urlopen(BASE+path) as response:return json.load(response)
snapshot=get('/api/data')
history=json.loads((ROOT/'data/history.json').read_text()) if (ROOT/'data/history.json').exists() else {'counties':{}}
classes={'partisan':None,'demographic':get('/api/demographics'),'primary':get('/api/primary')}
observed=snapshot['days']
def plus(a,b):
 out=a.copy()
 for k,v in b.items():out[k]=out.get(k,0)+v
 return out
def resolve(sources,year):
 result=[];previous={};issues=[]
 for day in range(1,13):
  if year==2026 and day>observed:result.append((None,None));continue
  stamp=(date(year,10,19 if year==2026 else 21)+timedelta(days=day-1)).isoformat()
  daily=sources.get((stamp,False));direct=sources.get((stamp,True))
  if daily is None and direct is not None and previous is not None:
   delta={k:direct.get(k,0)-previous.get(k,0) for k in direct.keys()|previous.keys()}
   if min(delta.values(),default=0)<0:issues.append('negative')
   else:daily={k:v for k,v in delta.items() if v}
  summed=plus(previous,daily) if daily is not None and previous is not None else None
  if direct is not None and summed is not None and direct!=summed:issues.append('conflict')
  cumulative=direct if direct is not None else summed
  previous=cumulative;result.append((daily,cumulative))
 return result,issues
resolved={}
for c in snapshot['counties']:
 sources={};newest={}
 for source in history.get('counties',{}).get(c['id'],{}).get('sources',[])+c['sources']:
  key=(source['date'],source.get('cumulative',False));stamp=datetime.fromisoformat(source['retrieved_at'].replace('Z','+00:00'))
  if key not in newest or stamp>=newest[key]:sources[key]=source['counts'];newest[key]=stamp
 old,oi=resolve(sources,2024);new,ni=resolve(sources,2026)
 resolved[c['id']]=(old,new,oi+ni)
def classify(g,kind,classification,metric,county):
 if kind=='partisan':return g['bucket']
 m=next(m for m in classification['metrics'] if m['id']==metric);p=classification['counties'].get(county,{}).get('precincts',{})
 n=d=0
 for precinct in g['new']:
  counts=p.get(precinct,{}).get('counts',{});num=counts.get(m['numerator']);den=counts.get(m['denominator'])
  if num is None or den is None or not 0<=num<=den:return None
  n+=num;d+=den
 if d<=0:return None
 share=100*n/d
 return sum(share>=cut for cut in m['cuts'])
checks=views=0
for kind,classification in classes.items():
 metrics=['partisan'] if classification is None else [m['id'] for m in classification['metrics']]
 for metric in metrics:
  for cohort in ['matched','unchanged']:
   for scope in ['all']+[c['id'] for c in snapshot['counties']]:
    view=get('/api/trends?'+urlencode({'view':kind,'metric':metric,'cohort':cohort,'county':scope}));selected=[]
    for c in snapshot['counties']:
     if scope!='all' and c['id']!=scope:continue
     latest=max(c['periods'],key=lambda p:p['day']) if c['periods'] else None
     groups=[]
     for g in latest['groups'] if latest else []:
      if cohort=='unchanged' and not g['unchanged']:continue
      b=classify(g,kind,classification,metric,c['id'])
      if b is not None:groups.append((g,b))
     old,new,issues=resolved[c['id']]
     included=bool(groups) and (scope!='all' or not issues and all(old[i][0] is not None and new[i][0] is not None for i in range(observed)))
     if included:selected.append((c['id'],groups,old,new))
    assert view['coverage']['included_counties']==[c[0] for c in selected],(kind,metric,scope,'coverage')
    for index,b in enumerate(view['buckets']+[view['totals']]):
     target=None if index==len(view['buckets']) else index
     assert b['groups']==sum(sum(target is None or bucket==target for _,bucket in groups) for _,groups,_,_ in selected)
     assert len(b['days'])==12
     for i,row in enumerate(b['days']):
      assert row['day']==i+1
      for year,position in [(2024,2),(2026,3)]:
       for measure,field in [('daily',0),('cumulative',1)]:
        key=f'{measure}_{year}';value=None
        if selected and (year==2024 or i<observed) and all(c[position][i][field] is not None for c in selected):
         value=sum(sum(sum(c[position][i][field].get(p,0) for p in g['old' if year==2024 else 'new']) for g,bucket in c[1] if target is None or bucket==target) for c in selected)
        assert row[key]==value,(kind,metric,cohort,scope,index,i+1,key,row[key],value)
        checks+=1
    views+=1
report={'status':'passed','views':views,'daily_cumulative_cells':checks,'checks':['independent fixed cohort','summed native counts classify groups','all twelve aligned days','future 2026 null','missing reports stay null','adjacent cumulative differences','classification and cohort coverage','total/bucket group counts']}
out=ROOT.parent/'sources/daily-tracking';out.mkdir(exist_ok=True,parents=True);(out/'integration-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

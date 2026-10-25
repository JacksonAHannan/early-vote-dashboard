#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyshp>=2.3,<3", "shapely>=2.1,<3", "pyproj>=3.7,<4", "numpy>=2,<3"]
# ///
"""Build Census-population-weighted place types without allocating election votes.

Run with --source-root pointing at the retained source project, or acquire the
same public files under sources/ first. --offline never makes network requests.
"""
import argparse,collections,csv,hashlib,io,json,time,zipfile,platform
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import numpy as np
import pyproj,shapefile,shapely
from shapely.geometry import shape

ROOT=Path(__file__).resolve().parents[2]
LOCALE='https://nces.ed.gov/opengis/rest/services/Locale_Boundaries/EDGE_LOCALE25_US/MapServer/1'
BLOCKS='https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/Tracts_Blocks/MapServer/2'
METHOD=('Dashboard place types derived from NCES 2025 Census-based locales and 2020 Census PL 94-171 voting-age population. '
 'Urban = NCES city (11–13); Suburban = suburb (21–23); Exurban = town-fringe (31) or rural-fringe (41); '
 'Rural = town-distant/remote (32–33) or rural-distant/remote (42–43). '
 'A group or county needs more than 50% of its 2020 age-18+ residents in one geographic type. '
 'Rural Anglo additionally requires more than 50% White alone non-Hispanic residents age 18+; '
 'Rural Hispanic requires more than 50% Hispanic residents age 18+. '
 'Otherwise Other / unclassified, including zero-population areas. Unlocated population stays in the denominator; classify only when a known geographic count still exceeds half of all age-18+ residents. '
 'Census blocks are assigned whole by their internal point, following the existing precinct Census method. '
 'Place types describe geographic populations, not the ethnicity or party of voters. No election votes are allocated.')
KEYS=['city_vap','suburb_vap','fringe_vap','rural_vap','unclassified_vap']

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',type=Path,default=ROOT);p.add_argument('--output',type=Path,default=ROOT/'dashboard/places/texas.json');p.add_argument('--offline',action='store_true');args=p.parse_args()
 src=args.source_root.resolve();raw=src/'sources/place-types/raw';raw.mkdir(parents=True,exist_ok=True)
 census=json.loads((ROOT/'dashboard/data/demographics.json').read_text());counties=json.loads((ROOT/'dashboard/data/county-reference.json').read_text())['counties']
 inputs={}
 def provenance(path,url):
  inputs[str(path.relative_to(src))]={'path':str(path.relative_to(src)),'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
 def fetch(path,url):
  if not path.exists():
   if args.offline:raise FileNotFoundError(path)
   for attempt in range(3):
    try:
     with urlopen(url,timeout=150) as r:data=r.read()
     tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_bytes(data);tmp.replace(path);break
    except Exception:
     if attempt==2:raise
     time.sleep(1+attempt)
  provenance(path,url);return path
 localeurl=LOCALE+'/query?'+urlencode({'where':"STATEFP='48'",'outFields':'OBJECTID,LOCALE,STATEFP,GEO_YEAR','returnGeometry':'true','outSR':'4326','f':'geojson'})
 localepath=fetch(raw/'texas-locales-2025.geojson',localeurl)
 locale=json.loads(localepath.read_text());assert len(locale['features'])==12 and not locale.get('exceededTransferLimit');assert {f['properties']['STATEFP'] for f in locale['features']}=={'48'} and {f['properties']['GEO_YEAR'] for f in locale['features']}=={'2025'}
 geos=np.array([shape(f['geometry']) for f in locale['features']],dtype=object);codes=[int(f['properties']['LOCALE']) for f in locale['features']];assert set(codes)=={11,12,13,21,22,23,31,32,33,41,42,43};repairs=[{'locale':code,'reason':shapely.is_valid_reason(g)} for code,g in zip(codes,geos) if not g.is_valid];geos=shapely.make_valid(geos);assert all(shapely.is_valid(geos));shapely.prepare(geos)
 pointpaths={}
 def point_file(item):
  id,c=item;params={'where':f"STATE='48' AND COUNTY='{c['fips'][2:]}'",'outFields':'GEOID,POP100,HU100,INTPTLON,INTPTLAT','returnGeometry':'false','f':'json'};url=BLOCKS+'/query?'+urlencode(params)
  candidates=list(src.glob(f'sources/**/raw/{id}-block-points.json'));path=candidates[0] if candidates else raw/f'{id}-block-points.json';fetch(path,url);return id,path
 with ThreadPoolExecutor(max_workers=3) as pool:pointpaths=dict(pool.map(point_file,counties.items()))
 blockzip=src/'sources/census-atlas/raw/blocks_pop.zip';assert blockzip.exists()
 provenance(blockzip,'https://data.capitol.texas.gov/dataset/2b59f5ce-5fa4-4040-a550-caffbe8986c4/resource/33ed77c5-951b-4a88-9de7-9c90c4ba50db/download/blocks_pop.zip')
 with zipfile.ZipFile(blockzip) as z:
  with io.TextIOWrapper(z.open('Blocks_Pop.txt'),encoding='utf-8-sig') as f:blocks={r['SCTBKEY']:(int(r['total']),int(r['vap']),int(r['anglovap']),int(r['hispvap'])) for r in csv.DictReader(f)}
 boundary=src/'sources/boundaries/26p/Precincts26P.shp';fips_to_id={int(c['fips'][2:]):id for id,c in counties.items()};native=collections.defaultdict(dict)
 for rec in shapefile.Reader(str(boundary)).iterShapeRecords():
  r=rec.record.as_dict();id=fips_to_id.get(int(r['CNTY']))
  if id not in census['counties']:continue
  key=str(r['PREC']).strip().upper().lstrip('0') or '0';g=shape(rec.shape.__geo_interface__);native[id][key]=shapely.make_valid(g) if not g.is_valid else g
 crs=pyproj.CRS.from_wkt(boundary.with_suffix('.prj').read_text());project=pyproj.Transformer.from_crs(4326,crs,always_xy=True)
 for ext in ['.shp','.shx','.dbf','.prj']:provenance(boundary.with_suffix(ext),'https://data.capitol.texas.gov/dataset/d04c72b9-16c4-4ab2-8c6d-c666d41e04b7/resource/33ec5b30-ee4d-424f-9769-57b87cb5e311/download/precincts26p.zip')
 result={'schema_version':1,'metrics':[{'id':'place_type','label':'Place type','unit':'category','numerator':'city_vap','denominator':'vap','cuts':[],'source':'NCES 2025 locales · 2020 Census','vintage':'2020 Census / NCES 2025 / 2026 precincts'}],'counties':{},'sources':[],'method':METHOD,'geometry_repairs':repairs,'geometry_repair_method':'GEOS make_valid linework, no snapping or vote allocation','versions':{'python':platform.python_version(),'shapely':shapely.__version__,'geos':shapely.geos_version_string,'pyproj':pyproj.__version__,'numpy':np.__version__}};audit={}
 for id,c in counties.items():
  points=json.loads(pointpaths[id].read_text());assert 'error' not in points and not points.get('exceededTransferLimit'),id
  attrs=[f['attributes'] for f in points['features']];assert len({p['GEOID'] for p in attrs})==len(attrs)
  x=np.array([float(p['INTPTLON']) for p in attrs]);y=np.array([float(p['INTPTLAT']) for p in attrs]);xy=shapely.points(x,y);assignment=np.full(len(attrs),-1);matches=np.zeros(len(attrs),dtype=int)
  for g,code in zip(geos,codes):
   hit=shapely.intersects(g,xy);matches+=hit;assignment[hit]=code
  assignment[matches!=1]=-1
  def empty():return {k:0 for k in ['population','vap','white_nh_vap','hispanic_vap',*KEYS]}
  countycounts=empty();precincts={p:{'counts':empty()} for p in census['counties'].get(id,{}).get('precincts',{})};join={}
  if id in native:
   ids=list(native[id]);polys=np.array(list(native[id].values()),dtype=object);tree=shapely.STRtree(polys);xx,yy=project.transform(x,y);pairs=tree.query(shapely.points(xx,yy),predicate='within')
   assert len(set(pairs[0]))==len(pairs[0]),('multiple precinct assignment',id);join={int(i):ids[int(j)] for i,j in zip(*pairs)}
  unmatched_vap=0
  for i,p in enumerate(attrs):
   pop,vap,white,hisp=blocks[p['GEOID']];assert pop==p['POP100'];code=assignment[i];key='city_vap' if 11<=code<=13 else 'suburb_vap' if 21<=code<=23 else 'fringe_vap' if code in (31,41) else 'rural_vap' if code in (32,33,42,43) else 'unclassified_vap'
   vals={'population':pop,'vap':vap,'white_nh_vap':white,'hispanic_vap':hisp,key:vap}
   for k,v in vals.items():countycounts[k]+=v
   target=join.get(i)
   if target in precincts:
    for k,v in vals.items():precincts[target]['counts'][k]+=v
   elif id in native:unmatched_vap+=vap
  for k in ['population','vap','white_nh_vap','hispanic_vap']:assert countycounts[k]==c['counts'][k],(id,k,'county control')
  for key,prec in precincts.items():
   for k in ['population','vap','white_nh_vap','hispanic_vap']:assert prec['counts'][k]==census['counties'][id]['precincts'][key]['counts'][k],(id,key,k,'existing Census assignment drift')
   assert sum(prec['counts'][k] for k in KEYS)==prec['counts']['vap']
  assert sum(countycounts[k] for k in KEYS)==countycounts['vap']
  result['counties'][id]={'precincts':precincts,'assigned_totals':countycounts,'coverage':{'unmatched_precinct_vap':unmatched_vap,'unclassified_locale_vap':countycounts['unclassified_vap']}}
  audit[id]={'blocks':len(attrs),'precincts':len(precincts),'vap':countycounts['vap'],'unclassified_locale_vap':countycounts['unclassified_vap'],'unmatched_precinct_vap':unmatched_vap};print(id,audit[id],flush=True)
 result['sources']=[inputs[k] for k in sorted(inputs)];args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,separators=(',',':'))+'\n');(raw.parent/'audit.json').write_text(json.dumps(audit,indent=2)+'\n');print('Saved',args.output,flush=True)
if __name__=='__main__':main()

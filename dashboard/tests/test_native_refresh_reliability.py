"""Successive official publications; synthetic identities only."""
from datetime import date, datetime, timezone
import base64, importlib.util, io, json, tempfile, unittest
from pathlib import Path
from unittest import mock

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
def load(name):
 spec=importlib.util.spec_from_file_location(name,SCRIPTS/(name+'.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class RefreshReliability(unittest.TestCase):
 def test_collin_new_workbook_omits_only_optional_presentation_column(self):
  m=load('collect_collin')
  header={key:value for key,value in m.HEADER.items() if key!='I'}
  row={'A':'SYNTHETIC','B':'TEST','C':'0000000001','D':'1','E':'46322.448611111111','F':'TEST','G':'Regular','H':'Early Voting'}
  result=m.aggregate(iter([header,row]),date(2026,10,27),'https://official.example/x','a'*64,'test')
  self.assertEqual(result[0]['counts'],{'1':1})
  self.assertEqual(result[0]['date'],'2026-10-27')
  with self.assertRaises(ValueError):m.aggregate(iter([{k:v for k,v in header.items() if k!='C'},row]),date(2026,10,27),'x','a'*64,'test')
 def test_panola_next_morning_export_keeps_exact_prior_voting_date(self):
  m=load('collect_panola')
  doc='HPanola 183VRH 20261028074416\nDPanola 1830000000001 53815 SYNTHETIC\nEV EV 20261027 08:00 15096\n2 P8\nTPanola 1831\n'
  frozen=mock.Mock(wraps=datetime);frozen.now.side_effect=lambda tz:datetime(2026,10,28,15,tzinfo=timezone.utc).astimezone(tz)
  with mock.patch.object(m,'datetime',frozen):
   self.assertEqual(m.parse_panola(doc,date(2026,10,27)),[('0000000001','P8')])
   with self.assertRaises(ValueError):m.parse_panola(doc.replace('20261027 08:00','20261028 08:00'),date(2026,10,27))
 def test_collin_successive_editions_discover_new_link_and_replaced_content(self):
  m=load('collect_collin');edition=26;revision=1
  def download(url):
   if url==m.LANDING:return f'<a href="/early-voters-through-october-{edition}-2026.xlsx">latest</a>'.encode()
   return f'{edition}:{revision}'.encode()
  def rows(raw):
   day,rev=map(int,raw.decode().split(':'))
   return iter([m.HEADER,{'A':'SYNTHETIC','B':'TEST','C':'0000000001','D':str(rev),'E':f'10/{day}/2026','F':'TEST','G':'Regular','H':'Early Voting','I':''}])
  frozen=mock.Mock(wraps=datetime);frozen.now.side_effect=lambda tz:datetime(2026,10,28,15,tzinfo=timezone.utc).astimezone(tz)
  with mock.patch.object(m,'xlsx_rows',side_effect=rows),mock.patch.object(m,'datetime',frozen):
   first=m.collect(date(2026,10,27),download)[0]
   edition=27;second=m.collect(date(2026,10,27),download)[0]
   revision=2;third=m.collect(date(2026,10,27),download)[0]
  self.assertEqual([r['date'] for r in [first,second,third]],['2026-10-26','2026-10-27','2026-10-27'])
  self.assertEqual(len({r['sha256'] for r in [first,second,third]}),3)
  self.assertEqual(third['counts'],{'2':1})
 def test_later_publication_can_revoke_previously_unique_alias(self):
  m=load('collect_county_native')
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'dashboard/data').mkdir(parents=True)
   (root/'dashboard/data/reference.json').write_text(json.dumps([{'id':'washington','groups':[{'new':['101','102']}]}]))
   folder='/upload/page/10698/2026/2026 11 03/'
   page=''.join(f'<a href="{folder}10{d}26.xlsx">October {d}</a>' for d in [21,22])
   def downloader(url):
    if url==m.LANDINGS['washington']:return page.encode()
    if 'getFileByFormat' in url:
     target='101' if '10/21/2026' in url else '102'
     identity='0000000001' if target=='101' else '0000000002'
     csv=f'ID_VOTER,VOTING_METHOD,PRECINCT\n{identity},IN-PERSON,{target}\n'
     return json.dumps({'upload':base64.b64encode(csv.encode()).decode()}).encode()
    return url.encode()
   def parse(raw,when):return [('0000000001' if when.day==21 else '0000000002','S 1.1')]
   with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'parse_washington',side_effect=parse),mock.patch('sys.stderr',new_callable=io.StringIO):
    result=m.collect('washington',date(2026,10,22),downloader)
   self.assertTrue(all(not any(p in r['counts'] for p in ['101','102']) for r in result),result)
   self.assertTrue(all(set(r['unavailable_precincts'])=={'101','102'} for r in result))
 def test_foreign_target_is_retained_in_alias_evidence(self):
  m=load('collect_county_native')
  text='ID_VOTER,VOTING_METHOD,PRECINCT\n0000000001,IN-PERSON,FOREIGN\n'
  aliases,proof,_=m.derive_aliases([('0000000001','S1')],json.dumps({'upload':base64.b64encode(text.encode()).decode()}).encode(),{'101'})
  self.assertEqual(aliases,{})
  self.assertEqual(proof,[{'native':'S1','precinct':'FOREIGN','matched_rows':1}])
 def test_collin_latest_failure_does_not_discard_prior_completed_publication(self):
  m=load('collect_collin')
  def download(url):
   if url==m.LANDING:return b'<a href="/early-voters-through-october-26-2026.xlsx">26</a><a href="/early-voters-through-october-27-2026.xlsx">27</a>'
   if '-27-' in url:raise TimeoutError('synthetic transient failure')
   return b'synthetic older workbook'
  row={'A':'SYNTHETIC','B':'TEST','C':'0000000001','D':'1','E':'10/26/2026','F':'TEST','G':'Regular','H':'Early Voting','I':''}
  with mock.patch.object(m,'xlsx_rows',return_value=iter([m.HEADER,row])),mock.patch('sys.stderr',new_callable=io.StringIO):
   result=m.collect(date(2026,10,27),download)
  self.assertEqual(result[0]['date'],'2026-10-26')
  self.assertIn('-26-',result[0]['source'])
 def test_panola_current_day_never_treated_as_completed(self):
  m=load('collect_panola')
  now=datetime(2026,10,28,12,tzinfo=timezone.utc)
  frozen=mock.Mock(wraps=datetime);frozen.now.side_effect=lambda tz:now.astimezone(tz)
  page='Early Voting Turnout for November 3rd 2026 Uniform Election<a href="/DocumentCenter/View/1932">Day 9 (PDF)</a><a href="/DocumentCenter/View/1933">Day 10 (PDF)</a>'
  with mock.patch.object(m,'datetime',frozen):found=m.discover(page,date(2026,10,30))
  self.assertEqual(set(found),{date(2026,10,27)})

if __name__=='__main__':unittest.main()

"""Synthetic contract checks: source identity and explicit zero proofs only."""
import importlib.util
from pathlib import Path
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'

def load(name):
 spec=importlib.util.spec_from_file_location(name,SCRIPTS/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
bexar=load('collect_bexar_native_recovery');tarrant=load('certify_tarrant_2024_zeros');fortbend=load('audit_fortbend_native_returns')

class BexarProofs(unittest.TestCase):
 def test_blank_identity_marks_only_residence_label(self):
  text='Name VUID Polling Place Precinct\nSYNTHETIC PERSON 1000000001 CENTER-EV P 1001\nSYNTHETIC MISSING       CENTER-EV S 1002.01\n'
  ids,repeats,blanks=bexar.parse_pdf_text(text)
  self.assertEqual(ids,{'1000000001':'P 1001'});self.assertEqual(repeats,0);self.assertEqual(blanks,{'S 1002.01':1})
 def test_unparsed_voter_shaped_row_rejected(self):
  with self.assertRaisesRegex(ValueError,'unparsed voter'):
   bexar.parse_pdf_text('Name VUID Polling Place Precinct\nSYNTHETIC PERSON 1000000001 CENTER-EV WRONG\n')
 def test_duplicate_different_record_rejected(self):
  ids,repeats,invalid=bexar.parse_pdf_text('Name VUID Polling Place Precinct\nSYNTHETIC PERSON 1000000001 CENTER-EV P 1001\nSYNTHETIC PERSON 1000000001 OTHER-EV P 1001\nSYNTHETIC OTHER 1000000002 CENTER-EV P 2001\n')
  self.assertEqual(ids,{'1000000002':'P 2001'});self.assertEqual(invalid,{'P 1001':2})
 def test_proof_is_unique_across_dates_and_only_repairs_unknown_sos_labels(self):
  results=[dict(when='2026-10-19',source='county',sha256='a'*64,state_source='state',state_sha256='b'*64,identities={'a':'S 1001.01','b':'S 1001.01','c':'P 2001','d':'P 3001'},state={'a':'1001','b':'11','c':'2001','d':'1001'},blank_labels={},repeats=0,pages=1)]
  metadata={'2026-10-19':{'DisplayName':'synthetic official title'}}
  bundle=bexar.aggregate(results,{'1001','2001','3001'},metadata)
  repaired=bundle['repaired_state_observations'][0]['counts']
  self.assertEqual(repaired,{'1001':3,'2001':1});self.assertEqual(bundle['days'][0]['reassignments'],[{'source_label':'11','county_label':'S 1001.01','native_precinct':'1001','votes':1}])
  # A label with two mapped targets cannot justify any reassignment.
  results[0]['identities']['c']='S 1001.01'
  bundle=bexar.aggregate(results,{'1001','2001','3001'},metadata)
  self.assertIsNone(bundle['aliases']['S 1001.01']['target'])
  self.assertEqual(bundle['repaired_state_observations'][0]['counts']['11'],1)
 def test_quarantine_does_not_remove_unrelated_cells(self):
  results=[dict(when='2026-10-19',source='county',sha256='a'*64,state_source='state',state_sha256='b'*64,identities={'a':'P 1001','b':'P 2001'},state={'a':'1001','b':'2001'},blank_labels={'P 1001':1},repeats=0,pages=1)]
  bundle=bexar.aggregate(results,{'1001','2001'},{'2026-10-19':{'DisplayName':'test'}})
  self.assertEqual(bundle['observations'][0]['counts'],{'2001':1});self.assertEqual(bundle['observations'][0]['unavailable_precincts'],['1001'])

class TarrantProofs(unittest.TestCase):
 def report(self):
  return ('Official Results\nTarrant County\nJoint General and Special Election\n11/5/2024\n'
          'Precincts Reporting\n844 of 844 = 100.00%\n828544 of 1299023 = 63.78%\n'
          '1001 0 of 1 registered voters = 0.00%\n1002 828,544 of 1,299,022 registered voters = 63.78%\n')
 def test_only_explicit_final_zero_is_certified(self):
  self.assertEqual(tarrant.parse_zero_precincts(self.report(),2),{'1001':{'ballots_cast':0,'registered_voters':1}})
 def test_positive_and_absent_precincts_not_certified(self):
  result=tarrant.parse_zero_precincts(self.report(),2);self.assertNotIn('1002',result);self.assertNotIn('1003',result)
 def test_nonfinal_wrong_election_and_control_failure_rejected(self):
  for text in [self.report().replace('Official Results','Unofficial Results'),self.report().replace('11/5/2024','11/3/2026'),self.report().replace('828,544','828,545')]:
   with self.assertRaises(ValueError):tarrant.parse_zero_precincts(text,2)
 def test_conflicting_repeated_precinct_header_rejected(self):
  with self.assertRaisesRegex(ValueError,'conflicting'):
   tarrant.parse_zero_precincts(self.report()+'1001 1 of 1 registered voters = 100.00%\n',2)

class FortBendProofs(unittest.TestCase):
 def canvass(self):
  heading='OFFICIAL RESULTS\nNovember 5, 2024\nFort Bend County Precinct Canvass Report\nPresident / Vice President\nREP Donald J.\nDEM Kamala\n175 of 175 Precincts Reporting\n'
  rows='\n'.join(f'{i} - 1   2 3 0 0 0 0 0 0 0 0 0 0 0 5' for i in range(1001,1176))
  return heading+rows+'\nTotals   350 525 0 0 0 0 0 0 0 0 0 0 0 875\n'
 def test_native_canvass_conserves_all_precincts(self):
  rows,totals=fortbend.parse_canvass(self.canvass());self.assertEqual(len(rows),175);self.assertEqual(rows['1001'],{'trump':2,'harris':3});self.assertEqual(totals,{'trump':350,'harris':525})
 def test_damaged_row_arithmetic_and_duplicate_identity_fail(self):
  for text in [self.canvass().replace('0 0 0 5','0 0 0 6',1),self.canvass().replace('1002 - 1','1001 - 1')]:
   with self.assertRaises(ValueError):fortbend.parse_canvass(text)
 def test_native_report_modes_sum_and_zero_vote_percentage_optional(self):
  heading='OFFICIAL RESULTS\nGeneral Election\nNovember 5, 2024\nFort Bend County Precint Reports\n'
  pages='\f'.join(f'{i} - 1\nPresident / Vice President\nREP Donald J. Trump / JD Vance   2 40.00% 1 0 1\nDEM Kamala Harris / Tim Walz   0 0 0 0\n' for i in range(1001,1176))
  rows=fortbend.parse_precinct_report(heading+pages);self.assertEqual(rows['1001'],{'trump':2,'harris':0})
  with self.assertRaisesRegex(ValueError,'conservation'):
   fortbend.parse_precinct_report(heading+pages.replace('2 40.00% 1 0 1','2 40.00% 1 1 1',1))

if __name__=='__main__':unittest.main()

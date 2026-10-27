#!/usr/bin/env python3
"""Native presidential join and source conservation without external data."""
import copy, importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('denton_presidential',ROOT/'sources/large-county-recovery/denton_presidential.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
TOTAL=[250521,191503,3100,3605,5,116,98,5,221,14,449188,3205,160,13643,370893,68017,452553,661361]

def fixture():
    header='Denton County Canvass Official Results 11/5/2024 11/16/2024 240 of 240 = 100.00% President/Vice President Donald J. Trump / JD Vance, REP Kamala D. Harris / Tim Walz, DEM Cast Votes Undervotes Overvotes Total Ballots Cast\n'
    rows=[]
    for i in range(240):rows.append(str(1000+i)+' '+' '.join(map(str,TOTAL if i==0 else [0]*18))+' 0.00%')
    rows.append('Totals '+' '.join(map(str,TOTAL))+' 68.43%')
    text=header+'\n'.join(rows)+'\nUnited States Senator'
    ref={'id':'denton','groups':[{'old':[str(1000+i)]} for i in range(240)],'presidential':{'1000':{'trump':250521,'harris':191503}}}
    return text,ref

class NativePresidential(unittest.TestCase):
    def test_exact_native_join_and_all_columns_conserve(self):
        s,r=fixture();x=m.parse_text(s,r);self.assertEqual(x['precincts'],240);self.assertEqual(x['additional_native_returns'],239);self.assertEqual(x['county_totals']['trump'],250521);self.assertEqual(x['presidential']['1001'],{'trump':0,'harris':0});self.assertEqual(len(x['zero_ballot_precincts']),239)
    def test_wrong_election_rejected(self):
        s,r=fixture()
        with self.assertRaisesRegex(ValueError,'scope'):m.parse_text(s.replace('11/5/2024','11/5/2026'),r)
    def test_incomplete_precinct_row_set_rejected(self):
        s,r=fixture();s='\n'.join(line for line in s.splitlines() if not line.startswith('1001 '))
        with self.assertRaisesRegex(ValueError,'exactly match'):m.parse_text(s,r)
    def test_extra_precinct_not_guessed(self):
        s,r=fixture();s=s.replace('1001 ','9999 ',1)
        with self.assertRaisesRegex(ValueError,'exactly match'):m.parse_text(s,r)
    def test_duplicate_normalized_id_rejected(self):
        s,r=fixture();s=s.replace('1001 ','001000 ',1)
        with self.assertRaisesRegex(ValueError,'Duplicate'):m.parse_text(s,r)
    def test_row_ballot_arithmetic_rejected(self):
        s,r=fixture();s=s.replace('250521 191503','250522 191503',1)
        with self.assertRaisesRegex(ValueError,'arithmetic'):m.parse_text(s,r)
    def test_all_numeric_columns_not_only_candidate_totals_checked(self):
        s,r=fixture();tot='Totals '+' '.join(map(str,TOTAL));changed=TOTAL.copy();changed[-1]+=1;s=s.replace(tot,'Totals '+' '.join(map(str,changed)))
        with self.assertRaisesRegex(ValueError,'all county'):m.parse_text(s,r)
    def test_existing_reference_conflict_cannot_be_silently_overwritten(self):
        s,r=fixture();r['presidential']['1000']['harris']-=1;before=copy.deepcopy(r)
        with self.assertRaisesRegex(ValueError,'conflicts'):m.parse_text(s,r)
        self.assertEqual(r,before)
    def test_wrong_county_rejected(self):
        s,r=fixture();r['id']='collin'
        with self.assertRaisesRegex(ValueError,'county reference'):m.parse_text(s,r)
    def test_independent_county_summary_agrees_by_method_and_total(self):
        s,r=fixture();result=m.parse_text(s,r)
        summary='Denton County Cumulative Official Results 11/5/2024 11/16/2024 President/Vice President\nDonald J. Trump / JD Vance REP 5827 43.00% 208947 56.72% 35747 53.14% 250521 55.77%\nKamala D. Harris / Tim Walz DEM 7588 56.00% 154463 41.93% 29452 43.78% 191503 42.63%\nUnited States Senator'
        self.assertEqual(m.validate_county_summary(summary,result)['sha256'],m.SUMMARY_SHA256)
    def test_independent_county_summary_disagreement_rejected(self):
        s,r=fixture();result=m.parse_text(s,r)
        summary='Denton County Cumulative Official Results 11/5/2024 11/16/2024 President/Vice President\nDonald J. Trump / JD Vance REP 5827 43.00% 208947 56.72% 35747 53.14% 250520 55.77%\nKamala D. Harris / Tim Walz DEM 7588 56.00% 154463 41.93% 29452 43.78% 191503 42.63%\nUnited States Senator'
        with self.assertRaisesRegex(ValueError,'totals differ'):m.validate_county_summary(summary,result)
    def test_repeated_total_rejected(self):
        s,r=fixture();line='Totals '+' '.join(map(str,TOTAL))+' 68.43%';s=s.replace(line,line+'\n'+line)
        with self.assertRaisesRegex(ValueError,'Duplicate county'):m.parse_text(s,r)

if __name__=='__main__':unittest.main()

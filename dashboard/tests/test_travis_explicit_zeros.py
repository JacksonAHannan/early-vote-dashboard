#!/usr/bin/env python3
"""Bounded literal-zero proof tests; no production/source network access."""
import importlib.util
from datetime import date, datetime
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('travis_zero_proof',ROOT/'sources/large-county-recovery/travis_zero_proof.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fixture(rows=None):
    rows=rows or [('100',10),('159',0)]
    headers=['Precinct','Reg. Voters','Early Vote','Election Day','Provisional Application','Turnout']
    table='NOVEMBER 3, 2026 JOINT GENERAL AND SPECIAL ELECTIONS<script>var lastRefreshed = 1793093035628.37;</script><table id="gridVerify"><thead><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'
    for p,n in rows:table+='<tr>'+''.join('<td>'+str(v)+'</td>' for v in [p,100,n,0,0,'10%'])+'</tr>'
    table+='</tbody></table>'
    graph="evData.push(['10/19/2026',10])"
    return table.encode(),graph.encode()

class ExplicitZeros(unittest.TestCase):
    def test_literal_zero_only_bounded_to_closed_cutoff(self):
        t,g=fixture();r=m.parse(t,g,date(2026,10,26));self.assertEqual(r['precincts'],['159']);self.assertEqual(r['through'],'2026-10-19');self.assertNotIn('128',r['precincts'])
    def test_missing_precinct_not_certified(self):
        t,g=fixture([('100',10)]);self.assertEqual(m.parse(t,g,date(2026,10,26))['precincts'],[])
    def test_any_prior_positive_rejects_zero(self):
        t,g=fixture()
        with self.assertRaisesRegex(ValueError,'conflicts'):m.parse(t,g,date(2026,10,26),[{'date':'2026-10-19','counts':{'159':1}}])
    def test_zero_after_cutoff_does_not_claim_day_after(self):
        t,g=fixture();r=m.parse(t,g,date(2026,10,26));self.assertEqual(r['through'],'2026-10-19')
    def test_mismatched_full_scope_rejected(self):
        t,g=fixture();g=g.replace(b',10]',b',11]')
        with self.assertRaisesRegex(ValueError,'reconcile'):m.parse(t,g,date(2026,10,26))
    def test_active_day_excluded(self):
        t,g=fixture();g+=b"evData.push(['10/27/2026',1])"
        with self.assertRaisesRegex(ValueError,'active'):m.parse(t,g,date(2026,10,26))
    def test_future_requested_cutoff_cannot_certify_active_day(self):
        t,g=fixture();g+=b"evData.push(['10/27/2026',1])"
        with self.assertRaisesRegex(ValueError,'active'):m.parse(t,g,date(2026,10,28))
    def test_other_method_header_rejected(self):
        t,g=fixture();t=t.replace(b'Early Vote',b'Total Ballots Cast')
        with self.assertRaisesRegex(ValueError,'scope'):m.parse(t,g,date(2026,10,26))
    def test_duplicate_normalized_precinct_rejected(self):
        t,g=fixture([('100',10),('159',0),('0159',0)])
        with self.assertRaisesRegex(ValueError,'Duplicate'):m.parse(t,g,date(2026,10,26))
    def test_daily_gap_rejected(self):
        t,g=fixture();g+=b"evData.push(['10/21/2026',1])"
        with self.assertRaisesRegex(ValueError,'gap'):m.parse(t,g,date(2026,10,26))

if __name__=='__main__':unittest.main()

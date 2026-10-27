import importlib.util
from datetime import date,datetime
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest import mock
import json,tempfile
from collections import Counter

spec=importlib.util.spec_from_file_location('anchor',Path(__file__).resolve().parents[1]/'scripts/collect_tarrant_anchor.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class TarrantAnchor(unittest.TestCase):
    def test_split_conflict_withholds_other_labels_feeding_any_possible_native_target(self):
        ids={'a':'100101','b':'100102','c':'100102','d':'100201','e':'100301','f':'100102'}
        sources=[{'identities':{'a':'1','b':'1','c':'2','d':'2','e':'3'}}]
        counts,bad,proof,withheld=m.aggregate(ids,{},sources,{'1','2','3'})
        self.assertEqual(counts,{'3':1,'UNRESOLVED 100102':1})
        self.assertEqual(bad,['1','2'])
        self.assertEqual(withheld,4)
        self.assertIsNone(proof['100102']['target'])
    def test_individual_identity_resolves_a_mixed_label_when_every_row_has_a_native_target(self):
        counts,bad,_,withheld=m.aggregate({'a':'100101','b':'100101'}, {},[{'identities':{'a':'1','b':'2'}}],{'1','2'})
        self.assertEqual(counts,{'1':1,'2':1});self.assertEqual(bad,[]);self.assertEqual(withheld,0)
    def test_unknown_row_in_a_mixed_label_still_withholds_every_possible_native_cell(self):
        counts,bad,_,withheld=m.aggregate({'a':'100101','b':'100101','c':'100101'}, {},[{'identities':{'a':'1','b':'2'}}],{'1','2'})
        self.assertEqual(counts,{'UNRESOLVED 100101':1});self.assertEqual(bad,['1','2']);self.assertEqual(withheld,2)
    def test_unique_label_fallback_applies_only_to_unmatched_individuals(self):
        counts,bad,proof,withheld=m.aggregate({'a':'100101','b':'100101'}, {},[{'identities':{'a':'1'}}],{'1'})
        self.assertEqual(counts,{'1':2});self.assertEqual(bad,[]);self.assertEqual(withheld,0)
        self.assertEqual(proof['100101']['directly_matched_native_rows'],{'1':1})
        self.assertEqual(proof['100101']['unmatched_identity_alias_rows'],1)
    def test_foreign_sos_target_participates_in_conflicts(self):
        counts,bad,_,_=m.aggregate({'a':'100101','b':'100101'}, {},[{'identities':{'a':'1','b':'FOREIGN'}}],{'1'})
        self.assertNotIn('1',counts);self.assertEqual(bad,['1'])
    def test_blank_identity_quarantines_full_native_cell(self):
        counts,bad,_,withheld=m.aggregate({'a':'100101','b':'100102'}, {'100101':1},[{'identities':{'a':'1','b':'1'}}],{'1'})
        self.assertEqual(counts,{});self.assertIn('1',bad);self.assertEqual(withheld,2)
    def test_identity_repeated_across_dated_reports_rejects_anchor(self):
        with self.assertRaisesRegex(ValueError,'across dates'):
            m.aggregate({'a':'100101'}, {},[{'identities':{'a':'1'}},{'identities':{'a':'1'}}],{'1'})
    def test_alias_evidence_includes_the_actual_cutoff_day(self):
        calls=[]
        def state(when):
            calls.append(when)
            return {'date':str(when),'source':'https://official.example/state','sha256':'a'*64,'identities':{'id-'+str(when.day):'1001'}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'dashboard/data').mkdir(parents=True)
            (root/'dashboard/data/reference.json').write_text(json.dumps([{'id':'tarrant','groups':[{'new':['1001']}]}]))
            ids={'id-'+str(day):'100101' for day in range(19,27)}
            with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'download',return_value=(b'%PDF synthetic',{})),mock.patch.object(m.subprocess,'run',return_value=SimpleNamespace(stdout=b'synthetic control')),mock.patch.object(m,'cutoff_control',return_value=(datetime(2026,10,26,21),8)),mock.patch.object(m,'parse_native',return_value=(ids,{},Counter({'100101':8}),{})),mock.patch.object(m,'state',side_effect=state):
                daily,evidence=m.collect(date(2026,10,26))
            self.assertEqual(sorted(calls),[date(2026,10,day) for day in range(19,27)])
            self.assertEqual(daily['counts'],{'1001':8})
            self.assertFalse(daily['allow_daily_difference'])
    def test_control_is_exact_completed_cutoff_not_prior_date(self):
        text='November 3, 2026\nOctober 26, 2026\nEarly Voting In Person Totals\n8:58:11PM\nTotal 10/19 10/20 10/21 10/22 10/23 10/24 10/25 10/26\nTotal 36 1 2 3 4 5 6 7 8\nSite One  36 1 2 3 4 5 6 7 8\n'
        generated,total=m.cutoff_control(text,date(2026,10,26));self.assertEqual(total,36)
        with self.assertRaisesRegex(ValueError,'exact completed cutoff'):m.cutoff_control(text,date(2026,10,25))
        with self.assertRaisesRegex(ValueError,'exact completed cutoff'):m.cutoff_control(text.replace('8:58:11PM','6:58:11PM'),date(2026,10,26))
        member=SimpleNamespace(date_time=(2026,10,26,21,0,20))
        self.assertIn('zip_member_modified',m.prove_archive_cutoff({'last-modified':'Tue, 27 Oct 2026 02:03:31 GMT'},member,generated,date(2026,10,26)))
        with self.assertRaisesRegex(ValueError,'exact cutoff'):
            m.prove_archive_cutoff({'last-modified':'Wed, 28 Oct 2026 02:03:31 GMT'},member,generated,date(2026,10,26))
    def test_independent_site_totals_must_reconcile(self):
        text='November 3, 2026\nOctober 19, 2026\nEarly Voting In Person Totals\n8:58:11PM\nTotal 10/19\nTotal 5 5\nSite One  4 4\n'
        with self.assertRaisesRegex(ValueError,'location totals'):m.cutoff_control(text,date(2026,10,19))
if __name__=='__main__':unittest.main()

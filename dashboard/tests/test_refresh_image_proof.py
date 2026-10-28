"""Real renderer CLI accepts a frozen Rust proof and rejects changed provenance."""
import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/render_images.py'
class FrozenProofTests(unittest.TestCase):
 def run_renderer(self,proof,expected=None,companion=False):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);raw=json.dumps(proof,separators=(',',':'),ensure_ascii=False).encode()
   snapshot={'completeness_sha256':expected or hashlib.sha256(raw).hexdigest(),'through':'2026-10-27','days':9,'generated_at':'fixture','geography':'fixture','counties':[]}
   (root/'snapshot.json').write_text(json.dumps(snapshot));(root/'controls.json').write_text(json.dumps(proof[0]))
   qualification=root/('snapshot.qualification.json' if companion else 'proof.json');qualification.write_bytes(raw)
   command=[sys.executable,str(SCRIPT),'--snapshot',str(root/'snapshot.json'),'--controls',str(root/'controls.json'),'--output',str(root/'out')]
   if not companion:command+=['--qualification',str(qualification)]
   result=subprocess.run(command,capture_output=True,text=True)
   if result.returncode==0:self.assertEqual((root/'out/qualification.json').read_bytes(),raw)
   return result
 def test_control_plus_recovery_proof_is_accepted_without_disabling_hash_check(self):
  proof=[{'schema_version':1,'generated_at':'fixture','controls':[]},{'schema_version':1,'method':'reviewed daily sources','observations':[]}]
  result=self.run_renderer(proof);self.assertEqual(result.returncode,0,result.stderr)
 def test_snapshot_companion_proof_is_discovered_for_recurring_render(self):
  result=self.run_renderer([{'schema_version':1,'generated_at':'fixture','controls':[]},None],companion=True)
  self.assertEqual(result.returncode,0,result.stderr)
 def test_altered_qualification_still_fails_closed(self):
  result=self.run_renderer([{'schema_version':1,'generated_at':'changed','controls':[]},None],expected='0'*64)
  self.assertNotEqual(result.returncode,0);self.assertIn('qualification',result.stderr.lower())
if __name__=='__main__':unittest.main()

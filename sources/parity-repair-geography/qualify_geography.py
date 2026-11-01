"""Offline evidence/negative-admission gate: never modifies production files."""
from datetime import datetime,timezone
import hashlib,importlib.util,json
from pathlib import Path
import subprocess,xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
STORE=ROOT/'analysis/parity-repair/geography'
WANTED=['gregg','guadalupe','hill','taylor','upton','wood']


def main():
    spec=importlib.util.spec_from_file_location('stage',Path(__file__).with_name('stage_guadalupe.py'))
    # Stage parser imports curl_cffi via the established SOS helper.
    stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
    project=ROOT/'analysis/county-recovery/admission-additional/project'
    refs={r['id']:r for r in json.loads((project/'dashboard/data/reference.json').read_text())}
    results={}
    reasons={
        'gregg':'Current native county source found; historical ordinary native source/dictionary absent; anonymous media API401, bounded historicalfile404; Clarity all-mode turnout cannot substitute.',
        'guadalupe':'Historical native canvass redistributes accepted provisionals into mode totals;169+45=214. Ordinary early participation cannot be isolated by native precinct.',
        'hill':'Current report contains ballot style rather than residence precinct; sample ballot groups do not provide a complete unique native mapping.',
        'taylor':'All34 historical labels end in literal period; no official historical equivalence/native ordinary source proved.',
        'upton':'Current county PCT values are decimal subdivisions; full native map codes remain unproved; no truncation allowed.',
        'wood':'Historical decimal subdivisions lack explicit native dictionary; real42-UHISD reporting subdivision and all-mode turnout do not establish ordinary early participation.'}
    avenues={
        'gregg':['Official native maps','Ordinary current/historical county roster discovery, including bounded anonymous media search','Official Clarity native turnout and reporting-unit dictionary'],
        'guadalupe':['Official boundary order and native maps','Certified native canvass/summary checked against signed reconciliation','Official historical ordinary-roster/participation-source discovery'],
        'hill':['Updated county history roster schema','Official sample-ballot equivalence evidence','Native geographic prerequisites and map namespace'],
        'taylor':['Fresh official archive and direct result/reconciliation documents','Official election notice and targeted primary-source discovery','Retained old/current source-code/native-universe diagnostics'],
        'upton':['New current and historical ordinary-roster schema','Official current sample-ballot/native labels','Retained native geographic crosswalk prerequisites'],
        'wood':['Official parent precinct maps','Official election results and Clarity directory','Aggregate native reporting-unit/turnout dictionary']}
    for c in WANTED:
        ref=refs[c];old=[p for g in ref['groups'] for p in g['old']];new=[p for g in ref['groups'] for p in g['new']]
        assert len(old)==len(set(old)) and len(new)==len(set(new))
        maps=json.loads((project/f'dashboard/data/maps/{c}.geojson').read_text())
        assert {f['properties']['precinct'] for f in maps['features']}==set(new)
        for path in ['dashboard/data/demographics.json','dashboard/places/texas.json']:
            obj=json.loads((project/path).read_text())['counties'][c]
            assert set(obj['precincts'])==set(new)
        assert len(avenues[c])<=3
        results[c]=dict(native_2024_precincts=len(old),native_2026_precincts=len(new),groups=len(ref['groups']),geographic_prerequisites_pass=True,admission_approved=False,reason=reasons[c],avenues_checked=avenues[c])
    facts=json.loads((STORE/'source-facts.json').read_text());verified=0
    for f in facts:
        if not f.get('path'):continue
        path=ROOT/f['path'];assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest()==f['sha256'],path
        verified+=1
    raw=ROOT/'sources/parity-repair-geography/raw/guadalupe-2024-precinct-results.pdf'
    text=subprocess.run(['pdftotext','-layout',str(raw),'-'],capture_output=True,check=True).stdout.decode()
    native=stage.parse_precinct(text);assert len(native)==76
    assert set(native)=={p for g in refs['guadalupe']['groups'] for p in g['old']}
    assert sum(r['early_in_person'] for r in native.values())==67411
    assert sum(r['election_day'] for r in native.values())==14959
    assert 67411-67242==169 and 14959-14914==45 and 169+45==214
    rejected=STORE/'staged/guadalupe-UNAPPROVED-canvass-alternative'
    proof=json.loads((rejected/'guadalupe-proof.json').read_text());assert proof['admission_approved'] is False
    candidate=json.loads((rejected/'UNAPPROVED-2024-canvass-alternative.json').read_text())[0]
    assert not candidate['complete'] and candidate['allow_daily_difference'] is False
    assert 'UNAPPROVED' in candidate['note']
    assert not (rejected/'reference-additions.json').exists()
    for c,units,total in [('gregg',21,46974),('wood',15,24503)]:
        xml=ET.fromstring((ROOT/f'sources/parity-repair-geography/raw/{c}-2024-detail.xml').read_bytes())
        turnout=xml.find('VoterTurnout');rows=turnout.findall('./Precincts/Precinct')
        assert len(rows)==units and int(turnout.attrib['ballotsCast'])==total
        assert sum(int(p.attrib['ballotsCast']) for p in rows)==total
    status=dict(checked_at=datetime.now(timezone.utc).isoformat(),reviewed=WANTED,admitted=[],approved_additional_paired_precincts=0,counties=results,verified_saved_aggregate_hashes=verified,
        guadalupe_scope_falsification=dict(native_early_mode=67411,ordinary_early_voters=67291,ordinary_early_counted=67242,ordinary_election_day_counted=14914,native_election_day_mode=14959,early_excess=169,election_day_excess=45,provisional_counted=214,admission_approved=False),passed=True)
    (STORE/'qualification.json').write_text(json.dumps(status,indent=2)+'\n')
    (STORE/'staged/approved-reference-additions.json').write_text('[]\n')
    print(json.dumps(status,indent=2))


if __name__=='__main__':main()

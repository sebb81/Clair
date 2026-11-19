"""Deterministic checks of real benchmark evidence; does not replace human review."""
import json
import re
from pathlib import Path


def check(path):
    result=json.loads(path.read_text(encoding='utf-8'))
    checks=[]
    for run in result['runs']:
        text=run.get('answer','').lower()
        q=run['question'].lower()
        outcome={'question':run['question'],'strategy':run['strategy_requested'],
                 'completed':'error' not in run and bool(text),
                 'valid_source_pages':all(1 <= s['page'] <= 4 for s in run.get('sources',[]) if s['page'] is not None)}
        if 'budget' in q and '2099' not in q:
            outcome['budget_240000']=bool(re.search(r'240\s*000',text))
        if 'responsable' in q: outcome['responsable_nadia_martin']='nadia martin' in text
        if '2099' in q or 'tva' in q: outcome['absent_information_reported']='introuvable' in text
        if q.startswith('résume le document'):
            outcome['four_topics_mentioned']=all(any(w in text for w in words) for words in [
                ['archive'],['240'],['scanner','archiviste'],['mensuelle','sauvegarde']])
            outcome['no_explicit_decision_negation']=not bool(re.search(r'(aucune|sans|pas de)\s+d[ée]cision',text))
        checks.append(outcome)
    target=path.with_name(path.stem+'-checks.json')
    target.write_text(json.dumps({'model':result['model'],'checks':checks,
        'limit':'Vérifications de présence et de structure, pas une preuve de fidélité sémantique.'},indent=2,ensure_ascii=False),encoding='utf-8')
    print(path.name, 'checks:', json.dumps(checks,ensure_ascii=True))


if __name__=='__main__':
    for path in Path('docs').glob('benchmark-qwen*.json'):
        if not path.stem.endswith('-checks'): check(path)

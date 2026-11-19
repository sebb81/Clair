"""Prepare comparable WebNN requests without writing to the document library."""
import json
import re
from pathlib import Path

from tokenizers import Tokenizer

from app import selection
from app.config import settings
from app.store import chunks, db, document


def make_case(name, evidence, question, limit, structured=False):
    return {'id': name, 'request': {
        'messages': [
            {'role': 'system', 'content': (
                'Tu es un analyste documentaire. Réponds en français à partir des extraits uniquement.')},
            {'role': 'user', 'content': f'Extraits :\n{evidence}\n\nQuestion : {question}'},
        ],
        'max_tokens': limit, 'json_output': structured,
    }}


def main():
    output = Path('data/webnn-bench')
    output.mkdir(parents=True, exist_ok=True)
    tokenizer = Tokenizer.from_file(str(settings.data_dir / 'webnn-model/qwen2/tokenizer.json'))

    def count(text):
        return len(tokenizer.encode(text, add_special_tokens=False).ids)

    aster = """[S1] L'enveloppe initiale pour le projet Aster était de 180 000 euros. Le comité a approuvé le 12 février 2027 un budget révisé de 240 000 euros.
[S2] Le lancement du pilote est prévu en mars 2027, sous réserve de l'autorisation du comité de sécurité. La date de déploiement général n'est pas arrêtée.
[S3] Un audit a relevé des efforts d'accessibilité. La conformité au RGAA n'a pas été démontrée. Le montant des coûts de maintenance est inconnu."""
    format_json = (' Donne uniquement un JSON sous la forme {"paragraphs":[{"source_ids":[N],"text":"fait"}]}. '
                   'Remplace N par le numéro de source utilisé, sans lettre S.')
    format_bullets = (' Une puce par fait. Termine chaque puce par son identifiant de source '
                      'exact, entre crochets. Utilise les identifiants présents dans les extraits.')
    short_question = 'Résume le budget approuvé, le calendrier et la réserve sur la conformité RGAA.'
    cases = [
        make_case('fait', aster, 'Quel montant le comité a-t-il approuvé ? Une phrase, cite la source entre crochets.', 100),
        make_case('resume_court', aster, short_question + ' Trois phrases courtes et sourcées.' + format_json, 240, True),
        make_case('resume_court_puces', aster, short_question + format_bullets, 240),
    ]
    with db() as conn:
        row = conn.execute("SELECT id FROM documents WHERE kind='pdf' AND pages=111 ORDER BY id LIMIT 1").fetchone()
    if row:
        info = document(row['id'])
        evidence, ids, _ = selection.select(list(chunks(row['id'])), info['sections'], 1050, count)
        aliases = {original: index for index, original in enumerate(sorted(ids), 1)}
        evidence = re.sub(r'\[S(\d+)\]', lambda match: f'[S{aliases.get(int(match[1]), int(match[1]))}]', evidence)
        cases.append(make_case('pdf_111_pages', evidence, (
            'Fais un résumé structuré en français. Préserve les chiffres, décisions et réserves.' + format_json), 320, True))
        cases.append(make_case('pdf_111_pages_puces', evidence, (
            'Fais un résumé en français en 90 mots maximum. Préserve les chiffres, décisions et réserves.'
            + format_bullets), 320))
        (output / 'long-sources.json').write_text(
            json.dumps({alias: original for original, alias in aliases.items()}), encoding='utf-8')
    (output / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(cases)} requêtes de comparaison prêtes.')


if __name__ == '__main__':
    main()

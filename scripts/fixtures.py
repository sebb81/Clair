from pathlib import Path
import pymupdf
from docx import Document


PAGES = [
    ('Chapitre 1 - Objectif', 'Le projet Horizon modernise les archives municipales.\nLa responsable est Nadia Martin.\nLe comite decide un pilote en mars 2027.'),
    ('Chapitre 2 - Budget', 'Le budget annonce pour 2027 est de 240 000 euros.\nEquipement : 90 000 euros. Formation : 50 000 euros.\nNumerisation : 100 000 euros.'),
    ('Chapitre 3 - Risques', 'Risques identifies : retard de livraison des scanners\net indisponibilite des archivistes.\nLe deploiement est prevu en septembre 2027.'),
    ('Chapitre 4 - Decisions', 'Decisions : revue mensuelle des couts et sauvegarde locale quotidienne.\nLe prestataire reste a selectionner.\nAucun nom de fournisseur ni taux de TVA ne sont indiques.'),
]


def make_pdf(path: Path, pages=4):
    pdf = pymupdf.open()
    for i in range(pages):
        title, body = PAGES[i % 4]
        page = pdf.new_page()
        page.insert_text((50, 60), title, fontsize=16)
        page.insert_text((50, 105), body, fontsize=11)
        if i == 1:
            # A genuine ruled table, not a text mockup.
            for y in [190, 215, 240, 265]:
                page.draw_line((50,y), (380,y))
            for x in [50,250,380]:
                page.draw_line((x,190), (x,265))
            for row, values in enumerate([['Poste','Euros'],['Equipement','90000'],['Formation','50000']]):
                for col, text in enumerate(values):
                    page.insert_text((60 if col==0 else 260,207+row*25),text,fontsize=10)
    pdf.save(path, garbage=3, deflate=True)
    pdf.close()


def make_docx(path):
    doc = Document()
    for title, body in PAGES:
        doc.add_heading(title, level=1)
        doc.add_paragraph(body)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0,0).text='Budget 2027'
    table.cell(0,1).text='240 000 euros'
    table.cell(1,0).text='Responsable'
    table.cell(1,1).text='Nadia Martin'
    doc.save(path)


if __name__ == '__main__':
    target = Path('tests/fixtures')
    target.mkdir(parents=True, exist_ok=True)
    make_pdf(target/'horizon.pdf')
    make_docx(target/'horizon.docx')
    (target/'horizon.txt').write_text('\n\n'.join('# '+title+'\n'+body for title,body in PAGES), encoding='utf-8')

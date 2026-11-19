import pytest
from app.config import settings
from app.store import initialize


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    (tmp_path/'files').mkdir()
    initialize()


@pytest.fixture
def pdf(tmp_path):
    from scripts.fixtures import make_pdf
    path = tmp_path/'test.pdf'
    make_pdf(path)
    return path


@pytest.fixture
def imported(pdf):
    from app.extract import extract
    return extract(pdf, 'horizon.pdf', 'fixture')[0]

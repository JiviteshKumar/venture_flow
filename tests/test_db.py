import db


def test_similar_company_query_casts_nullable_parameters(monkeypatch):
    executed = []

    class Cursor:
        def execute(self, query, params):
            executed.append((query, params))

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(db, "connection", lambda: Connection())

    assert db.find_similar_companies("Test Co", None, None) == []
    query, params = executed[0]
    assert "%(sector)s::text" in query
    assert "%(domain)s::text" in query
    assert params["sector"] is None

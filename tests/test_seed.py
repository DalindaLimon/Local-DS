from app import seed
from app.db import connect
from app.security import hash_password


def test_remove_deletes_demo_data_and_untouched_demo_users(settings):
    seed.seed(settings, with_users=True, videos=False)
    conn = connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE kind='demo'").fetchone()[0] > 0
    # friend changed their password, so that account is a real one now and must survive
    conn.execute("UPDATE users SET pw_hash=? WHERE username='friend'", (hash_password("a-new-secret-pw"),))

    seed.remove(settings)
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE kind='demo'").fetchone()[0] == 0
    assert [r["username"] for r in conn.execute("SELECT username FROM users")] == ["friend"]

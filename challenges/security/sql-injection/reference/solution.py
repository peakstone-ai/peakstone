import sqlite3


def get_user(conn: sqlite3.Connection, username: str):
    cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
    return cur.fetchone()

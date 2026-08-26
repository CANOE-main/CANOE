import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_transaction(db_path: Path, force_foreign_keys: bool = True):
    """
    Open a single SQLite database connection and treat everything that
    happens inside the `with` block as one all-or-nothing operation.

    Why this exists
    ----------------
    If you run several database operations in a row (e.g. insert a
    record, then update another table, then insert another record) and
    the third one fails, you probably don't want the first two changes
    to be saved anyway — that would leave your database in a half-done,
    inconsistent state. This function guarantees that either ALL the
    operations inside the `with` block succeed and are saved together,
    or NONE of them are (if anything raises an error, everything done
    so far is undone automatically).

    This all-or-nothing guarantee is called a "transaction" in database
    terminology, and undoing changes is called a "rollback."

    How to use it
    --------------
    Call it in a `with` statement and use the connection it gives you
    for every database operation you want grouped together:

        with transaction("my_data.db") as conn:
            conn.execute("INSERT INTO subjects (name) VALUES (?)", ("P01",))
            conn.execute("INSERT INTO trials (subject_id, score) VALUES (?, ?)", (1, 95))
            # If an error happens on any line above, neither INSERT
            # takes effect — the database ends up exactly as it was
            # before the `with` block started.

    Do not call conn.commit() yourself inside the block — this function
    handles that for you once everything inside succeeds.

    What happens step by step
    --------------------------
    1. A connection to the database file is opened.
    2. A setting is turned on that makes SQLite enforce relationships
       between tables (e.g. it won't let you reference a subject ID
       that doesn't exist).
    3. Control is handed to your `with` block, where your own code runs.
    4a. If your code finishes with no errors, all the changes are
        permanently saved to the database file (this is the "commit").
    4b. If your code raises an error at any point, every change made
        so far in the block is discarded (this is the "rollback"),
        and the original error is passed back up so you still see
        what went wrong.
    5. The connection is closed, whether things succeeded or failed.

    Parameters
    ----------
    db_path : Path
        File path to the SQLite database (e.g. "results.db"). If the
        file doesn't exist yet, SQLite will create it.
    force_foreign_keys : bool, optional
        If True, the `PRAGMA foreign_keys = ON` setting is enforced,
        ensuring foreign key constraints are enforced. Default is True.

    Yields
    ------
    sqlite3.Connection
        An open database connection to run your operations on. Pass
        this connection into any helper functions you call inside the
        `with` block so they all operate on the same transaction.
    """
    conn = sqlite3.connect(db_path)
    if force_foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

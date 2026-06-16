import sqlite3

import pytest

import database


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    database.init_db(connection)
    yield connection
    connection.close()

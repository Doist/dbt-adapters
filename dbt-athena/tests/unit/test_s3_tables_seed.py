from .utils import macro_caller

call = macro_caller("materializations/seeds/helpers.sql")

COLUMNS = [
    {"name": "id", "quoted": '"id"', "type": "integer"},
    {"name": "name", "quoted": '"name"', "type": "varchar"},
]


def _row_size(row):
    return sum(len(str(v).encode("utf-8")) + str(v).count("'") + 16 for v in row) + 4


def test_batches_empty():
    assert call("s3_tables_seed_batches", [], 100) == []


def test_batches_split_at_the_limit():
    rows = [[1, "a"], [2, "b"], [3, "c"]]
    size = _row_size(rows[0])
    assert call("s3_tables_seed_batches", rows, size * 2) == [rows[:2], rows[2:]]


def test_batches_keep_an_oversized_row_on_its_own():
    rows = [[1, "x" * 500], [2, "b"]]
    assert call("s3_tables_seed_batches", rows, 100) == [rows[:1], rows[1:]]


def test_batches_count_utf8_bytes_and_quotes():
    ascii_row, japanese_row, quoted_row = ["aaa"], ["日本語"], ["a'b"]
    assert _row_size(japanese_row) == _row_size(ascii_row) + 6
    assert _row_size(quoted_row) == _row_size(ascii_row) + 1
    limit = _row_size(ascii_row) * 2
    assert call("s3_tables_seed_batches", [ascii_row, ascii_row], limit) == [
        [ascii_row, ascii_row]
    ]
    assert call("s3_tables_seed_batches", [japanese_row, ascii_row], limit) == [
        [japanese_row],
        [ascii_row],
    ]


def test_bindings_flatten_rows():
    assert call("s3_tables_seed_bindings", [[1, "a"], [2, "b"]]) == [1, "a", 2, "b"]
    assert call("s3_tables_seed_bindings", []) is None


def test_select_with_rows_has_one_placeholder_per_value():
    sql = str(call("s3_tables_seed_select", COLUMNS, [[1, "a"], [2, "b"]]))
    assert 'cast("id" as integer) as "id"' in sql
    assert 'cast("name" as varchar) as "name"' in sql
    assert sql.count("%s") == 4
    assert ') as t("id", "name")' in sql
    assert "where false" not in sql


def test_select_without_rows_is_empty_but_typed():
    sql = str(call("s3_tables_seed_select", COLUMNS, []))
    assert "from (values (null, null)) as t" in sql
    assert "where false" in sql
    assert "%s" not in sql

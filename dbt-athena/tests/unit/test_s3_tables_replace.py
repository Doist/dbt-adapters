from types import SimpleNamespace

import pytest

from .utils import macro_caller

MACROS = "materializations/models/table/s3_tables_replace.sql"


class _Relation:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name

    def incorporate(self, path):
        return _Relation(path["identifier"])

    @property
    def identifier(self):
        return self.name


def _replace(merge_result, force_batch=False):
    calls = []

    def run_merge(sql):
        calls.append("merge")
        return merge_result

    def create_table_as(temporary, relation, sql, language, force_batch):
        calls.append(f"create {relation} force_batch={force_batch}")
        return "OK"

    adapter = SimpleNamespace(
        get_columns_in_relation=lambda relation: [SimpleNamespace(name="id")],
        run_query_with_partitions_limit_catching=run_merge,
        rename_s3_tables_relation=lambda old, new: calls.append(f"rename {old} {new}"),
    )
    call = macro_caller(
        MACROS,
        adapter=adapter,
        config=SimpleNamespace(
            get=lambda key: SimpleNamespace(enforced=False) if key == "contract" else None
        ),
        exceptions=SimpleNamespace(warn=lambda message: calls.append("warn")),
        get_column_schema_from_query=lambda sql: (
            [] if "$partitions" in sql else [SimpleNamespace(name="id")]
        ),
        run_query=lambda sql: SimpleNamespace(rows=[["integer", "integer", "row()"]]),
        make_temp_relation=lambda relation, suffix: _Relation(f"{relation}{suffix}"),
        drop_relation=lambda relation: calls.append(f"drop {relation}"),
        safe_create_table_as=create_table_as,
    )
    return call("s3_tables_replace", _Relation("t"), "select 1 as id", False, force_batch), calls


def test_replace_merges_in_place():
    replaced, calls = _replace("OK 3")
    assert replaced == {"mode": "merge", "query_result": "OK 3"}
    assert calls == ["merge"]


@pytest.mark.parametrize(
    "merge_result,force_batch,expected_calls",
    [
        ("TOO_MANY_OPEN_PARTITIONS", False, ["merge"]),
        (None, True, []),
    ],
    ids=["over-100-partitions", "force-batch"],
)
def test_replace_swaps_in_a_new_table_when_the_merge_cannot_run(
    merge_result, force_batch, expected_calls
):
    replaced, calls = _replace(merge_result, force_batch)
    assert replaced == {"mode": "rebuilt", "query_result": "OK"}
    assert calls == expected_calls + [
        "warn",
        "drop t__ha",
        "drop t__bkp",
        "create t__ha force_batch=True",
        "rename t t__bkp",
        "rename t__ha t",
        "drop t__bkp",
    ]


def _evolve(old, new):
    queries = []
    call = macro_caller(MACROS, run_query=lambda sql: queries.append(sql) or "")
    relation = SimpleNamespace(render_hive=lambda: "`s3tablescatalog/b`.`ns`.`t`")
    evolved = call(
        "s3_tables_evolve_columns",
        relation,
        [{"name": n, "type": t} for n, t in old],
        [{"name": n, "type": t} for n, t in new],
    )
    return evolved, queries


@pytest.mark.parametrize(
    "data_type,expected",
    [
        ("varchar(10)", "varchar"),
        ("char(3)", "varchar"),
        ("timestamp(3)", "timestamp(6)"),
        ("array(varchar(5))", "array(varchar)"),
        ("bigint", "bigint"),
    ],
)
def test_normalize_type(data_type, expected):
    assert macro_caller(MACROS)("s3_tables_normalize_type", data_type) == expected


@pytest.mark.parametrize(
    "partitioned_by,expected",
    [
        (None, []),
        (["Day"], ["day"]),
        (["day(ts)", "hour(ts)"], ["ts_day", "ts_hour"]),
        (["bucket(16, user_id)", "truncate(4, name)"], ["user_id_bucket", "name_trunc"]),
    ],
)
def test_partition_fields_from_config(partitioned_by, expected):
    call = macro_caller(MACROS)
    assert call("s3_tables_partition_fields_from_config", partitioned_by) == expected


@pytest.mark.parametrize(
    "old_type,new_type,expected",
    [
        ("integer", "bigint", True),
        ("real", "double", True),
        ("decimal(10,2)", "decimal(12,2)", True),
        ("decimal(10,2)", "decimal(12,3)", False),
        ("decimal(12,2)", "decimal(10,2)", False),
        ("bigint", "integer", False),
        ("varchar", "bigint", False),
    ],
)
def test_is_type_promotion(old_type, new_type, expected):
    assert macro_caller(MACROS)("s3_tables_is_type_promotion", old_type, new_type) is expected


@pytest.mark.parametrize(
    "data_type,expected",
    [
        ("varchar", "string"),
        ("integer", "int"),
        ("timestamp(6)", "timestamp"),
        ("decimal(10,2)", "decimal(10,2)"),
        ("array(integer)", None),
    ],
)
def test_ddl_type(data_type, expected):
    assert macro_caller(MACROS)("s3_tables_ddl_type", data_type) == expected


def test_merge_sql_keeps_trailing_comment_off_the_closing_parenthesis():
    sql = macro_caller(MACROS)(
        "s3_tables_replace_merge_sql",
        "t",
        "select 1 as id -- trailing comment",
        [{"name": "id", "type": "integer"}],
    )
    lines = [line.strip() for line in str(sql).splitlines()]
    assert "select 1 as id -- trailing comment" in lines
    assert ") as dbt_new" in lines


def test_merge_sql_deletes_old_rows_and_inserts_new_ones():
    sql = str(
        macro_caller(MACROS)(
            "s3_tables_replace_merge_sql",
            "t",
            "select 1 as id, 'a' as name",
            [{"name": "id", "type": "integer"}, {"name": "name", "type": "varchar"}],
        )
    )
    assert "merge into t as target" in sql
    assert "cast(null as integer), cast(null as varchar), bucket" in sql
    assert "when matched then delete" in sql
    assert 'insert ("id", "name") values (src."id", src."name")' in sql


def test_evolve_columns_unchanged_runs_nothing():
    assert _evolve([("id", "integer")], [("id", "integer")]) == (True, [])


def test_evolve_columns_adds_drops_and_promotes():
    evolved, queries = _evolve(
        [("id", "integer"), ("gone", "varchar"), ("amount", "decimal(10,2)")],
        [("id", "bigint"), ("amount", "decimal(12,2)"), ("note", "varchar")],
    )
    assert evolved is True
    assert queries == [
        "alter table `s3tablescatalog/b`.`ns`.`t` drop column `gone`",
        "alter table `s3tablescatalog/b`.`ns`.`t` change column `id` `id` bigint",
        "alter table `s3tablescatalog/b`.`ns`.`t` change column `amount` `amount` decimal(12,2)",
        "alter table `s3tablescatalog/b`.`ns`.`t` add columns (`note` string)",
    ]


@pytest.mark.parametrize(
    "old,new",
    [
        ([("a", "integer"), ("b", "integer")], [("b", "integer"), ("a", "integer")]),
        ([("a", "integer"), ("b", "integer")], [("c", "integer"), ("a", "integer")]),
        ([("a", "bigint")], [("a", "integer")]),
        ([("a", "integer")], [("a", "integer"), ("b", "array(integer)")]),
    ],
    ids=["reordered", "added-before-kept", "narrowed", "unsupported-added-type"],
)
def test_evolve_columns_refuses_and_runs_nothing(old, new):
    assert _evolve(old, new) == (False, [])

import pytest

from .utils import macro_caller

call = macro_caller("utils/ddl_dml_data_type.sql")


@pytest.mark.parametrize(
    "col_type,table_type,expected",
    [
        ("varchar", "hive", "string"),
        ("varchar(10)", "hive", "string"),
        ("integer", "hive", "int"),
        ("decimal(10,2)", "hive", "decimal(10,2)"),
        ("array(integer)", "hive", "array<int>"),
        ("list<int>", "iceberg", "array<int>"),
        ("map(varchar,integer)", "hive", "map<string,int>"),
        ("array(decimal(10,2))", "hive", "array<decimal(10,2)>"),
        ("list<decimal(10,2)>", "iceberg", "array<decimal(10,2)>"),
        ("map(varchar,decimal(38, 0))", "hive", "map<string,decimal(38,0)>"),
        (
            "array(row(d decimal(10,2), t timestamp(6)))",
            "iceberg",
            "array<row<d decimal(10,2), t timestamp>>",
        ),
        ("timestamp(6)", "iceberg", "timestamp"),
        ("varbinary", "iceberg", "binary"),
    ],
)
def test_ddl_data_type(col_type, table_type, expected):
    assert call("ddl_data_type", col_type, table_type) == expected

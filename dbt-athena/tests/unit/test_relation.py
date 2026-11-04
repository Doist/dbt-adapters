from datetime import datetime, timezone

import pytest

from dbt.adapters.athena.relation import AthenaRelation, TableType, get_table_type
from dbt.adapters.base.relation import EventTimeFilter

from .constants import DATA_CATALOG_NAME, DATABASE_NAME

TABLE_NAME = "test_table"


class TestRelation:
    @pytest.mark.parametrize(
        ("table", "expected"),
        [
            ({"Name": "n", "TableType": "table"}, TableType.TABLE),
            ({"Name": "n", "TableType": "VIRTUAL_VIEW"}, TableType.VIEW),
            (
                {
                    "Name": "n",
                    "TableType": "EXTERNAL_TABLE",
                    "Parameters": {"table_type": "ICEBERG"},
                },
                TableType.ICEBERG,
            ),
            # S3 Tables tables report a "customer" TableType that is not in RELATION_TYPE_MAP.
            # The iceberg `table_type` parameter must take precedence so they classify correctly.
            (
                {
                    "Name": "n",
                    "TableType": "customer",
                    "Parameters": {"table_type": "ICEBERG"},
                },
                TableType.ICEBERG,
            ),
        ],
    )
    def test__get_relation_type(self, table, expected):
        assert get_table_type(table) == expected

    def test__get_relation_type_with_no_type(self):
        with pytest.raises(ValueError):
            get_table_type({"Name": "name"})

    def test__get_relation_type_with_unknown_type(self):
        with pytest.raises(ValueError):
            get_table_type({"Name": "name", "TableType": "test"})


class TestAthenaRelation:
    def test_render_hive_uses_hive_style_quotation_and_only_schema_and_table_names(self):
        relation = AthenaRelation.create(
            identifier=TABLE_NAME,
            database=DATA_CATALOG_NAME,
            schema=DATABASE_NAME,
        )
        assert relation.render_hive() == f"`{DATABASE_NAME}`.`{TABLE_NAME}`"

    def test_render_hive_keeps_the_s3_tables_catalog(self):
        relation = AthenaRelation.create(
            identifier=TABLE_NAME,
            database="s3tablescatalog/my-bucket",
            schema=DATABASE_NAME,
        )
        assert relation.render_hive() == (
            f"`s3tablescatalog/my-bucket`.`{DATABASE_NAME}`.`{TABLE_NAME}`"
        )
        assert relation.without_identifier().render_hive() == (
            f"`s3tablescatalog/my-bucket`.`{DATABASE_NAME}`"
        )
        assert relation.render() == f'"s3tablescatalog/my-bucket"."{DATABASE_NAME}"."{TABLE_NAME}"'

    def test_render_hive_resets_quote_character_and_include_policy_after_call(self):
        relation = AthenaRelation.create(
            identifier=TABLE_NAME,
            database=DATA_CATALOG_NAME,
            schema=DATABASE_NAME,
        )
        relation.render_hive()
        assert relation.render() == f'"{DATA_CATALOG_NAME}"."{DATABASE_NAME}"."{TABLE_NAME}"'

    def test_render_pure_resets_quote_character_after_call(self):
        relation = AthenaRelation.create(
            identifier=TABLE_NAME,
            database=DATA_CATALOG_NAME,
            schema=DATABASE_NAME,
        )
        assert relation.render_pure() == f"{DATA_CATALOG_NAME}.{DATABASE_NAME}.{TABLE_NAME}"

    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            (
                datetime(2026, 8, 25, tzinfo=timezone.utc),
                datetime(2026, 8, 28, tzinfo=timezone.utc),
                "ts >= timestamp '2026-08-25 00:00:00+00:00' and ts < timestamp '2026-08-28 00:00:00+00:00'",
            ),
            (
                datetime(2026, 8, 25, tzinfo=timezone.utc),
                None,
                "ts >= timestamp '2026-08-25 00:00:00+00:00'",
            ),
            (
                None,
                datetime(2026, 8, 28, tzinfo=timezone.utc),
                "ts < timestamp '2026-08-28 00:00:00+00:00'",
            ),
            (None, None, ""),
        ],
    )
    def test_render_event_time_filtered_leaves_column_uncast(self, start, end, expected):
        relation = AthenaRelation.create(
            identifier=TABLE_NAME,
            database=DATA_CATALOG_NAME,
            schema=DATABASE_NAME,
        )
        event_time_filter = EventTimeFilter(field_name="ts", start=start, end=end)
        assert relation._render_event_time_filtered(event_time_filter) == expected

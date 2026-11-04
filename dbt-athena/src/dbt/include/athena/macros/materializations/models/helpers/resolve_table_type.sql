{#
  Resolve the effective `table_type` ('hive' or 'iceberg') for the current model.

  Precedence:
    1. An explicit `table_type` model config always wins (backward compatible).
    2. Otherwise, the `table_format` of the catalog referenced via `catalog_name`
       (catalogs.yml v2). The default `glue` catalog yields 'iceberg'.
    3. Otherwise, 'iceberg' when `relation` is given and lives in an S3 Tables
       catalog ("s3tablescatalog/<bucket>"), which accepts nothing else. This
       covers nodes that carry no model config, such as unit test probes.
    4. Otherwise, default to 'hive' (the default `info_schema` catalog also
       resolves to 'hive', so unconfigured models are unchanged).
#}
{% macro resolve_table_type(relation=none) %}
  {%- set catalog_relation = adapter.build_catalog_relation(config.model) -%}
  {%- set table_type = config.get('table_type', default=none) -%}
  {%- if table_type is none and catalog_relation is not none -%}
    {%- set table_type = catalog_relation.table_format -%}
  {%- endif -%}
  {%- if table_type is none and relation is not none and adapter.is_s3_tables_database(relation.database) -%}
    {%- set table_type = 'iceberg' -%}
  {%- endif -%}
  {{ return((table_type or 'hive') | lower) }}
{% endmacro %}

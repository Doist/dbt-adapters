{% macro athena__can_clone_table() %}
  {{ return(adapter.is_s3_tables_database(this.database)) }}
{% endmacro %}

{% macro athena__create_or_replace_clone(this_relation, defer_relation) %}
  {%- set existing_relation = adapter.get_relation(database=this_relation.database, schema=this_relation.schema, identifier=this_relation.identifier) -%}
  {%- if existing_relation is not none -%}
    {%- do drop_relation(existing_relation) -%}
  {%- endif -%}

  {%- set lookback_days = var('clone_lookback_days', none) -%}
  {%- set event_time = config.get('event_time') -%}
  {%- set clone_sql -%}
    select * from {{ defer_relation.render() }}
    {%- if lookback_days is not none and event_time is not none %}
    where {{ event_time }} >= current_timestamp - interval '{{ lookback_days | int }}' day
    {%- endif %}
  {%- endset -%}

  {%- set query_result = safe_create_table_as(False, this_relation, clone_sql) -%}
  select '{{ query_result }}'
{% endmacro %}

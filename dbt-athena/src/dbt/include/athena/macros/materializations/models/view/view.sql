{% materialization view, adapter='athena' -%}
    {%- if adapter.is_s3_tables_database(database) -%}
      {%- set error_view_s3_tables -%}
        View {{ this }} cannot be created: S3 Tables catalogs have no views, and Athena refuses
        CREATE VIEW over S3 Tables wherever the view lives. Materialize it as 'table' or 'ephemeral'.
      {%- endset -%}
      {% do exceptions.raise_compiler_error(error_view_s3_tables) %}
    {%- endif -%}
    {%- set identifier = model['alias'] -%}
    {%- set versions_to_keep = config.get('versions_to_keep', default=4) -%}
    {%- set target_relation = api.Relation.create(identifier=identifier,
                                                schema=schema,
                                                database=database,
                                                type='view') -%}

    {% set to_return = create_or_replace_view(run_outside_transaction_hooks=False) %}

    {% do adapter.expire_glue_table_versions(target_relation, versions_to_keep, False) %}

    {% set target_relation = this.incorporate(type='view') %}
    {% do persist_docs(target_relation, model) %}

    {% do return(to_return) %}
{%- endmaterialization %}

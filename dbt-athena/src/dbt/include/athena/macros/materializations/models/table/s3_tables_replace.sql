{% macro s3_tables_replace(target_relation, compiled_code, force_rebuild=false, force_batch=false) -%}
  {%- if config.get('contract').enforced -%}
    {%- do get_assert_columns_equivalent(compiled_code) -%}
  {%- endif -%}

  {%- set probe = s3_tables_probe(target_relation, compiled_code) -%}
  {%- set expected_partition_fields = s3_tables_partition_fields_from_config(config.get('partitioned_by')) -%}
  {%- set same_partitioning = probe.partition_fields == expected_partition_fields -%}

  {%- if not force_rebuild and same_partitioning and probe.new != probe.old
        and s3_tables_evolve_columns(target_relation, probe.old, probe.new) -%}
    {%- set probe = s3_tables_probe(target_relation, compiled_code) -%}
  {%- endif -%}

  {%- if force_rebuild or not same_partitioning or probe.new != probe.old -%}
    {%- do exceptions.warn('Rebuilding ' ~ target_relation ~ ' as a new table object: its LF grants and tags are reset. Columns ' ~ probe.old ~ ' -> ' ~ probe.new ~ ', partition fields ' ~ probe.partition_fields ~ ' -> ' ~ expected_partition_fields) -%}
    {{ return({'mode': 'rebuilt', 'query_result': s3_tables_rebuild(target_relation, compiled_code, force_batch)}) }}
  {%- endif -%}

  {%- if not force_batch -%}
    {%- set query_result = adapter.run_query_with_partitions_limit_catching(s3_tables_replace_merge_sql(target_relation, compiled_code, probe.new)) -%}
    {%- if query_result != 'TOO_MANY_OPEN_PARTITIONS' -%}
      {{ return({'mode': 'merge', 'query_result': query_result}) }}
    {%- endif -%}
  {%- endif -%}

  {%- do exceptions.warn('Rebuilding ' ~ target_relation ~ ' as a new table object: one MERGE cannot write over 100 partitions. Its LF grants and tags are reset.') -%}
  {{ return({'mode': 'rebuilt', 'query_result': s3_tables_rebuild(target_relation, compiled_code, true)}) }}
{%- endmacro %}


{% macro s3_tables_replace_merge_sql(target_relation, compiled_code, columns) -%}
  {#- One bucket row per hash of target."$path": every old row matches exactly one, new rows match none. -#}
  {%- set buckets = 64 -%}
  {%- set cols = [] -%}
  {%- set src_cols = [] -%}
  {%- set null_cols = [] -%}
  {%- for c in columns -%}
    {%- do cols.append('"' ~ c.name ~ '"') -%}
    {%- do src_cols.append('src."' ~ c.name ~ '"') -%}
    {%- do null_cols.append('cast(null as ' ~ c.type ~ ')') -%}
  {%- endfor -%}
  merge into {{ target_relation }} as target
  using (
    select {{ cols | join(', ') }}, cast(null as bigint) as "__dbt_replace_bucket"
    from (
{{ compiled_code }}
    ) as dbt_new
    union all
    select {{ null_cols | join(', ') }}, bucket
    from unnest(sequence(0, {{ buckets - 1 }})) as dbt_buckets(bucket)
  ) as src
  on src."__dbt_replace_bucket" = bitwise_and(from_big_endian_64(xxhash64(to_utf8(target."$path"))), {{ buckets - 1 }})
  when matched then delete
  when not matched and src."__dbt_replace_bucket" is null
    then insert ({{ cols | join(', ') }}) values ({{ src_cols | join(', ') }})
{%- endmacro %}


{% macro s3_tables_probe(target_relation, compiled_code) -%}
  {%- set new_names = get_column_schema_from_query(compiled_code) | map(attribute='name') | map('lower') | list -%}
  {%- set old_names = adapter.get_columns_in_relation(target_relation) | map(attribute='name') | map('lower') | list -%}
  {%- set partitions_relation = target_relation.incorporate(path={'identifier': target_relation.identifier ~ '$partitions'}) -%}
  {%- set is_partitioned = 'partition' in (get_column_schema_from_query('select * from ' ~ partitions_relation) | map(attribute='name') | list) -%}

  {%- set probe_sql -%}
    select
      {%- for n in new_names %} typeof(n."{{ n }}"),{% endfor %}
      {%- for n in old_names %} typeof(o."{{ n }}"),{% endfor %}
      {% if is_partitioned %}typeof(p.partition){% else %}'row()'{% endif %}
    from (values 1) as dbt_one(x)
    left join (select * from (
{{ compiled_code }}
    ) as dbt_q where false) as n on true
    left join (select * from {{ target_relation }} where false) as o on true
    {%- if is_partitioned %}
    left join (select partition from {{ partitions_relation }} where false) as p on true
    {%- endif %}
  {%- endset -%}
  {%- set row = run_query(probe_sql).rows[0] -%}

  {%- set new = [] -%}
  {%- set old = [] -%}
  {%- for n in new_names -%}
    {%- do new.append({'name': n, 'type': s3_tables_normalize_type(row[loop.index0])}) -%}
  {%- endfor -%}
  {%- for n in old_names -%}
    {%- do old.append({'name': n, 'type': row[new_names | length + loop.index0] | lower}) -%}
  {%- endfor -%}
  {%- set partition_fields = modules.re.findall('(?:^row\\(|, )([a-z0-9_]+) ', row[-1] | lower) -%}

  {{ return({'new': new, 'old': old, 'partition_fields': partition_fields}) }}
{%- endmacro %}


{% macro s3_tables_normalize_type(data_type) -%}
  {#- What Athena CTAS stores in Iceberg: varchar(n) as varchar, any timestamp or time precision as 6. -#}
  {%- set t = modules.re.sub('\\b(var)?char\\(\\d+\\)', 'varchar', data_type | lower) -%}
  {%- set t = modules.re.sub('\\b(timestamp|time)\\(\\d+\\)', '\\1(6)', t) -%}
  {{ return(t) }}
{%- endmacro %}


{% macro s3_tables_partition_fields_from_config(partitioned_by) -%}
  {%- set fields = [] -%}
  {%- for raw in (partitioned_by or []) -%}
    {%- set f = raw | lower | replace(' ', '') -%}
    {%- set time_transform = modules.re.match('^(year|month|day|hour)\\((\\w+)\\)$', f) -%}
    {%- set width_transform = modules.re.match('^(bucket|truncate)\\(\\d+,(\\w+)\\)$', f) -%}
    {%- if time_transform -%}
      {%- do fields.append(time_transform.group(2) ~ '_' ~ time_transform.group(1)) -%}
    {%- elif width_transform -%}
      {%- do fields.append(width_transform.group(2) ~ ('_bucket' if width_transform.group(1) == 'bucket' else '_trunc')) -%}
    {%- else -%}
      {%- do fields.append(f) -%}
    {%- endif -%}
  {%- endfor -%}
  {{ return(fields) }}
{%- endmacro %}


{% macro s3_tables_evolve_columns(relation, old, new) -%}
  {%- set old_types = {} -%}
  {%- for c in old -%}
    {%- do old_types.update({c.name: c.type}) -%}
  {%- endfor -%}
  {%- set new_names = new | map(attribute='name') | list -%}
  {%- set kept = old | selectattr('name', 'in', new_names) | map(attribute='name') | list -%}
  {%- set added = new | rejectattr('name', 'in', old_types.keys() | list) | list -%}
  {%- set dropped = old | rejectattr('name', 'in', new_names) | map(attribute='name') | list -%}

  {%- if kept + (added | map(attribute='name') | list) != new_names -%}
    {{ return(false) }}
  {%- endif -%}

  {%- set promoted = [] -%}
  {%- for c in new if c.name in kept and c.type != old_types[c.name] -%}
    {%- if not s3_tables_is_type_promotion(old_types[c.name], c.type) -%}
      {{ return(false) }}
    {%- endif -%}
    {%- do promoted.append(c) -%}
  {%- endfor -%}
  {%- for c in added -%}
    {%- if s3_tables_ddl_type(c.type) is none -%}
      {{ return(false) }}
    {%- endif -%}
  {%- endfor -%}

  {%- for name in dropped -%}
    {%- do run_query('alter table ' ~ relation.render_hive() ~ ' drop column `' ~ name ~ '`') -%}
  {%- endfor -%}
  {%- for c in promoted -%}
    {%- do run_query('alter table ' ~ relation.render_hive() ~ ' change column `' ~ c.name ~ '` `' ~ c.name ~ '` ' ~ s3_tables_ddl_type(c.type)) -%}
  {%- endfor -%}
  {%- if added -%}
    {%- set added_ddl = [] -%}
    {%- for c in added -%}
      {%- do added_ddl.append('`' ~ c.name ~ '` ' ~ s3_tables_ddl_type(c.type)) -%}
    {%- endfor -%}
    {%- do run_query('alter table ' ~ relation.render_hive() ~ ' add columns (' ~ added_ddl | join(', ') ~ ')') -%}
  {%- endif -%}

  {{ return(true) }}
{%- endmacro %}


{% macro s3_tables_is_type_promotion(old_type, new_type) -%}
  {%- if (old_type, new_type) in [('integer', 'bigint'), ('real', 'double')] -%}
    {{ return(true) }}
  {%- endif -%}
  {%- set o = modules.re.match('^decimal\\((\\d+),(\\d+)\\)$', old_type) -%}
  {%- set n = modules.re.match('^decimal\\((\\d+),(\\d+)\\)$', new_type) -%}
  {{ return(o is not none and n is not none and o.group(2) == n.group(2) and (n.group(1) | int) > (o.group(1) | int)) }}
{%- endmacro %}


{% macro s3_tables_ddl_type(data_type) -%}
  {%- set simple = {'varchar': 'string', 'boolean': 'boolean', 'integer': 'int', 'bigint': 'bigint', 'real': 'float',
                    'double': 'double', 'date': 'date', 'timestamp(6)': 'timestamp', 'varbinary': 'binary'} -%}
  {%- if data_type in simple -%}
    {{ return(simple[data_type]) }}
  {%- elif modules.re.match('^decimal\\(\\d+,\\d+\\)$', data_type) -%}
    {{ return(data_type) }}
  {%- endif -%}
  {{ return(none) }}
{%- endmacro %}


{% macro s3_tables_rebuild(target_relation, compiled_code, force_batch=false) -%}
  {%- set staging_relation = make_temp_relation(target_relation, '__ha') -%}
  {%- set backup_relation = make_temp_relation(target_relation, '__bkp') -%}
  {%- do drop_relation(staging_relation) -%}
  {%- do drop_relation(backup_relation) -%}
  {%- set query_result = safe_create_table_as(False, staging_relation, compiled_code, 'sql', force_batch) -%}

  {%- do adapter.rename_s3_tables_relation(target_relation, backup_relation) -%}
  {%- do adapter.rename_s3_tables_relation(staging_relation, target_relation) -%}
  {%- do drop_relation(backup_relation) -%}
  {{ return(query_result) }}
{%- endmacro %}

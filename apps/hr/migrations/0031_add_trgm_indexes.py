# Generated for P1-12: pg_trgm GIN 索引（raw_text + paragraph）
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0030_remove_candidate_legacy_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE EXTENSION IF NOT EXISTS pg_trgm;
                -- Resume 原文检索（icontains → UPPER LIKE），支撑 resume_search keyword 腿
                CREATE INDEX IF NOT EXISTS hr_resume_file_raw_text_trgm_idx
                    ON hr_resume_file USING gin (UPPER(raw_text) gin_trgm_ops);
                -- 段落内容检索（同为 icontains），支撑 keyword 腿与知识库检索
                CREATE INDEX IF NOT EXISTS paragraph_content_trgm_idx
                    ON paragraph USING gin (UPPER(content) gin_trgm_ops);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS hr_resume_file_raw_text_trgm_idx;
                DROP INDEX IF EXISTS paragraph_content_trgm_idx;
            """,
        ),
    ]

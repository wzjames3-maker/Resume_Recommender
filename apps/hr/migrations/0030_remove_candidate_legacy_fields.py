# Generated manually for 0030 - hard cleanup of Candidate legacy fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0029_resumefile_raw_text'),
    ]

    operations = [
        migrations.DeleteModel(
            name='CandidateSkill',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='current_city',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='target_city',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='highest_degree',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='years_experience',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='skills',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='source',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='source_type',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='source_detail',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='collected_at',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='consent_status',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='consent_version',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='contact_preference',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='note',
        ),
    ]

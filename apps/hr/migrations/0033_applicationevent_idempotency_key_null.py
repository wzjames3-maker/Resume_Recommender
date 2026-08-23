# Generated for P3-2: ApplicationEvent.idempotency_key 改为 NULL 缺省，规避空键唯一约束冲突
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0032_offer_active_unique'),
    ]

    operations = [
        # 空串默认值改为 NULL：PostgreSQL 唯一约束视 NULL 互异，
        # 同 (workspace, application, event_type) 下重复 create 空/缺省键不再 IntegrityError；
        # 约束 hr_application_event_idempotency_uniq 定义不变，仅列可空性变更。
        migrations.AlterField(
            model_name='applicationevent',
            name='idempotency_key',
            field=models.CharField(blank=True, default=None, max_length=128, null=True),
        ),
    ]

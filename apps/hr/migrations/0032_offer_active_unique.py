# Generated for P1-13: Offer 并发唯一约束（同申请至多一条活跃 Offer）
from django.db import migrations, models
import django.db.models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0031_add_trgm_indexes'),
    ]

    operations = [
        # 仅对 SENT 加唯一约束，避免并发双 SENT；DRAFT 允许多条但服务层通过 exists() 挡活跃 Offer（P1-13）
        # 若需严格 DRAFT+SENT 唯一，需将 condition 改为 Q(status__in=['DRAFT','SENT']) 并同步调整测试的直接 ORM 构造
        migrations.AddConstraint(
            model_name='offer',
            constraint=models.UniqueConstraint(
                fields=['workspace_id', 'application'],
                condition=django.db.models.Q(status='SENT'),
                name='hr_unique_active_offer_per_application',
            ),
        ),
    ]

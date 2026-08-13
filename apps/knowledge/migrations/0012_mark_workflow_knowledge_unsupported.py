from django.db import migrations


def forwards(apps, schema_editor):
    Knowledge = apps.get_model("knowledge", "Knowledge")
    for knowledge in Knowledge.objects.filter(type=4).iterator():
        meta = dict(knowledge.meta or {})
        meta["disabled_reason"] = "workflow_knowledge_removed_by_local_core"
        knowledge.meta = meta
        knowledge.save(update_fields=["meta"])


class Migration(migrations.Migration):

    dependencies = [
        ('knowledge', '0011_delete_knowledgeaction'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
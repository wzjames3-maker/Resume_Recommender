from django.db import migrations


def forwards(apps, schema_editor):
    Model = apps.get_model("models_provider", "Model")
    for model in Model.objects.exclude(provider="model_openai_provider").iterator():
        meta = dict(model.meta or {})
        meta["disabled_reason"] = "provider_removed_by_local_core"
        model.status = "ERROR"
        model.meta = meta
        model.save(update_fields=["status", "meta"])


class Migration(migrations.Migration):

    dependencies = [
        ('models_provider', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
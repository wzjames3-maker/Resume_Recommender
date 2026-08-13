from django.db import migrations


def forwards(apps, schema_editor):
    Application = apps.get_model("application", "Application")
    ApplicationVersion = apps.get_model("application", "ApplicationVersion")
    Application.objects.filter(type="WORK_FLOW").update(is_publish=False)
    ApplicationVersion.objects.filter(type="WORK_FLOW").update(
        mcp_enable=False,
        mcp_tool_ids=[],
        mcp_servers={},
        tool_enable=False,
        tool_ids=[],
        skill_tool_ids=[],
    )


class Migration(migrations.Migration):

    dependencies = [
        ('application', '0014_applicationversion_knowledge_ids'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
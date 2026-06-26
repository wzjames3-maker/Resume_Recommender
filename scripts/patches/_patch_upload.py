from pathlib import Path
p = Path('src/api/v1/upload.py')
text = p.read_text(encoding='utf-8')
old = """    except Exception as e:\n        logger.error(f\"简历上传失败: {str(e)}\")\n        return UploadResponse(\n            success=False,\n            message=\"简历上传失败，请稍后重试\",\n        )\n"""
new = """    except Exception as e:\n        import traceback\n\n        logger.error(\n            \"简历上传失败: %s\\n%s\",\n            str(e),\n            traceback.format_exc(),\n        )\n        detail = str(e)\n        return UploadResponse(\n            success=False,\n            message=f\"简历上传失败: {detail}\",\n        )\n"""
if old not in text:
    raise SystemExit('target block not found')
p.write_text(text.replace(old, new), encoding='utf-8')
print('patched src/api/v1/upload.py')

import os

# ====== Add openpyxl to pyproject.toml ======
pyproject_path = r"C:\Users\Administrator\Desktop\简历推荐系统\pyproject.toml"
with open(pyproject_path, "r", encoding="utf-8") as f:
    content = f.read()

if "openpyxl" not in content:
    # Find the pymongo line and add openpyxl after it
    content = content.replace(
        '"pymongo>=4.6.0",',
        '"pymongo>=4.6.0",\n    "openpyxl>=3.1.0",'
    )
    with open(pyproject_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("pyproject.toml: Added openpyxl dependency")
else:
    print("pyproject.toml: openpyxl already present")

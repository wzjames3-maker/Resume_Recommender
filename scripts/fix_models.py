with open("src/resume_store/models.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace('company: str = Field(..., description="公司名称")',
              'company: Optional[str] = Field(None, description="公司名称")')
c = c.replace('school: str = Field(..., description="学校名称")',
              'school: Optional[str] = Field(None, description="学校名称")')
# Also fix name in ProjectEntry
c = c.replace('name: str = Field(..., description="项目名称")',
              'name: Optional[str] = Field(None, description="项目名称")')
with open("src/resume_store/models.py", "w", encoding="utf-8") as f:
    f.write(c)
print("company/school/name -> Optional")

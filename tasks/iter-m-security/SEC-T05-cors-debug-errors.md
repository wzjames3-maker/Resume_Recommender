# SEC-T05: CORS 白名单 + debug 配置化 + 异常信息最小化

## 基本信息
- **对应 Spec**: SEC-REQ-006, SEC-RULE-005/007
- **对应 AC**: AC-SEC-006
- **依赖**: SEC-T04
- **预计工时**: 0.5 天
- **优先级**: P0

## 输入
- `src/api/main.py`（`allow_origins=["*"]`；`app.state.debug = True` 硬编码，忽略 config）
- `src/common/config.py`（`AppSettings.DEBUG` 默认 True；无 CORS_ORIGINS）
- `src/common/errors.py`（generic_exception_handler debug 返回 str(exc)；to_response debug 返回 self.error_detail）

## 输出
- 修改 `src/common/config.py` — AppSettings 新增 CORS_ORIGINS；DEBUG 默认改 False
- 修改 `src/api/main.py` — CORS 与 debug 从配置读取
- 修改 `src/common/errors.py` — 确认非 debug 返回 detail=None
- `tests/unit/test_errors.py` — 补充生产模式测试

## 实现要求
1. `config.py` AppSettings：
   ```python
   CORS_ORIGINS: str = Field(default="", description="允许的 CORS 来源，逗号分隔")
   DEBUG: bool = Field(default=False, description="调试模式")  # 默认改 False
   ```
2. `main.py`：
   ```python
   from src.common.config import get_settings
   settings = get_settings()
   origins = [o.strip() for o in settings.app.CORS_ORIGINS.split(",") if o.strip()] or ["http://localhost:8501"]
   app.add_middleware(
       CORSMiddleware,
       allow_origins=origins,
       allow_credentials=True,
       allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
       allow_headers=["*"],
   )
   app.state.debug = settings.app.DEBUG
   ```
   删除 `allow_origins=["*"]`；删除 `app.state.debug = True`
3. `errors.py`：
   - `generic_exception_handler`：`detail=str(exc) if debug else None`（已存在，确认 debug 来源正确）
   - `AppException.to_response`：`detail=self.error_detail if debug else None`（已存在，确认）
   - 两者 debug 均来自 `request.app.state.debug`

## 验收检查点
- [ ] 代码中无 `allow_origins=["*"]`
- [ ] `main.py` 无 `app.state.debug = True` 硬编码
- [ ] `AppSettings.DEBUG` 默认为 False
- [ ] `DEBUG` 未设置时 `app.state.debug == False`
- [ ] 生产模式 GET /test-error 返回 `detail: null`
- [ ] 生产模式 500 响应不含文件路径/堆栈
- [ ] CORS_ORIGINS 设置后预检 OPTIONS 正常
- [ ] `tests/unit/test_errors.py` 生产模式测试通过

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED

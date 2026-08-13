import pytest

from app.models import ResumeIR
from app.services.resume.ir_storage import decrypt_resume_ir, encrypt_resume_ir


def test_encrypt_resume_ir_does_not_keep_plaintext():
    plain = "姓名：张三\n电话：13800000000"
    encrypted = encrypt_resume_ir(plain)
    assert encrypted != plain
    assert plain not in encrypted


def test_decrypt_resume_ir_prefers_ciphertext():
    ir = ResumeIR(run_id="ir-1", content="old plain", content_enc=encrypt_resume_ir("new plain"), valid_chars=9)
    assert decrypt_resume_ir(ir) == "new plain"


def test_decrypt_resume_ir_falls_back_to_legacy_plaintext():
    ir = ResumeIR(run_id="ir-2", content="legacy plain", content_enc=None, valid_chars=12)
    assert decrypt_resume_ir(ir) == "legacy plain"


def test_decrypt_resume_ir_rejects_missing_content():
    ir = ResumeIR(run_id="ir-3", content=None, content_enc=None, valid_chars=0)
    with pytest.raises(ValueError, match="缺少 IR 内容"):
        decrypt_resume_ir(ir)
from app.models import ResumeIR
from app.services.crypto import decrypt_secret, encrypt_secret


def encrypt_resume_ir(plain: str) -> str:
    return encrypt_secret(plain)


def decrypt_resume_ir(ir: ResumeIR) -> str:
    if ir.content_enc:
        return decrypt_secret(ir.content_enc)
    if ir.content is not None:
        return ir.content
    raise ValueError(f"ResumeIR {ir.run_id} 缺少 IR 内容")
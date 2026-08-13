import hashlib

_FULL_TO_HALF = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９"}


def _to_half(text: str) -> str:
    return text.translate(_FULL_TO_HALF)


def normalize_phone(phone: str) -> str:
    p = _to_half(phone)
    p = p.replace("+86", "").replace(" ", "").replace("-", "")
    return p


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity_hashes(phone: str | None, email: str | None) -> tuple[str | None, str | None]:
    phone_hash = hash_identity(normalize_phone(phone)) if phone else None
    email_hash = hash_identity(normalize_email(email)) if email else None
    return phone_hash, email_hash


def normalize_skills(skills: list | None) -> list | None:
    """skills 无序集合归一化（spec §3.6）：去空白、去重、保序；canonical 别名词典随评测 bundle 冻结。"""
    if skills is None:
        return None
    seen: list[str] = []
    for skill in skills:
        if not isinstance(skill, str):
            continue
        norm = " ".join(skill.split())
        if norm and norm not in seen:
            seen.append(norm)
    return seen
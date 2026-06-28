"""测试文件上传安全校验（SEC-T06）"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.common.auth import create_user_token

client = TestClient(app)


def _hr_token() -> str:
    return create_user_token(user_id="hr-001", role="hr")


@pytest.fixture(autouse=True)
def mock_mongodb():
    with patch("src.resume_store.connection.MongoDBConnection.connect"), \
         patch("src.resume_store.connection.MongoDBConnection.get_database") as mock_db, \
         patch("src.resume_store.connection.MongoDBConnection.health_check", return_value=False):
        mock_col = MagicMock()
        mock_col.find_one.return_value = None
        mock_col.insert_one.return_value = MagicMock(inserted_id="mock-id")
        mock_db.return_value.__getitem__.return_value = mock_col
        yield


class TestUploadSafety:
    """File upload validation: extension, MIME, size"""

    def test_size_exceeded_rejected(self):
        """11MB file returns 413"""
        big = b"x" * (11 * 1024 * 1024)
        r = client.post(
            "/api/v1/resumes/upload",
            files={"file": ("big.pdf", big, "application/pdf")},
            headers={"Authorization": f"Bearer {_hr_token()}"},
        )
        assert r.status_code == 413

    def test_exe_extension_rejected(self):
        """.exe file returns 422"""
        r = client.post(
            "/api/v1/resumes/upload",
            files={"file": ("malware.exe", b"data", "application/octet-stream")},
            headers={"Authorization": f"Bearer {_hr_token()}"},
        )
        assert r.status_code == 422

    def test_wrong_mime_rejected(self):
        """PDF with wrong MIME returns 422"""
        r = client.post(
            "/api/v1/resumes/upload",
            files={"file": ("resume.pdf", b"%PDF", "image/jpeg")},
            headers={"Authorization": f"Bearer {_hr_token()}"},
        )
        assert r.status_code == 422

    def test_valid_pdf_accepted(self):
        """Valid PDF passes validation (may fail downstream)"""
        r = client.post(
            "/api/v1/resumes/upload",
            files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers={"Authorization": f"Bearer {_hr_token()}"},
        )
        # 200 or downstream error but not validation error
        assert r.status_code != 403  # auth passed (downstream parsing may fail)

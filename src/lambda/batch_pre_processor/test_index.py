"""Unit tests for batch_pre_processor Lambda function."""

import io
import os
import sys
import zipfile
from unittest.mock import MagicMock, patch

import pytest

# Mock idp_common before importing index
sys.modules["idp_common"] = MagicMock()
sys.modules["idp_common.dynamodb"] = MagicMock()
sys.modules["idp_common.dynamodb.job_service"] = MagicMock()


@pytest.fixture(autouse=True)
def mock_env():
    """Set up environment variables for tests."""
    env_vars = {
        "INPUT_BUCKET_NAME": "test-input-bucket",
        "TRACKING_TABLE": "test-table",
        "LOG_LEVEL": "INFO",
    }
    with patch.dict(os.environ, env_vars):
        yield


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch("index.s3") as mock:
        yield mock


@pytest.fixture
def mock_job_service():
    """Mock job service."""
    mock_svc = MagicMock()
    with patch("index.job_service", mock_svc):
        yield mock_svc


def create_test_zip(files: dict[str, bytes]) -> io.BytesIO:
    """Create an in-memory ZIP file with given files."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    zip_buffer.seek(0)
    return zip_buffer


def make_event(bucket: str, key: str) -> dict:
    """Create an EventBridge S3 event."""
    return {
        "detail": {
            "bucket": {"name": bucket},
            "object": {"key": key},
        }
    }


class TestHandler:
    """Tests for handler function."""

    def test_handler_processes_zip(self, mock_s3, mock_job_service):
        """Test handler processes ZIP and updates job record."""
        from index import handler

        zip_content = create_test_zip({"doc1.pdf": b"pdf1", "doc2.pdf": b"pdf2"})
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        event = make_event("staging-bucket", "jobs/test-uuid/archive.zip")

        response = handler(event, None)

        assert response["statusCode"] == 200
        assert mock_s3.put_object.call_count == 2
        mock_job_service.update_job_files.assert_called_once()
        call_args = mock_job_service.update_job_files.call_args
        assert call_args[0][0] == "test-uuid"
        assert call_args[0][1] == {"doc1.pdf": "IN_PROGRESS", "doc2.pdf": "IN_PROGRESS"}

    def test_handler_skips_non_zip(self, mock_s3, mock_job_service):
        """Test handler skips non-ZIP files."""
        from index import handler

        event = make_event("staging-bucket", "jobs/test-uuid/document.pdf")

        response = handler(event, None)

        assert response["statusCode"] == 200
        mock_s3.download_fileobj.assert_not_called()
        mock_job_service.update_job_files.assert_not_called()

    def test_handler_skips_invalid_key_format(self, mock_s3, mock_job_service):
        """Test handler skips keys with invalid format."""
        from index import handler

        event = make_event("staging-bucket", "invalid/path.zip")

        response = handler(event, None)

        assert response["statusCode"] == 200
        mock_s3.download_fileobj.assert_not_called()


class TestExtractAndUpload:
    """Tests for extract_and_upload function."""

    def test_extracts_files_to_input_bucket(self, mock_s3):
        """Test files are extracted and uploaded to input bucket."""
        from index import extract_and_upload

        zip_content = create_test_zip({"file1.pdf": b"content1", "file2.pdf": b"content2"})
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        files = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert set(files) == {"file1.pdf", "file2.pdf"}
        assert mock_s3.put_object.call_count == 2

        # Verify upload keys
        calls = mock_s3.put_object.call_args_list
        keys = {c[1]["Key"] for c in calls}
        assert keys == {"jobs/uuid/file1.pdf", "jobs/uuid/file2.pdf"}

    def test_skips_directories(self, mock_s3):
        """Test directories in ZIP are skipped."""
        from index import extract_and_upload

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("subdir/", "")
            zf.writestr("subdir/file.pdf", b"content")
        zip_buffer.seek(0)

        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_buffer.read())

        files = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert files == ["file.pdf"]
        assert mock_s3.put_object.call_count == 1

    def test_flattens_nested_paths(self, mock_s3):
        """Test nested paths are flattened to basename."""
        from index import extract_and_upload

        zip_content = create_test_zip({"folder/subfolder/doc.pdf": b"content"})
        mock_s3.download_fileobj.side_effect = lambda b, k, f: f.write(zip_content.read())

        files = extract_and_upload("staging", "jobs/uuid/test.zip", "uuid")

        assert files == ["doc.pdf"]
        call_args = mock_s3.put_object.call_args
        assert call_args[1]["Key"] == "jobs/uuid/doc.pdf"

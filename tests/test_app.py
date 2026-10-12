"""Tests use simulated Meta responses; real Meta OAuth requires user's app credentials."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_DB_DIR = tempfile.TemporaryDirectory()
os.environ.update({
    "FLASK_SECRET_KEY": "a-long-test-secret-session-key-for-only-tests-2026",
    "ADMIN_PASSWORD": "a-good-testing-password-2026",
    "INSTAGRAM_APP_ID": "test-app-id",
    "INSTAGRAM_APP_SECRET": "test-app-secret",
    "INSTAGRAM_REDIRECT_URI": "https://example.com/auth/callback",
    "DATABASE_PATH": str(Path(TEST_DB_DIR.name) / "test.sqlite3"),
})
import app as pickday


class Tests(unittest.TestCase):
    def setUp(self):
        pickday.app.config["TESTING"] = True
        self.client = pickday.app.test_client()
        with pickday.db_connection() as conn:
            conn.execute("DELETE FROM account")

    def login(self):
        status = self.client.get("/api/status").get_json()
        response = self.client.post("/api/login", json={"password": "a-good-testing-password-2026"}, headers={"X-CSRF-Token": status["csrf"]})
        self.assertEqual(response.status_code, 200)
        return status["csrf"]

    def test_shortcode_validation(self):
        self.assertEqual(pickday.shortcode_for_url("https://www.instagram.com/reel/Ab_12-C/?igsh=x"), "Ab_12-C")
        self.assertEqual(pickday.shortcode_for_url("https://instagram.com/p/12345/"), "12345")
        for invalid in ["http://instagram.com/p/12345", "https://evil.com/p/12345", "https://www.instagram.com.evil.com/p/12345", "https://www.instagram.com/profile", "file:///etc/passwd"]:
            self.assertIsNone(pickday.shortcode_for_url(invalid))

    def test_auth_required_and_wrong_password(self):
        self.assertEqual(self.client.post("/api/import",json={"url":"x"}).status_code, 401)
        csrf = self.client.get("/api/status").get_json()["csrf"]
        bad = self.client.post("/api/login",json={"password":"wrong"}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(bad.status_code,401)

    def test_login_disconnect_csrf(self):
        self.login()
        self.assertEqual(self.client.post("/api/disconnect").status_code, 403)
        csrf = self.client.get("/api/status").get_json()["csrf"]
        self.assertEqual(self.client.post("/api/disconnect", headers={"X-CSRF-Token":csrf}).status_code,200)

    def test_pagination_comments_and_deduplication(self):
        calls = []
        def fake_api(url, token, params):
            calls.append((url, params.copy()))
            if params.get("after") == "second":
                return {"data": [{"id":"10001","username":"amy","text":"repeat"},{"id":"10002","username":"jane","text":"hi"}]}
            return {"data":[{"id":"10001","username":"amy","text":"hi"}],"paging":{"cursors":{"after":"second"}}}
        with patch.object(pickday,"api_get",side_effect=fake_api):
            result=pickday.list_comments("123456789", "test-token")
        self.assertEqual(len(result),2)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1][1]["after"],"second")

    def test_import_owned_post_end_to_end(self):
        csrf = self.login()
        pickday.save_account("123456789", "organizer", "test-token", 5184000)
        fake_post={"id":"17890000001","permalink":"https://www.instagram.com/p/HELLO123/"}
        fake_comments=[
            {"id":"1","username":"alice","text":"신청합니다","timestamp":""},
            {"id":"2","username":"alice","text":"또 신청해요","timestamp":""},
            {"id":"3","username":"bob","text":"참여!","timestamp":""},
            {"id":"4","username":"","text":"불완전 댓글","timestamp":""},
        ]
        with patch.object(pickday,"get_owned_post",return_value=fake_post),patch.object(pickday,"list_comments",return_value=fake_comments):
            reply=self.client.post("/api/import",json={"url":"https://www.instagram.com/p/HELLO123/"}, headers={"X-CSRF-Token":csrf})
        self.assertEqual(reply.status_code,200)
        result=reply.get_json()
        self.assertEqual(result["stats"], {"total":4,"accounts":2,"missing_username":1})
        self.assertEqual(len(result["snapshot_sha256"]),64)
        self.assertIn("최상위",result["scope"])

    def test_import_rejects_unrecognized_url(self):
        csrf = self.login()
        reply=self.client.post("/api/import",json={"url":"https://not-instagram.com/p/HELLO123"},headers={"X-CSRF-Token":csrf})
        self.assertEqual(reply.status_code,400)


if __name__ == '__main__': unittest.main()

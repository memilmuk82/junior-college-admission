import unittest

from app import create_app


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.client = create_app({"TESTING": True, "SECRET_KEY": "test"}).test_client()

    def test_index_renders_current_phase_screen(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("입력 게이트웨이 완료", response.get_data(as_text=True))
        self.assertIn("지원자격 판정과 성적 계산은", response.get_data(as_text=True))
        self.assertIn('media="print"', response.get_data(as_text=True))

    def test_health_endpoint(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()

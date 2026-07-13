import unittest

from app import create_app


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.client = create_app({"TESTING": True, "SECRET_KEY": "test"}).test_client()

    def test_index_renders_current_phase_screen(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("지원자격부터 확인하는 상담 흐름", body)
        self.assertIn("교직원 상담 시작", body)
        self.assertIn("허용된 경우에만 성적 범위·환산점수", body)
        self.assertIn('media="print"', body)

    def test_health_endpoint(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()

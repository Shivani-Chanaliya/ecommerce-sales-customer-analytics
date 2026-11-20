import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StreamlitDashboardTests(unittest.TestCase):
    def test_dashboard_renders_and_country_filter_runs(self):
        app = AppTest.from_file(
            str(PROJECT_ROOT / "streamlit_app.py"),
            default_timeout=180,
        ).run()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual([element.value for element in app.title], ["E-Commerce Sales Analytics"])
        self.assertEqual(len(app.tabs), 6)

        country_filter = next(
            element for element in app.selectbox if element.label == "Country"
        )
        country_filter.select("France").run()

        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()

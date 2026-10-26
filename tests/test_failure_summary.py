import unittest
from src.automation import summarize_failure


class FailureSummaryTest(unittest.TestCase):
    def test_multi_source_job_names_only_the_failing_ones(self):
        result = {"status": "partial", "agendas": [{"source": "venue_ia_ok", "status": "completed", "rows_received": 42},
                                                   {"source": "venue_ia_mal", "status": "failed", "error": "HTTP 403"}]}
        self.assertEqual(summarize_failure(result), "1 de 2 fallan · venue_ia_mal: HTTP 403")

    def test_single_source_uses_error_or_warnings(self):
        self.assertEqual(summarize_failure({"status": "failed", "error": "HTTP Error 500"}), "HTTP Error 500")
        self.assertEqual(summarize_failure({"status": "partial", "http_status": 500, "warnings": ["HTTP 500 tras reintentos"]}), "HTTP 500 tras reintentos")


if __name__ == "__main__":
    unittest.main()

import ssl
import unittest
from unittest.mock import patch
from src.network import tls_context


class NetworkTests(unittest.TestCase):
    def test_context_keeps_certificate_verification_enabled(self):
        with patch('src.network.ssl.get_default_verify_paths') as paths:
            paths.return_value=type('Paths',(),{'cafile':'/missing-ca.pem'})()
            context=tls_context()
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == '__main__': unittest.main()

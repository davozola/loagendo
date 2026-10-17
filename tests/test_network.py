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

    def test_ascii_url_encodes_copyright_and_accents_but_keeps_encoded_and_reserved(self):
        from src.network import ascii_url
        self.assertEqual(ascii_url('https://img.macba.cat/a/Meier-1987-©-Partners.jpg'), 'https://img.macba.cat/a/Meier-1987-%C2%A9-Partners.jpg')
        self.assertEqual(ascii_url('https://www.auditori.cat/wp/Orquestra Simfònica.jpg?w=800&h=600'), 'https://www.auditori.cat/wp/Orquestra%20Simf%C3%B2nica.jpg?w=800&h=600')
        already = 'https://x.test/a%20b/c.jpg?q=%C3%A9&x=1'
        self.assertEqual(ascii_url(already), already)
        self.assertEqual(ascii_url('https://música.example/x.jpg'), 'https://xn--msica-7ua.example/x.jpg')
        self.assertEqual(ascii_url('https://x.test:8443/a.jpg'), 'https://x.test:8443/a.jpg')

    def test_encoding_failures_are_retried_after_the_fix(self):
        from src.media import TRANSIENT_DOWNLOAD_ERRORS
        self.assertTrue(any(e in "'ascii' codec can't encode character '\\xa9' in position 59" for e in TRANSIENT_DOWNLOAD_ERRORS))


if __name__ == '__main__': unittest.main()

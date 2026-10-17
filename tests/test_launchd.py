import plistlib
import unittest
from pathlib import Path
from src.launchd import LABEL, plist_data


class LaunchdTests(unittest.TestCase):
    def test_rendered_plist_runs_local_engine_only(self):
        value=plist_data(Path('/tmp/loagendo'),900)
        self.assertEqual(value['Label'],LABEL)
        self.assertEqual(value['ProgramArguments'][-1],'--run-jobs')
        self.assertEqual(plistlib.loads(plistlib.dumps(value))['StartInterval'],900)
        with self.assertRaises(ValueError): plist_data(Path('/tmp/loagendo'),60)


if __name__ == '__main__': unittest.main()

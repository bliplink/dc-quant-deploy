import os
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/build-mac-common-candidate.sh'


@unittest.skipUnless(platform.system() == 'Darwin', 'Mac candidate builder')
class CommonCandidateSourceTest(unittest.TestCase):
    def test_dirty_head_stops_before_creating_a_candidate(self):
        for change in ('unstaged', 'staged', 'untracked'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'source'
                source.mkdir()
                subprocess.run(['git', 'init', '-q', str(source)], check=True)
                (source / 'src').mkdir()
                original = source / 'src/Original.java'
                original.write_text('original fixture\n')
                subprocess.run(['git', '-C', str(source), 'add', 'src'], check=True)
                subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture',
                                '-c', 'user.email=fixture@acceptance.invalid',
                                'commit', '-qm', 'fixture'], check=True)
                if change == 'untracked':
                    (source / 'src/New.java').write_text('new fixture\n')
                else:
                    original.write_text('changed fixture\n')
                    if change == 'staged':
                        subprocess.run(['git', '-C', str(source), 'add', 'src'], check=True)
                output = root / 'candidate'
                environment = dict(os.environ, MAC_DEMO_COMMON_SOURCE=str(source),
                                   MAC_DEMO_MAVEN='/usr/bin/false')
                result = subprocess.run(['bash', str(SCRIPT), 'HEAD', str(output)],
                                        env=environment, text=True, capture_output=True)
                self.assertEqual(2, result.returncode)
                self.assertIn('uncommitted source or tests', result.stderr)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

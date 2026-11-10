"""Read-only verification of external imported source and its exact compiled artifact."""

import base64
import hashlib
from pathlib import PurePosixPath
import re
import shlex


def compare_stored_source(uploaded, stored, jar_sha256, candidate_checksum):
    if not re.fullmatch(r'[0-9a-f]{64}', str(jar_sha256)) or jar_sha256 != candidate_checksum:
        raise ValueError('compiled JAR does not match candidate checksum')
    if stored == uploaded:
        normalization = 'exact'
    elif stored == uploaded.strip(b' \t\r\n'):
        normalization = 'outer_ascii_whitespace_trim'
    else:
        raise ValueError('stored source differs beyond allowed outer whitespace normalization')
    return {'uploaded_source_sha256': hashlib.sha256(uploaded).hexdigest(),
            'stored_source_sha256': hashlib.sha256(stored).hexdigest(),
            'uploaded_source_bytes': len(uploaded), 'stored_source_bytes': len(stored),
            'source_normalization': normalization, 'source_tokens_unchanged': True,
            'server_jar_sha256': jar_sha256, 'candidate_checksum_matches': True,
            'compiled_source_verified': True}


def compiled_artifact_audit(client, candidate, request):
    name, version = candidate.get('strategy_name'), str(candidate.get('strategy_version') or '')
    if name != request['strategyName'] or not re.fullmatch(r'[a-zA-Z0-9_-]+', version):
        raise ValueError('compiled candidate identity mismatch')
    artifact = PurePosixPath(str(candidate.get('artifact_uri') or ''))
    source = PurePosixPath(str(candidate.get('java_source_path') or ''))
    entry = str(candidate.get('entry_class') or '')
    if (not artifact.is_absolute() or artifact.name != 'strategy.jar' or artifact.parent.name != version
            or artifact.parent.parent.name != name or '..' in artifact.parts
            or not re.fullmatch(r'[a-zA-Z_$][a-zA-Z0-9_$]*(\.[a-zA-Z_$][a-zA-Z0-9_$]*)*', entry)
            or source != artifact.parent / 'src' / (entry.replace('.', '/') + '.java')):
        raise ValueError('compiled source/artifact path is outside the exact candidate version')

    def remote(command):
        _, stdout, stderr = client.exec_command(command, timeout=60)
        data = stdout.read()
        error = stderr.read().decode('utf-8', 'replace')
        if stdout.channel.recv_exit_status():
            raise ValueError('read-only compiled artifact audit failed: ' + error[:1000])
        return data

    stored = remote('sudo docker exec dc-indsvr cat ' + shlex.quote(str(source)))
    jar = remote('sudo docker exec dc-indsvr sha256sum ' + shlex.quote(str(artifact))).decode('ascii').split()[0]
    uploaded = base64.b64decode(request['javaSourceBase64'], validate=True)
    return compare_stored_source(uploaded, stored, jar, candidate.get('checksum'))

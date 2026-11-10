"""Exact class-file equality modulo declared package/label UTF8 constants; never a financial qualification."""
import hashlib
import re
import struct
import zipfile


def identity_prefix(name):
    if not isinstance(name, str) or not re.fullmatch(r'catalog_[a-z0-9_]{1,180}', name):
        raise ValueError('explicit exported ASCII strategy identity required')
    return 'com/app/dc/generated/autogen/' + name + '/v1/'


def neutral_source(source, name):
    identity_prefix(name)
    package = 'package com.app.dc.generated.autogen.' + name + '.v1;'
    label = 'private static final String STRATEGY_NAME = "' + name + '";'
    if (source.count(package) != 1 or source.count(label) != 1 or source.count(name) != 2
            or source.count('STRATEGY_NAME') != 2 or source.count('signal.strategyName = STRATEGY_NAME;') != 1):
        raise ValueError('identity must occur only in the package and returned strategy label')
    return source.replace(package, 'package com.app.dc.generated.autogen.__IDENTITY__.v1;', 1).replace(
        label, 'private static final String STRATEGY_NAME = "__IDENTITY__";', 1)


def require_source_identity_equivalence(canonical_source, canonical_name, source, name):
    if neutral_source(canonical_source, canonical_name) != neutral_source(source, name):
        raise ValueError('source differs beyond the two declared identity substitutions')


def normalize_class(data, name):
    """Keep every non-UTF8 CP byte and the entire remaining class file EXACTLY unchanged."""
    prefix = identity_prefix(name).encode('ascii')
    neutral = b'com/app/dc/generated/autogen/__IDENTITY__/v1/'
    if len(data) < 24 or data[:4] != b'\xca\xfe\xba\xbe':
        raise ValueError('complete JVM class file required')
    count = struct.unpack_from('>H', data, 8)[0]
    if count < 1: raise ValueError('invalid constant-pool count')
    result = [data[:10]]; offset, index = 10, 1
    widths = {3: 4, 4: 4, 5: 8, 6: 8, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4,
              15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2}
    while index < count:
        if offset >= len(data): raise ValueError('truncated constant-pool tag')
        start = offset; tag = data[offset]; offset += 1
        if tag == 1:
            if offset + 2 > len(data): raise ValueError('truncated UTF8 length')
            length = struct.unpack_from('>H', data, offset)[0]; offset += 2
            if offset + length > len(data): raise ValueError('truncated UTF8 payload')
            value = data[offset:offset + length]; offset += length
            # JVM modified UTF8 outside these ASCII sequences remains untouched.
            if value == name.encode('ascii'): value = b'__IDENTITY__'
            value = value.replace(prefix, neutral).replace(prefix.replace(b'/', b'.'), neutral.replace(b'/', b'.'))
            if len(value) > 65535: raise ValueError('normalized UTF8 constant too long')
            result.append(b'\x01' + struct.pack('>H', len(value)) + value)
        else:
            if tag not in widths: raise ValueError('unknown JVM constant-pool tag: ' + str(tag))
            width = widths[tag]
            if offset + width > len(data): raise ValueError('truncated constant-pool payload')
            if tag in (5, 6):
                if index + 1 >= count: raise ValueError('wide constant has no reserved second slot')
                index += 1
            offset += width; result.append(data[start:offset])
        index += 1
    if len(data) - offset < 14: raise ValueError('truncated class structure after constant pool')
    result.append(data[offset:])
    return b''.join(result)


def jar_class_proof(artifact, name):
    prefix = identity_prefix(name); classes, manifest = {}, None
    with zipfile.ZipFile(artifact) as archive:
        entries = archive.infolist()
        if len({entry.filename for entry in entries}) != len(entries): raise ValueError('duplicate JAR entries')
        for entry in entries:
            if entry.is_dir(): continue
            if entry.filename == 'META-INF/MANIFEST.MF':
                manifest = hashlib.sha256(archive.read(entry)).hexdigest(); continue
            if not entry.filename.startswith(prefix) or not entry.filename.endswith('.class'):
                raise ValueError('unexpected non-class or external package entry: ' + entry.filename)
            relative = entry.filename[len(prefix):]
            if not re.fullmatch(r'GeneratedStrategy(?:\$[A-Za-z0-9_$]+)?\.class', relative):
                raise ValueError('unexpected generated class name: ' + relative)
            normalized = normalize_class(archive.read(entry), name)
            classes[relative] = hashlib.sha256(normalized).hexdigest()
    if 'GeneratedStrategy.class' not in classes or manifest is None: raise ValueError('main class and manifest required')
    return {'normalized_class_sha256': classes, 'manifest_content_sha256': manifest}


def require_jar_identity_equivalence(canonical_artifact, canonical_name, artifact, name):
    canonical = jar_class_proof(canonical_artifact, canonical_name)
    actual = jar_class_proof(artifact, name)
    if canonical != actual:
        raise ValueError('compiled class/manifest bytes differ beyond declared identity UTF8 constants')
    return actual

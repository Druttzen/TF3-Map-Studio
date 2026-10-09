"""Exact legacy helper profiles; unfamiliar code remains a migration blocker."""
import hashlib
from pathlib import Path

from .filesystem import linked


HELPER_DIGESTS = {
    'parambuilder_v1_1': '38e69b27f76f154ac9f2ca2eb528cc85eb5f7252f78683b9c19b4f41dedcdca9',
    'bbs2util': '80b7d45c5df3adefcea88226e80e463300b848a968ad1c5b8ff99e9430fc1918',
    'soundeffectsutil2': '66370d4962c3fd8436197af6184b4eeb5635449b8e1ef75da31156b882a02f10',
}

# Keep the original identities available to callers while recognizing separately
# audited editions. A matching filename alone never establishes equivalence.
HELPER_DIGEST_VARIANTS = {
    'bbs2util': frozenset({
        '2377f9c3ceeb9c782b4ae654308be7c166570b872a6553cd49eb01e1b2d0f027',
    }),
    'soundeffectsutil': frozenset({
        'a5f00cd3e74bcd6e29f4242a43e52ee38ed15e10eac8f6eb4ba99e196a0281e0',
    }),
}


def helper_digest_verified(module: str, digest: str) -> bool:
    return (isinstance(digest, str) and
            (digest == HELPER_DIGESTS.get(module) or
             digest in HELPER_DIGEST_VARIANTS.get(module, ())))


def verified_legacy_helpers(root: Path) -> dict[str, Path]:
    result = {}
    scripts = root/'res/scripts'
    if not scripts.is_dir():
        return result
    for path in scripts.iterdir():
        helper = path.stem.lower()
        if (path.suffix.lower() == '.lua'
                and not linked(path) and path.is_file()
                and helper_digest_verified(helper, hashlib.sha256(path.read_bytes()).hexdigest())):
            result[helper] = path
    return result

from peakstone.engine import versions


def test_version_key_ordering():
    assert versions.version_key("0.2.0") > versions.version_key("0.1.9")
    assert versions.version_key("1.0") > versions.version_key("0.9.9")
    assert versions.version_key("0.2.0rc1") == (0, 2, 0)   # pre-release suffix ignored
    assert versions.version_key(None) == (0,)


def test_is_outdated():
    assert versions.is_outdated("0.1.0", "0.2.0")
    assert not versions.is_outdated("0.2.0", "0.2.0")
    assert not versions.is_outdated("0.3.0", "0.2.0")


def test_pkg_version_is_string():
    assert isinstance(versions.pkg_version(), str)

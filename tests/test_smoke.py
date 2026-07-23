import isox


def test_module_imports_and_pure_function_runs():
    assert isox.is_unsafe_filename("../evil.iso")
    assert not isox.is_unsafe_filename("archlinux-x86_64.iso")

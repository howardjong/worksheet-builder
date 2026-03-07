def test_packages_importable() -> None:
    """Verify all pipeline packages are importable."""
    import adapt
    import capture
    import companion
    import extract
    import render
    import skill
    import theme
    import validate

    assert capture is not None
    assert extract is not None
    assert skill is not None
    assert adapt is not None
    assert theme is not None
    assert companion is not None
    assert render is not None
    assert validate is not None

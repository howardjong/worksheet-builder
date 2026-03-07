def test_packages_importable() -> None:
    """Verify all pipeline packages are importable."""
    import capture
    import extract
    import skill
    import adapt
    import theme
    import companion
    import render
    import validate

    assert capture is not None
    assert extract is not None
    assert skill is not None
    assert adapt is not None
    assert theme is not None
    assert companion is not None
    assert render is not None
    assert validate is not None

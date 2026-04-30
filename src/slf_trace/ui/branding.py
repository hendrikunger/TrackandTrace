from importlib import resources


def load_logo_svg() -> str:
    asset = resources.files("slf_trace.ui.assets").joinpath("SLF-logo-bg-white.svg")
    return asset.read_text(encoding="utf-8")

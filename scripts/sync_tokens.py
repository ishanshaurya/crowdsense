"""Write design/tokens.json into the chat CSS and the Streamlit theme; `--check` only compares.

    uv run python -m scripts.sync_tokens          # rewrite the generated blocks
    uv run python -m scripts.sync_tokens --check  # exit 1 if a file differs from tokens.json

CSS cannot import a shared file and config.toml is static, so tokens.json is the one place a
value is edited and both consumers are generated from it. Only the text between the
`tokens:start` and `tokens:end` markers is replaced.
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "design" / "tokens.json"
CSS = ROOT / "api" / "static" / "app.css"
THEME = ROOT / ".streamlit" / "config.toml"
CSS_GROUPS = ("color", "font", "radius")


def css_block(tokens: dict[str, Any]) -> str:
    lines = [
        f"  --{group}-{name}: {value};"
        for group in CSS_GROUPS
        for name, value in tokens[group].items()
    ]
    return ":root {\n" + "\n".join(lines) + "\n}"


def theme_block(tokens: dict[str, Any]) -> str:
    lines = ["[theme]", 'base = "light"']
    lines += [f'{key} = "{value}"' for key, value in tokens["streamlitTheme"].items()]
    return "\n".join(lines)


def replace_block(text: str, block: str, open_mark: str, close_mark: str) -> str:
    pattern = re.compile(re.escape(open_mark) + r".*?" + re.escape(close_mark), re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(f"markers {open_mark!r} .. {close_mark!r} missing")
    return pattern.sub(lambda _: f"{open_mark}\n{block}\n{close_mark}", text, count=1)


def render(tokens: dict[str, Any], css: str, theme: str) -> tuple[str, str]:
    return (
        replace_block(css, css_block(tokens), "/* tokens:start */", "/* tokens:end */"),
        replace_block(theme, theme_block(tokens), "# tokens:start", "# tokens:end"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of rewriting")
    args = parser.parse_args(argv)
    tokens = json.loads(TOKENS.read_text())
    css, theme = CSS.read_text(), THEME.read_text()
    new_css, new_theme = render(tokens, css, theme)
    if args.check:
        stale = [
            p.name for p, old, new in ((CSS, css, new_css), (THEME, theme, new_theme)) if old != new
        ]
        if stale:
            sys.stderr.write(f"out of sync with design/tokens.json: {', '.join(stale)}\n")
            return 1
        return 0
    CSS.write_text(new_css)
    THEME.write_text(new_theme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

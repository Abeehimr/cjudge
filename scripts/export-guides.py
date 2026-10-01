"""Export guide PDFs through HTML with embedded screenshots (LibreOffice required)."""

import base64
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
GUIDES = ROOT / "docs" / "guides"


def embed_image(match: re.Match[str]) -> str:
    tag = match[0]
    source = re.search(r'src="([^"]+)"', tag)
    assert source is not None
    path = Path(unquote(urlparse(source[1]).path)).resolve()
    if not path.is_relative_to(GUIDES / "imgs"):
        raise ValueError(f"Image outside guide assets: {path}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    tag = tag.replace(source[0], f'src="data:image/png;base64,{data}"')
    width = re.search(r'width="(\d+)"', tag)
    height = re.search(r'height="(\d+)"', tag)
    if width and height:
        tag = tag.replace(width[0], 'width="640"').replace(
            height[0], f'height="{round(int(height[1]) * 640 / int(width[1]))}"'
        )
    return tag


def main() -> None:
    output = GUIDES / "pdf"
    output.mkdir(exist_ok=True)
    sources = [GUIDES / "student.md", GUIDES / "ta.md"]
    with tempfile.TemporaryDirectory(prefix="cjudge-guides-") as temporary:
        work = Path(temporary)
        command = ["libreoffice", f"-env:UserInstallation={(work / 'profile').as_uri()}", "--headless"]
        subprocess.run(command + ["--convert-to", "html", "--outdir", str(work), *map(str, sources)], check=True)
        html_files = [work / source.with_suffix(".html").name for source in sources]
        for html_file in html_files:
            content, count = re.subn(r'<img\b[^>]*>', embed_image, html_file.read_text())
            if not count:
                raise ValueError(f"No screenshots exported: {html_file.name}")
            html_file.write_text(content)
        subprocess.run(command + ["--convert-to", "pdf", "--outdir", str(output), *map(str, html_files)], check=True)
    for source in sources:
        pdf = output / source.with_suffix(".pdf").name
        if not pdf.is_file():
            raise RuntimeError(f"PDF not generated: {pdf}")
        print(pdf)


if __name__ == "__main__":
    main()

"""Build a blank, self-contained HTML report for JSON exports from Altegio MCP."""
import argparse
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    html = (ROOT / 'dashboards/index.html').read_text(encoding='utf-8')
    seed = re.search(r'^let DB=(.*);$', html, re.M)
    data = json.loads(seed.group(1))
    if data.get('clients') or data.get('location'):
        raise ValueError('The shared template must not contain a salon snapshot')
    def inline(match):
        name = match.group(1)
        path = (ROOT / 'dashboards' / name).resolve()
        if path.parent != ROOT / 'dashboards':
            raise ValueError('Unexpected script path')
        source = path.read_text(encoding='utf-8')
        source = source.replace('Добавить в категорию клиентов Altegio', 'Как добавить через чат').replace('Add to an Altegio client category', 'How to add via chat')
        return '<script>\n' + source.replace('</script', '<\\/script') + '\n</script>'
    html = re.sub(r'<script src="([^"]+)"></script>', inline, html)
    bootstrap = (ROOT / 'dashboards/mcp-offline.js').read_text(encoding='utf-8')
    start = html.index('const initialLoad=initializeLocations();')
    end = html.index('</script>', start)
    html = html[:start] + bootstrap + '\ninitializeMcpReport();\n' + html[end:]
    policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data: blob:; connect-src \'none\'; base-uri \'none\'; form-action \'none\'">'
    html = html.replace('<head>', '<head>\n' + policy)
    html = html.replace('</style>', '.mailing-panel,.mailing-new{display:none!important}</style>')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')
    instructions = ROOT / 'MCP_START_RU.md'
    archive = output.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(output, 'altegio-report-mcp.html')
        bundle.write(instructions, 'MCP_START_RU.md')
    print(json.dumps({'html':str(output.resolve()),'archive':str(archive.resolve()),'baked_clients':0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)

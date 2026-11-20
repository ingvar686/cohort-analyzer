"""Altegio Analytics edition for clients: cohorts and upsell audiences."""

import re

from desktop import DesktopApplication, main


class ClientDesktopApplication(DesktopApplication):
    app_id = 'altegio-analytics-client'
    name = 'Altegio Analytics'
    profile_name = 'AltegioAnalyticsClient'
    preferred_port = 9474
    public_assets = {'index.html', 'upsell.js', 'monthly-budgets.js',
                     'campaign-comparison.js', 'desktop-bootstrap.js'}
    has_mailings = False

    @classmethod
    def dashboard_template(cls):
        page = super().dashboard_template()
        page = re.sub(r'<!-- full-edition -->.*?<!-- /full-edition -->\s*', '', page, flags=re.DOTALL)
        page = page.replace('<body>', '<body data-client-edition>')
        page = page.replace('<title>Altegio Intelligence · Reports Portal</title>', '<title>Altegio Analytics</title>')
        page = page.replace('<b>Altegio Intelligence</b><small>AI-powered business analytics</small>', '<b>Altegio Analytics</b>')
        page = page.replace('id="upsellExport" type="button">Скачать CSV для рассылки',
                            'id="upsellExport" type="button">Скачать CSV')
        return re.sub(r'<span class="num">0[12]</span>', '', page)


if __name__ == '__main__':
    main(ClientDesktopApplication)

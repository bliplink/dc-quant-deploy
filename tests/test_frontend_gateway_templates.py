"""T543: all frontends use the same deployed Gateway port, never stale GW 33002."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
TEMPLATES={
    'public-web': ('public-web.conf.template', 18094),
    'tenant-web': ('tenant-web.conf.template', 18092),
    'platform-web': ('platform-web.conf.template', 18090),
}

class GatewayTemplateTests(unittest.TestCase):
    def test_all_three_sites_use_runtime_gateway_host_port(self):
        for name,(file,port) in TEMPLATES.items():
            with self.subTest(name=name):
                value=(ROOT/'config/frontend-proxies'/file).read_text()
                self.assertIn(f'listen {port};',value)
                self.assertIn('proxy_pass http://${GATEWAY_HOST}:${GATEWAY_HTTP_PORT};',value)
                self.assertNotIn('proxy_pass http://127.0.0.1:33002;',value)
                self.assertNotIn('proxy_pass http://127.0.0.1:43002;',value)
                self.assertIn('location = /healthz',value)
                self.assertIn('proxy_set_header Host $host;',value)

    def test_compose_mounts_nginx_templates_and_passes_matching_http_port(self):
        content=(ROOT/'compose.yaml').read_text()
        for service,(file,_) in TEMPLATES.items():
            with self.subTest(service=service):
                fragment=re.split(r'\n  [a-z][a-z0-9-]*:\n',
                    content.split(f'  {service}:\n',1)[1],maxsplit=1)[0]
                self.assertIn(f'./config/frontend-proxies/{file}:/etc/nginx/templates/default.conf.template:ro',fragment)
                self.assertIn('GATEWAY_HOST: 127.0.0.1',fragment)
                self.assertIn('GATEWAY_HTTP_PORT: ${GW_HTTP_PORT:-33002}',fragment)

    def test_trade_web_has_dynamic_ws_and_http_ports(self):
        content=(ROOT/'compose.yaml').read_text()
        fragment=content.split('  web:\n',1)[1].split('\n  tenant-web:',1)[0]
        self.assertIn('GATEWAY_HTTP_PORT: ${GW_HTTP_PORT:-33002}',fragment)
        self.assertIn('GATEWAY_WS_PORT: ${GW_WEBSOCKET_PORT:-33001}',fragment)

if __name__=='__main__':
    unittest.main()
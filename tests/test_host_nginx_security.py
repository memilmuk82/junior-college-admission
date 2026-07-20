from __future__ import annotations

import ipaddress
import re
from pathlib import Path

HTTP_CONFIG = Path("deploy/nginx.host-admission-http.conf")
REAL_IP_CONFIG = Path("deploy/nginx.host-admission-cloudflare-realip.conf")
PROXY_CONFIG = Path("deploy/nginx.host-admission-proxy.conf")
SITE_CONFIG = Path("deploy/nginx.host-admission-site.conf")
DEMO_PROXY_CONFIG = Path("deploy/nginx.host-admission-demo-proxy.conf")


def test_host_access_log_is_path_only_and_has_a_bounded_auth_zone() -> None:
    config = HTTP_CONFIG.read_text(encoding="utf-8")
    directives = "\n".join(
        line for line in config.splitlines() if not line.lstrip().startswith("#")
    )

    assert "log_format admission_path_only" in directives
    assert '"$request_method $uri $server_protocol"' in directives
    for query_bearing_variable in ("$request ", "$request_uri", "$args"):
        assert query_bearing_variable not in directives
    assert "Referer" not in directives
    assert "limit_req_zone $binary_remote_addr zone=admission_auth_per_ip:10m rate=20r/m;" in config


def test_cloudflare_real_ip_include_has_only_current_official_ranges() -> None:
    config = REAL_IP_CONFIG.read_text(encoding="utf-8")
    ranges = re.findall(r"^set_real_ip_from ([^;]+);$", config, re.MULTILINE)
    expected = {
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    }

    assert set(ranges) == expected
    assert len(ranges) == len(expected)
    assert all(ipaddress.ip_network(value).is_global for value in ranges)
    assert "real_ip_header CF-Connecting-IP;" in config
    assert "real_ip_recursive on;" in config


def test_host_proxy_normalizes_the_only_trusted_forwarded_hop() -> None:
    config = PROXY_CONFIG.read_text(encoding="utf-8")

    assert "proxy_pass http://127.0.0.1:8000;" in config
    assert "proxy_set_header X-Real-IP $remote_addr;" in config
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in config
    assert "proxy_set_header X-Forwarded-Proto https;" in config
    assert "proxy_set_header X-Forwarded-Host $host;" in config
    assert "proxy_set_header X-Forwarded-Port 443;" in config
    assert "$proxy_add_x_forwarded_for" not in config


def test_demo_proxy_is_loopback_only_and_restores_the_fixed_script_root() -> None:
    proxy = DEMO_PROXY_CONFIG.read_text(encoding="utf-8")
    site = SITE_CONFIG.read_text(encoding="utf-8")

    assert "proxy_pass http://127.0.0.1:8002;" in proxy
    assert "rewrite ^/demo/(.*)$ /$1 break;" in proxy
    assert "proxy_set_header X-Forwarded-Prefix /demo;" in proxy
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in proxy
    assert "$proxy_add_x_forwarded_for" not in proxy
    assert "location = /demo" in site
    assert "location /demo/" in site
    assert site.count("admission-demo-proxy.conf") == 3
    assert "^/demo/auth/(email/verify|password/reset)$" in site
    assert "google/demo-consent" in site


def test_both_vhosts_use_dedicated_logs_and_scoped_cloudflare_trust() -> None:
    config = SITE_CONFIG.read_text(encoding="utf-8")

    assert config.count("server {") == 2
    assert config.count("admission-cloudflare-realip.conf") == 2
    assert config.count("access_log /var/log/nginx/admission.access.log admission_path_only;") == 2
    assert "access_log /var/log/nginx/access.log" not in config


def test_https_vhost_limits_every_public_auth_entrypoint() -> None:
    config = SITE_CONFIG.read_text(encoding="utf-8")

    callback = config.split("location = /auth/google/callback {", 1)[1].split("}", 1)[0]
    public_auth_location = (
        "location ~ ^/(auth/(login|register|google/start|email/resend|password/forgot)"
        "|account/security/(password|email|google/(connect|disconnect))|admin/login)$ {"
    )
    public_auth = config.split(public_auth_location, 1)[1].split("}", 1)[0]
    account_tokens = config.split("location ~ ^/auth/(email/verify|password/reset)$ {", 1)[1].split(
        "}", 1
    )[0]
    directive = "limit_req zone=admission_auth_per_ip burst=10 nodelay;"

    assert directive in callback
    assert "admission.callback.error.log crit" in callback
    assert directive in public_auth
    assert directive in account_tokens
    assert "admission.account-token.error.log crit" in account_tokens
    assert "include /etc/nginx/snippets/admission-proxy.conf;" in callback
    assert "include /etc/nginx/snippets/admission-proxy.conf;" in public_auth
    assert "include /etc/nginx/snippets/admission-proxy.conf;" in account_tokens


def test_http_vhost_redirects_without_reintroducing_combined_logging() -> None:
    config = SITE_CONFIG.read_text(encoding="utf-8")
    http_server = config.rsplit("server {", 1)[1]

    assert "listen 80;" in http_server
    assert "return 308 https://$host$request_uri;" in http_server
    assert "admission_path_only" in http_server


def test_admission_logrotate_policy_is_bounded_and_signals_nginx() -> None:
    config = Path("deploy/logrotate.admission").read_text(encoding="utf-8")

    assert "/var/log/nginx/admission.account-token.error.log" in config
    assert "/var/log/nginx/admission.demo-account-token.error.log" in config
    assert "daily" in config
    assert "rotate 14" in config
    assert "maxsize 10M" in config
    assert "create 0640 www-data adm" in config
    assert "kill -USR1" in config

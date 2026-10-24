"""Generate the 25 benchmark scenario files. Run: python3 -m benchmark.make_scenarios"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "scenarios"
WEB = "Users on the client cannot load the web server at web.anta.local."
VERIFY = ["ping_success", "http_200", "dns_resolves"]
DEV = {"s01", "s02", "s03", "s04", "s05", "s06", "s07", "s10", "s12", "s14", "s18", "s20"}


def route(dev, dest):
    return {"type": "broken_route", "device": dev, "mechanism": "route_delete", "dest": dest}


def fw(dev, proto, port=None, action="DROP", typ="firewall_block"):
    return {"type": typ, "device": dev, "mechanism": "iptables", "chain": "FORWARD",
            "protocol": proto, "port": port, "action": action}


def stop(dev, proc, typ):
    return {"type": typ, "device": dev, "mechanism": "service_stop", "process": proc}


NONE = {"type": "no_fault", "device": None, "mechanism": "none"}
LAYER = {"broken_route": "L3", "firewall_block": "L4", "dns_failure": "APP", "service_failure": "L7", "no_fault": "-"}


def remediation(f):
    m, d = f["mechanism"], f.get("device")
    if f["type"] == "no_fault":
        return None
    return {
        "route_delete": {"action": "restore_route", "device": d, "dest": f.get("dest")},
        "iptables": {"action": "remove_firewall_rule", "device": d},
        "service_stop": {"action": "start_service", "device": d, "service": f.get("process")},
        "nginx_503": {"action": "restore_service_config", "device": d},
        "dns_wrong_ip": {"action": "restore_dns_record", "device": d},
    }[m]


# (id, tier, symptom, description, fault, required evidence finding keys)
SPECS = [
    ("s01", "A_seen", WEB, "Router lost its route to the server subnet", route("router", "10.10.3.0/24"), ["route_complete:router"]),
    ("s02", "A_seen", WEB, "Firewall lost its return route to the client subnet", route("firewall", "10.10.1.0/24"), ["route_complete:firewall"]),
    ("s03", "A_seen", WEB, "Firewall drops tcp/80", fw("firewall", "tcp", 80), ["fw_has_drop:firewall"]),
    ("s04", "A_seen", WEB, "Router drops tcp/80", fw("router", "tcp", 80), ["fw_has_drop:router"]),
    ("s05", "A_seen", WEB, "DNS service stopped", stop("dns-server", "dnsmasq", "dns_failure"), ["svc_up:dns-server:dns"]),
    ("s06", "A_seen", WEB, "Web service stopped", stop("web-server", "nginx", "service_failure"), ["svc_up:web-server:web"]),
    ("s07", "B_variant", WEB, "Client lost its default route", route("client", "default"), ["route_complete:client"]),
    ("s08", "B_variant", WEB, "Web server lost its default route (replies cannot return)", route("web-server", "default"), ["route_complete:web-server"]),
    ("s09", "B_variant", WEB, "DNS server lost its default route (replies cannot return)", route("dns-server", "default"), ["route_complete:dns-server"]),
    ("s10", "B_variant", WEB, "Firewall drops udp/53 (DNS blocked)", fw("firewall", "udp", 53), ["fw_has_drop:firewall"]),
    ("s11", "B_variant", WEB, "Router drops udp/53 (DNS blocked)", fw("router", "udp", 53), ["fw_has_drop:router"]),
    ("s12", "B_variant", "The client cannot ping the web server.", "Firewall drops ICMP", fw("firewall", "icmp"), ["fw_has_drop:firewall"]),
    ("s13", "B_variant", "The client cannot ping the web server.", "Router drops ICMP", fw("router", "icmp"), ["fw_has_drop:router"]),
    ("s14", "B_variant", "Connections from the client to the web server are immediately refused.", "Firewall REJECTs tcp/80 with a reset", fw("firewall", "tcp", 80, "REJECT"), ["fw_has_drop:firewall"]),
    ("s15", "B_variant", "Connections from the client to the web server are immediately refused.", "Router REJECTs tcp/80 with a reset", fw("router", "tcp", 80, "REJECT"), ["fw_has_drop:router"]),
    ("s16", "B_variant", "The web server answers with errors instead of the page.", "Web service up but returns HTTP 503",
     {"type": "service_failure", "device": "web-server", "mechanism": "nginx_503"}, ["svc_local_ok:web-server"]),
    ("s17", "B_variant", "web.anta.local opens nothing even though the web server is up.", "DNS record points to the wrong IP",
     {"type": "dns_failure", "device": "dns-server", "mechanism": "dns_wrong_ip", "wrong_ip": "10.10.3.99"}, ["dns_ip_correct"]),
    ("s18", "C_control", "A user reported they could not load the web server earlier. Please check.", "Healthy network (control)", NONE, []),
    ("s19", "C_control", "The network feels slow. Please check whether anything is broken.", "Healthy network (control)", NONE, []),
    ("s20", "C_control", "Users report intermittent problems reaching web.anta.local.", "Harmless firewall rule (tcp/443) is a distractor",
     fw("firewall", "tcp", 443, typ="no_fault"), []),
    ("s21", "C_control", "Users report intermittent problems reaching web.anta.local.", "Harmless router rule (udp/9999) is a distractor",
     fw("router", "udp", 9999, typ="no_fault"), []),
    ("s22", "A_phrasing", "HTTP requests to the web server are refused.", "Web service stopped (different wording)", stop("web-server", "nginx", "service_failure"), ["svc_up:web-server:web"]),
    ("s23", "A_phrasing", "web.anta.local does not resolve.", "DNS service stopped (different wording)", stop("dns-server", "dnsmasq", "dns_failure"), ["svc_up:dns-server:dns"]),
    ("s24", "A_phrasing", "The client cannot ping any server.", "Router lost its route (different wording)", route("router", "10.10.3.0/24"), ["route_complete:router"]),
    ("s25", "A_phrasing", "The web page hangs forever when opened from the client.", "Firewall drops tcp/80 (different wording)", fw("firewall", "tcp", 80), ["fw_has_drop:firewall"]),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    types = set()
    for sid, tier, symptom, desc, fault, req in SPECS:
        typ = fault["type"]
        if typ != "no_fault":
            types.add(typ)
        sc = {
            "id": sid, "description": desc, "tier": tier, "split": "dev" if sid in DEV else "test",
            "symptom": symptom, "topology": "standard_5node", "injected_fault": fault,
            "ground_truth": {"device": fault.get("device") or "none", "layer": LAYER[typ], "cause": typ,
                             "evidence_required": req},
            "remediation": remediation(fault), "verification_tests": VERIFY,
        }
        (OUT / f"{sid}.json").write_text(json.dumps(sc, indent=2))
    assert len(SPECS) == 25 and len(types) <= 6, "scope cap violated"
    print(f"wrote {len(SPECS)} scenarios to {OUT}")
    print(f"fault types used: {sorted(types)} ({len(types)} of max 6); dev={len(DEV)} test={len(SPECS) - len(DEV)}")


if __name__ == "__main__":
    main()

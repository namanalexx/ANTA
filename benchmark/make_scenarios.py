"""Generate the 25 benchmark scenario files. Run: python3 -m benchmark.make_scenarios"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "scenarios"
WEB = "Users on the client cannot load the web server at web.anta.local."
VERIFY = ["ping_success", "http_200", "dns_resolves"]
DEV = {"s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10", "s12", "s14", "s16", "s17", "s18", "s20"}


def route(dev, dest):
    return {"type": "broken_route", "device": dev, "mechanism": "route_delete", "dest": dest}


def fw(dev, proto, port=None, action="DROP", typ="firewall_block"):
    return {"type": typ, "device": dev, "mechanism": "iptables", "chain": "FORWARD",
            "protocol": proto, "port": port, "action": action}


def stop(dev, proc, typ):
    return {"type": typ, "device": dev, "mechanism": "service_stop", "process": proc}


NONE = {"type": "no_fault", "device": None, "mechanism": "none"}
LAYER = {"broken_route": "L3", "firewall_block": "L4", "dns_failure": "APP", "service_failure": "L7",
         "interface_down": "L2", "link_degradation": "L3", "no_fault": "-"}
STRESS = {f"s{n}" for n in range(36, 46)}  # out-of-library scenarios, kept out of the headline numbers
STRESS_TEST = {f"s{n}" for n in range(46, 52)}  # fresh held-out scenarios for the extended agent
FINAL_SET = {f"s{n}" for n in range(52, 62)}  # final held-out batch, run once on the frozen system


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
        "iptables_policy": {"action": "restore_policy", "device": d},
        "iface_down": {"action": "bring_interface_up", "device": d},
        "netem": {"action": "remove_netem", "device": d},
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
    ("s26", "A_phrasing", "Pings to the web server get no reply.", "Firewall lost its return route (fresh wording)", route("firewall", "10.10.1.0/24"), ["route_complete:firewall"]),
    ("s27", "B_variant", "Name lookups for web.anta.local fail instantly.", "Firewall REJECTs udp/53", fw("firewall", "udp", 53, "REJECT"), ["fw_has_drop:firewall"]),
    ("s28", "B_variant", "Every web connection hangs, but ping works.", "Router drops all TCP", fw("router", "tcp"), ["fw_has_drop:router"]),
    ("s29", "A_phrasing", "Lookups for web.anta.local are being refused.", "DNS service stopped (fresh wording)", stop("dns-server", "dnsmasq", "dns_failure"), ["svc_up:dns-server:dns"]),
    ("s30", "B_variant", "Customers see error pages from the web server.", "Web service returns HTTP 503 (fresh wording)",
     {"type": "service_failure", "device": "web-server", "mechanism": "nginx_503"}, ["svc_local_ok:web-server"]),
    ("s31", "B_variant", "web.anta.local leads to a page that never opens, though the server is healthy.", "DNS record points to a different wrong IP",
     {"type": "dns_failure", "device": "dns-server", "mechanism": "dns_wrong_ip", "wrong_ip": "10.10.1.99"}, ["dns_ip_correct"]),
    ("s32", "C_control", "Page loads feel slow today. Is something broken?", "Healthy network (control)", NONE, []),
    ("s33", "C_control", "Some users report occasional failures reaching web.anta.local.", "Harmless firewall rule (tcp/8080) is a distractor",
     fw("firewall", "tcp", 8080, typ="no_fault"), []),
    ("s34", "B_variant", "The client lost access to everything beyond its own subnet.", "Client lost its default route (fresh wording)", route("client", "default"), ["route_complete:client"]),
    ("s35", "B_variant", "All traffic through the firewall is being silently discarded.", "Firewall FORWARD policy set to DROP",
     {"type": "firewall_block", "device": "firewall", "mechanism": "iptables_policy", "chain": "FORWARD"}, ["fw_has_drop:firewall"]),
    ("s36", "D_unknown", WEB, "Router's client-side interface is down",
     {"type": "interface_down", "device": "router", "mechanism": "iface_down", "subnet": "10.10.1."}, ["iface_up:router"]),
    ("s37", "D_unknown", WEB, "Router's core-side interface is down",
     {"type": "interface_down", "device": "router", "mechanism": "iface_down", "subnet": "10.10.2."}, ["iface_up:router"]),
    ("s38", "D_unknown", WEB, "Firewall's server-side interface is down",
     {"type": "interface_down", "device": "firewall", "mechanism": "iface_down", "subnet": "10.10.3."}, ["iface_up:firewall"]),
    ("s39", "D_unknown", WEB, "Web server's network interface is down",
     {"type": "interface_down", "device": "web-server", "mechanism": "iface_down", "subnet": "10.10.3."}, ["iface_up:web-server"]),
    ("s40", "D_unknown", "Name lookups for web.anta.local fail.", "DNS server's network interface is down",
     {"type": "interface_down", "device": "dns-server", "mechanism": "iface_down", "subnet": "10.10.3."}, ["iface_up:dns-server"]),
    ("s41", "D_unknown", "Users report intermittent failures loading web.anta.local.", "Router drops 40% of packets on its client side",
     {"type": "link_degradation", "device": "router", "mechanism": "netem", "subnet": "10.10.1.", "loss_pct": 40}, ["link_degraded:router"]),
    ("s42", "D_unknown", "Users report the web page loads very slowly.", "Firewall adds 500 ms delay on its core side",
     {"type": "link_degradation", "device": "firewall", "mechanism": "netem", "subnet": "10.10.2.", "delay_ms": 500}, ["link_degraded:firewall"]),
    ("s43", "D_unknown", WEB, "Web server loses 100% of its outgoing packets",
     {"type": "link_degradation", "device": "web-server", "mechanism": "netem", "subnet": "10.10.3.", "loss_pct": 100}, ["link_degraded:web-server"]),
    ("s44", "D_unknown", "Name lookups for web.anta.local take very long.", "DNS server adds 1500 ms delay",
     {"type": "link_degradation", "device": "dns-server", "mechanism": "netem", "subnet": "10.10.3.", "delay_ms": 1500}, ["link_degraded:dns-server"]),
    ("s45", "D_unknown", "Users report intermittent failures loading web.anta.local.", "Firewall drops 60% of packets on its server side",
     {"type": "link_degradation", "device": "firewall", "mechanism": "netem", "subnet": "10.10.3.", "loss_pct": 60}, ["link_degraded:firewall"]),
    ("s46", "D_unknown", WEB, "Firewall's core-side interface is down",
     {"type": "interface_down", "device": "firewall", "mechanism": "iface_down", "subnet": "10.10.2."}, ["iface_up:firewall"]),
    ("s47", "D_unknown", "The client cannot reach anything on the network.", "Client's network interface is down",
     {"type": "interface_down", "device": "client", "mechanism": "iface_down", "subnet": "10.10.1."}, ["iface_up:client"]),
    ("s48", "D_unknown", "Pages sometimes fail to load for users.", "Router drops 30% of packets on its core side",
     {"type": "link_degradation", "device": "router", "mechanism": "netem", "subnet": "10.10.2.", "loss_pct": 30}, ["link_degraded:router"]),
    ("s49", "D_unknown", "The web page loads very slowly.", "Web server adds 800 ms delay",
     {"type": "link_degradation", "device": "web-server", "mechanism": "netem", "subnet": "10.10.3.", "delay_ms": 800}, ["link_degraded:web-server"]),
    ("s50", "D_unknown", WEB, "Client loses 50% of its outgoing packets",
     {"type": "link_degradation", "device": "client", "mechanism": "netem", "subnet": "10.10.1.", "loss_pct": 50}, ["link_degraded:client"]),
    ("s51", "D_unknown", "web.anta.local cannot be resolved from the client.", "DNS server's network interface is down (fresh wording)",
     {"type": "interface_down", "device": "dns-server", "mechanism": "iface_down", "subnet": "10.10.3."}, ["iface_up:dns-server"]),
    ("s52", "E_final", "Nothing passes through the router.", "Router FORWARD policy set to DROP (final batch)",
     {"type": "firewall_block", "device": "router", "mechanism": "iptables_policy", "chain": "FORWARD"}, ["fw_has_drop:router"]),
    ("s53", "E_final", "Name lookups for web.anta.local fail from the client.", "Firewall drops all UDP (final batch)",
     fw("firewall", "udp"), ["fw_has_drop:firewall"]),
    ("s54", "E_final", "web.anta.local shows the wrong site.", "DNS record points at the firewall's address (final batch)",
     {"type": "dns_failure", "device": "dns-server", "mechanism": "dns_wrong_ip", "wrong_ip": "10.10.3.2"}, ["dns_ip_correct"]),
    ("s55", "E_final", "Opening the site gives connection refused.", "Web service stopped (final batch)",
     stop("web-server", "nginx", "service_failure"), ["svc_up:web-server:web"]),
    ("s56", "E_final", "The web server accepts connections but nothing comes back.", "Web server lost its default route (final batch)",
     route("web-server", "default"), ["route_complete:web-server"]),
    ("s57", "E_final", "Servers are unreachable through the router.", "Router's core-side interface is down (final batch)",
     {"type": "interface_down", "device": "router", "mechanism": "iface_down", "subnet": "10.10.2."}, ["iface_up:router"]),
    ("s58", "E_final", "Pages occasionally stall for a few seconds.", "Router drops 10% of packets on its core side (final batch)",
     {"type": "link_degradation", "device": "router", "mechanism": "netem", "subnet": "10.10.2.", "loss_pct": 10}, ["link_degraded:router"]),
    ("s59", "E_final", "Name lookups for web.anta.local often fail.", "DNS server loses 60% of packets (final batch)",
     {"type": "link_degradation", "device": "dns-server", "mechanism": "netem", "subnet": "10.10.3.", "loss_pct": 60}, ["link_degraded:dns-server"]),
    ("s60", "E_final", "Users say the site feels slow sometimes. Is anything wrong?", "Healthy network (final batch control)", NONE, []),
    ("s61", "E_final", "Some users report errors on web.anta.local.", "Harmless firewall rule on tcp/3306 (final batch control)",
     fw("firewall", "tcp", 3306, typ="no_fault"), []),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    types = set()
    for sid, tier, symptom, desc, fault, req in SPECS:
        typ = fault["type"]
        if typ != "no_fault":
            types.add(typ)
        sc = {
            "id": sid, "description": desc, "tier": tier, "split": "dev" if sid in DEV else ("stress" if sid in STRESS else ("stress_test" if sid in STRESS_TEST else ("final" if sid in FINAL_SET else "test"))),
            "symptom": symptom, "topology": "standard_5node", "injected_fault": fault,
            "ground_truth": {"device": "none" if typ == "no_fault" else fault.get("device"), "layer": LAYER[typ], "cause": typ,
                             "evidence_required": req},
            "remediation": remediation(fault), "verification_tests": VERIFY,
        }
        (OUT / f"{sid}.json").write_text(json.dumps(sc, indent=2))
    assert len(SPECS) == 61 and len(types) <= 6, "scope cap violated"
    print(f"wrote {len(SPECS)} scenarios to {OUT}")
    print(f"fault types used: {sorted(types)} ({len(types)} of max 6); dev={len(DEV)} test={len(SPECS) - len(DEV) - len(STRESS) - len(STRESS_TEST) - len(FINAL_SET)} stress={len(STRESS)} stress_test={len(STRESS_TEST)} final={len(FINAL_SET)}")


if __name__ == "__main__":
    main()

"""Run the approved Lab 3 topology through a local GNS3 2.2 API."""

import argparse
from contextlib import ExitStack, contextmanager
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import telnetlib
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile


GNS3 = "http://127.0.0.1:19730/v2"
IOS = "c3640-a3js-mz.124-25d.image"
PROMPT = re.compile(rb"(?m)^\r*[a-zA-Z][\w().-]*[>#] *\r*$")
INITIAL_DIALOG = re.compile(rb"configuration dialog\? \[yes/no\]: *")
ABORT_AUTOINSTALL = re.compile(rb"Terminate autoinstall\? \[yes\]: *", re.I)
IOS_FAILURE = re.compile(r"%\s*(?:Invalid input|Incomplete command|Ambiguous command|Error)")
ROUTER_A = ("202.103.2.1", "202.103.1.1")
ROUTER_B = ("202.103.2.2", "192.168.1.1")
PC_A, PC_B = "202.103.1.2", "192.168.1.2"
MASK = "255.255.255.0"


def stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def api(method, route, body=None, *, raw=False):
    data = None if body is None else json.dumps(body).encode()
    request = Request(
        GNS3 + route, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urlopen(request, timeout=45) as response:
            data = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {route}: HTTP {error.code} {detail}") from error
    return data if raw else (json.loads(data) if data else None)


class Console:
    def __init__(self, node, folder, resources):
        self.name = node["name"]
        self.is_ios = node["node_type"] == "dynamips"
        self.log = resources.enter_context((folder / f"{self.name}.log").open("w", encoding="utf-8"))
        self.telnet = resources.enter_context(telnetlib.Telnet("127.0.0.1", node["console"], 8))
        self.wait_for_boot()
        if self.is_ios:
            self.run("enable")
            self.run("terminal length 0")
            self.configure(
                f"hostname {self.name}", "no ip domain lookup",
                "line con 0", "exec-timeout 0 0", "logging synchronous", "exit",
            )
        else:
            self.run(f"set pcname {self.name}")

    def wait_for_boot(self):
        deadline = time.monotonic() + (145 if self.is_ios else 20)
        while time.monotonic() < deadline:
            self.telnet.write(b"\r")
            choice, _, data = self.telnet.expect([PROMPT, INITIAL_DIALOG, ABORT_AUTOINSTALL], 8)
            self.record("boot console", data)
            if choice == 0:
                return
            if choice in (1, 2):
                self.telnet.write(b"no\r" if choice == 1 else b"yes\r")
        raise RuntimeError(f"{self.name}: no opening prompt")

    def record(self, label, output):
        value = output.decode("utf-8", "replace")
        self.log.write(f"\n[{stamp()}] {self.name}> {label}\n{value.replace(chr(13), '')}\n")
        self.log.flush()
        return value

    def wait(self, timeout):
        index, _, output = self.telnet.expect([PROMPT], timeout)
        if index < 0:
            return self.record("prompt timeout", output), False
        return output, True

    def run(self, command, timeout=15):
        pending = self.telnet.read_very_eager()
        if pending:
            self.record("async", pending)
        self.telnet.write(command.encode("ascii") + b"\r")
        output, ok = self.wait(timeout)
        if not ok:
            raise RuntimeError(f"{self.name}: prompt timeout after {command!r}: {output[-160:]}")
        value = self.record(command, output)
        if self.is_ios and IOS_FAILURE.search(value):
            raise RuntimeError(f"{self.name}: rejected {command!r}: {value}")
        return value

    def configure(self, *commands):
        self.run("configure terminal")
        for command in commands:
            self.run(command)
        self.run("end")

    def save(self, folder):
        if self.is_ios:
            running = self.run("show running-config")
            (folder / f"{self.name}-running.txt").write_text(running, encoding="utf-8")
            self.run("write memory", 30)
        else:
            self.run("show ip")
            self.run("save")


class Project:
    def __init__(self, name, folder):
        self.name = name
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=False)
        self.info = api("POST", "/projects", {"name": name, "show_interface_labels": True})
        self.route = f"/projects/{self.info['project_id']}"
        self.nodes = {}
        self.configuration = folder / "topology-notes.log"

    def event(self, message):
        line = f"{stamp()} {message}"
        print(line, flush=True)
        with self.configuration.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def add_node(self, name, kind, x, y, module=None):
        symbol = {"vpcs": "vpcs_guest", "dynamips": "router"}[kind]
        properties = {}
        if module:
            properties = {
                "platform": "c3600", "chassis": "3640", "image": IOS,
                "ram": 128, "idlepc": "0x6050b114", "slot0": module,
                "startup_config_content": (
                    f"!\nhostname {name}\nno service config\nno ip domain lookup\n"
                    "line con 0\n exec-timeout 0 0\n logging synchronous\nend\n"
                ),
            }
            if module == "NM-16ESW":
                symbol = "ethernet_switch"
                properties["disk0"] = 1
        result = api("POST", self.route + "/nodes", {
            "name": name, "node_type": kind, "compute_id": "local",
            "x": x, "y": y, "symbol": f":/symbols/{symbol}.svg",
            "console_type": "telnet", "properties": properties,
        })
        self.nodes[name] = result
        self.event(f"node {name} {kind} {module or ''} console={result['console']}")
        return result

    def link(self, a, a_port, b, b_port):
        endpoints = []
        for name, port in ((a, a_port), (b, b_port)):
            node = self.nodes[name]
            match = next(p for p in node["ports"] if p["name"] == port)
            endpoints.append({
                "node_id": node["node_id"],
                "adapter_number": match["adapter_number"], "port_number": match["port_number"],
            })
        link = api("POST", self.route + "/links", {"nodes": endpoints})
        self.event(f"link {a}:{a_port} <-> {b}:{b_port} {link['link_id']}")
        return link["link_id"]

    def node_action(self, node, action):
        endpoint = "start" if action == "resume" else action
        result = api("POST", f"{self.route}/nodes/{self.nodes[node]['node_id']}/{endpoint}", {})
        self.event(f"{node} {action}: {result.get('status', 'ok') if result else 'ok'}")

    @contextmanager
    def consoles(self):
        try:
            api("POST", self.route + "/nodes/start", {})
            self.event("all nodes started")
            with ExitStack() as resources:
                yield {
                    node["name"]: Console(node, self.folder, resources)
                    for node in api("GET", self.route + "/nodes")
                }
        finally:
            api("POST", self.route + "/nodes/stop", {})
            self.event("all nodes stopped")

    def export(self):
        target = self.folder / (self.name + ".gns3project")
        target.write_bytes(api("GET", self.route + "/export?include_images=no", raw=True))
        with ZipFile(target) as bundle:
            assert bundle.testzip() is None
            assert any(name.endswith(".gns3") for name in bundle.namelist())
        self.event(f"export verified {target.name}")
        api("POST", self.route + "/close", {})


def wait_until(action, test, *, seconds, pause=2):
    end = time.monotonic() + seconds
    while True:
        data = action()
        if test(data):
            return data
        if time.monotonic() >= end:
            raise RuntimeError(f"Condition did not pass: {data[-350:]}")
        time.sleep(pause)


def ping(node, ip):
    if node.is_ios:
        value = node.run(f"ping {ip} repeat 2 timeout 1", 12)
        match = re.search(r"Success rate is (\d+) percent", value)
        if not match:
            raise RuntimeError(f"{node.name}: unrecognized IOS ping result: {value}")
        return int(match.group(1)) > 0
    value = node.run(f"ping {ip} -c 2", 13)
    if re.search(r"invalid|usage", value, re.I):
        raise RuntimeError(f"{node.name}: unrecognized VPCS ping command: {value}")
    return bool(re.search(r"\bbytes from " + re.escape(ip) + r"\b", value, re.I))


def matrix(project, phase, probes):
    failed = []
    with (project.folder / "ping-matrix.csv").open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if handle.tell() == 0:
            writer.writerow(("phase", "source", "destination", "expected", "observed"))
        for source, destination, expected in probes:
            result = ping(source, destination)
            writer.writerow((phase, source.name, destination, int(expected), int(result)))
            if expected != result:
                failed.append((source.name, destination, expected, result))
    project.event(f"{phase}: {'FAIL ' + repr(failed) if failed else 'PASS'}")
    if failed:
        raise RuntimeError(f"{phase} ping mismatch: {failed}")


def switch_vlan(node):
    node.run("vlan database")
    node.run("vlan 200 name VLAN200")
    node.run("vlan 300 name VLAN300")
    node.run("exit")
    for port, vlan in enumerate((200, 200, 300)):
        node.configure(
            f"interface FastEthernet0/{port}", "switchport mode access",
            f"switchport access vlan {vlan}", "no shutdown", "exit",
        )
    node.run("show vlan-switch brief")
    node.run("show interfaces FastEthernet0/0 switchport")


def switching(folder, suffix, subnet):
    project = Project(f"NL3-{suffix}-Switching", folder)
    for name, x in (("SW1", -210), ("SW2", 210)):
        project.add_node(name, "dynamips", x, -110, "NM-16ESW")
    for number, x in enumerate((-300, -125, 125, 300), 1):
        project.add_node(f"PC{number}", "vpcs", x, 90)
    project.link("SW1", "FastEthernet0/0", "SW2", "FastEthernet0/0")
    for n in range(1, 5):
        switch = "SW1" if n < 3 else "SW2"
        port = (n + 1) % 2 + 1
        project.link(switch, f"FastEthernet0/{port}", f"PC{n}", "Ethernet0")

    with project.consoles() as consoles:
        switches = [consoles[name] for name in ("SW1", "SW2")]
        pcs = [consoles[f"PC{i}"] for i in range(1, 5)]
        for switch in switches:
            switch.configure("no ip routing")
            version = switch.run("show version")
            assert "12.4(25d)" in version
            switch.run("show ip interface brief")
        project.event("NM-16ESW slot 0, FastEthernet0/0-15, and VPCS startup verified")
        full = [f"192.168.{subnet}.{host}" for host in (11, 12, 21, 22)]
        changed = full[:3] + [f"192.168.{subnet + 2}.22"]
        split = [full[0], f"192.168.{subnet}.140", full[2], f"192.168.{subnet}.150"]
        phases = (
            ("same-/24", full, 24, (1, 1, 1, 1)),
            ("PC4-other-subnet", changed, 24, (1, 1, 1, 2)),
            ("two-/25", split, 25, (1, 2, 1, 2)),
            ("VLAN-200-300", full, 24, (1, 2, 1, 3)),
        )
        for phase, addresses, prefix, groups in phases:
            project.event(phase + ": configuring and probing")
            for node, ip in zip(pcs, addresses):
                node.run(f"ip {ip}/{prefix}")
                node.run("show ip")
            if phase.startswith("VLAN"):
                for switch in switches:
                    switch_vlan(switch)
            wait_until(lambda: ping(pcs[0], addresses[2]), bool, seconds=55)
            probes = (
                (pcs[i], addresses[j], groups[i] == groups[j])
                for i in range(4) for j in range(i + 1, 4)
            )
            matrix(project, phase, probes)
        for node in consoles.values():
            node.save(folder)
    project.export()


def routes(project, consoles, phase, code=None):
    for name, remote in (("R1", "192.168.1.0"), ("R2", "202.103.1.0")):
        output = consoles[name].run("show ip route")
        (project.folder / f"{phase}-{name}-routes.txt").write_text(output, encoding="utf-8")
        if code and not re.search(rf"(?m)^{code}\s+{re.escape(remote)}(?:/|\s)", output):
            raise RuntimeError(f"{name} missing expected {code} route to {remote}")


def routing(folder, suffix, mode):
    project = Project(f"NL3-{suffix}-{mode}", folder)
    project.add_node("R1", "dynamips", -110, -25, "NM-4E")
    project.add_node("R2", "dynamips", 110, -25, "NM-4E")
    project.add_node("PC1", "vpcs", -310, 55)
    project.add_node("PC2", "vpcs", 315, 55)
    project.link("PC1", "Ethernet0", "R1", "Ethernet0/1")
    interconnect = project.link("R1", "Ethernet0/0", "R2", "Ethernet0/0")
    project.link("R2", "Ethernet0/1", "PC2", "Ethernet0")
    with project.consoles() as c:
        for router, addresses in ((c["R1"], ROUTER_A), (c["R2"], ROUTER_B)):
            for i, address in enumerate(addresses):
                router.configure(
                    f"interface Ethernet0/{i}", f"ip address {address} {MASK}", "no shutdown", "exit",
                )
            router.run("show ip interface brief")
        c["PC1"].run(f"ip {PC_A}/24 {ROUTER_A[1]}")
        c["PC2"].run(f"ip {PC_B}/24 {ROUTER_B[1]}")
        wait_until(lambda: ping(c["R1"], ROUTER_B[0]), bool, seconds=20)
        routes(project, c, "01-direct")
        matrix(project, "direct", [
            (c["PC1"], PC_B, False), (c["PC1"], ROUTER_A[0], True),
            (c["PC1"], ROUTER_A[1], True), (c["PC2"], ROUTER_B[0], True),
            (c["PC2"], ROUTER_B[1], True), (c["R1"], ROUTER_B[0], True),
            (c["R1"], ROUTER_B[1], False), (c["R2"], ROUTER_A[0], True),
            (c["R2"], ROUTER_A[1], False),
        ])

        if mode == "Static":
            c["R1"].configure(f"ip route 192.168.1.0 {MASK} {ROUTER_B[0]}")
            routes(project, c, "02-one-side")
            matrix(project, "one-sided", [(c["PC1"], ROUTER_B[0], False), (c["PC1"], PC_B, False)])
            c["R2"].configure(f"ip route 202.103.1.0 {MASK} {ROUTER_A[0]}")
            routes(project, c, "03-static", "S")
            matrix(project, "two-sided", [
                (c["PC1"], PC_B, True), (c["PC2"], PC_A, True),
                (c["PC1"], ROUTER_B[0], True), (c["PC1"], ROUTER_A[0], True),
                (c["PC1"], ROUTER_A[1], True), (c["PC2"], ROUTER_B[0], True),
                (c["PC2"], ROUTER_B[1], True), (c["R1"], ROUTER_B[0], True),
                (c["R1"], ROUTER_B[1], True), (c["R2"], ROUTER_A[0], True),
                (c["R2"], ROUTER_A[1], True),
            ])
        else:
            dynamic_routing(project, c, mode, interconnect)
        for device in c.values():
            device.save(folder)
    project.export()


def dynamic_routing(project, c, mode, interconnect):
    rip = mode == "RIP"
    for name, local in (("R1", "202.103.1.0"), ("R2", "192.168.1.0")):
        if rip:
            c[name].configure(
                "router rip", "version 2", "no auto-summary",
                f"network {local}", "network 202.103.2.0", "exit",
            )
        else:
            c[name].configure(
                "router ospf 1", f"network {local} 0.0.0.255 area 0",
                "network 202.103.2.0 0.0.0.255 area 0", "exit",
            )
        c[name].run("show ip protocols")
    route_line = re.compile(rf"(?m)^{('R' if rip else 'O')}\s+192\.168\.1\.0")
    wait_until(lambda: c["R1"].run("show ip route"), route_line.search, seconds=65)
    if not rip:
        for name in ("R1", "R2"):
            assert "FULL/" in c[name].run("show ip ospf neighbor")
    routes(project, c, "02-learned", "R" if rip else "O")
    matrix(project, "learned", [(c["PC1"], PC_B, True), (c["PC2"], PC_A, True)])
    if not rip:
        return

    relink = ("R1", "Ethernet0/0", "R2", "Ethernet0/0")
    for name in ("R1", "R2"):
        project.node_action(name, "suspend")
    api("DELETE", f"{project.route}/links/{interconnect}")
    project.event("physical topology link deleted while both routers suspended")
    for name in ("R1", "R2"):
        project.node_action(name, "resume")
    withdrawal = project.folder / "03-RIP-withdrawal.txt"
    # IOS timers can lag wall time when the emulator is sharing the host.
    # Keep the IOS defaults and wait until both route tables confirm removal.
    end = time.monotonic() + 420
    while True:
        first = c["R1"].run("show ip route")
        second = c["R2"].run("show ip route")
        missing = (
            not route_line.search(first),
            not re.search(r"(?m)^R\s+202\.103\.1\.0", second),
        )
        with withdrawal.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{stamp()} learned routes absent {missing}\nR1\n{first}\nR2\n{second}\n")
        if all(missing):
            break
        if time.monotonic() >= end:
            raise RuntimeError("RIP routes did not withdraw within observation window")
        project.event(f"waiting for RIP withdrawal, absent={missing}")
        time.sleep(15)
    routes(project, c, "03-withdrawn")
    matrix(project, "link-removed", [(c["PC1"], PC_B, False)])
    for name in ("R1", "R2"):
        project.node_action(name, "suspend")
    project.link(*relink)
    for name in ("R1", "R2"):
        project.node_action(name, "resume")
        c[name].run("debug ip rip")
    wait_until(lambda: c["R1"].run("show ip route"), route_line.search, seconds=70)
    routes(project, c, "04-restored", "R")
    matrix(project, "link-restored", [(c["PC1"], PC_B, True), (c["PC2"], PC_A, True)])
    update = re.compile(r"RIP: (?:received|sending)", re.I)
    def observed_update():
        c["R1"].run("show clock")
        c["R2"].run("show clock")
        return "".join((project.folder / f"{n}.log").read_text(encoding="utf-8") for n in ("R1", "R2"))
    wait_until(observed_update, update.search, seconds=46, pause=5)
    for name in ("R1", "R2"):
        c[name].run("undebug all")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="New output directory for one round")
    parser.add_argument("round", choices=("A", "B"))
    parser.add_argument("steps", nargs="*", choices=("switch", "Static", "RIP", "OSPF"))
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    suffix = args.round + "-" + datetime.now().strftime("%H%M%S")
    if "switch" in args.steps:
        switching(args.root / "01-switching", suffix, 30 if args.round == "A" else 31)
    for index, mode in enumerate(("Static", "RIP", "OSPF"), 2):
        if mode in args.steps:
            routing(args.root / f"0{index}-{mode.lower()}", suffix, mode)


if __name__ == "__main__":
    main()

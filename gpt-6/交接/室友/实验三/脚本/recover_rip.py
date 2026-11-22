from pathlib import Path
import re
import sys
from run_lab3 import Project, api, ROUTER_A, ROUTER_B, MASK, PC_A, PC_B, matrix, routes, ping, wait_until

folder, project_id = Path(sys.argv[1]), sys.argv[2]
project = Project.__new__(Project)
project.route = f"/projects/{project_id}"
project.info = api("GET", project.route)
project.name = project.info["name"]
project.folder = folder
project.configuration = folder / "topology-notes.log"
project.nodes = {node["name"]: node for node in api("GET", project.route + "/nodes")}
for path in folder.glob("*.log"):
    if path.stem in project.nodes and not path.with_name(path.stem + "-before-recovery.log").exists():
        path.rename(path.with_name(path.stem + "-before-recovery.log"))
project.event("recovery: hot reconnect did not restore RIP; restarting nodes in the same reconnected project")
with project.consoles() as c:
    for name, addresses, local in (("R1", ROUTER_A, "202.103.1.0"), ("R2", ROUTER_B, "192.168.1.0")):
        router = c[name]
        router.run("debug ip rip")
        for i, address in enumerate(addresses):
            router.configure(f"interface Ethernet0/{i}", f"ip address {address} {MASK}", "no shutdown", "exit")
        router.configure("router rip", "version 2", "no auto-summary", f"network {local}", "network 202.103.2.0", "exit")
    c["PC1"].run(f"ip {PC_A}/24 {ROUTER_A[1]}")
    c["PC2"].run(f"ip {PC_B}/24 {ROUTER_B[1]}")
    wait_until(lambda: ping(c["R1"], ROUTER_B[0]), bool, seconds=30)
    wait_until(lambda: c["R1"].run("show ip route"), re.compile(r"(?m)^R\s+192\.168\.1\.0").search, seconds=80)
    wait_until(lambda: c["R2"].run("show ip route"), re.compile(r"(?m)^R\s+202\.103\.1\.0").search, seconds=90)
    routes(project, c, "04-restored", "R")
    for endpoint, gateway, remote in ((c["PC1"], ROUTER_A[1], PC_B), (c["PC2"], ROUTER_B[1], PC_A)):
        wait_until(lambda: ping(endpoint, gateway), bool, seconds=25)
        wait_until(lambda: ping(endpoint, remote), bool, seconds=50)
    matrix(project, "link-restored", [(c["PC1"], PC_B, True), (c["PC2"], PC_A, True)])
    for name in ("R1", "R2"):
        wait_until(lambda: c[name].run("show clock") or "", lambda _: bool(re.search(
            r"RIP: received v2 update from 202\.103\.2\.[12] on Ethernet0/0",
            (folder / f"{name}.log").read_text(encoding="utf-8")
        )), seconds=45)
        c[name].run("undebug all")
    for device in c.values():
        device.save(folder)
project.export()



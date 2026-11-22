from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4
import json, re, socket, sys, time
from run_lab3 import Project, api, GNS3, ping, switch_vlan, wait_until, MASK, ROUTER_A, ROUTER_B, PC_A, PC_B

tag, delivery = sys.argv[1], Path(sys.argv[2])
work = Path(__file__).parent / ('native-proof-' + tag)
work.mkdir(exist_ok=True)
checkpoint = work / 'checkpoint.json'
port = 19742 if tag == 'A' else 19743
listener=socket.create_server(('127.0.0.1',port))
listener.settimeout(100)
print(tag,'PuTTY feed ready',port,flush=True)
screen,_=listener.accept()
screen.sendall(f'\x1b]0;GNS3 Lab3 {tag} Live Console\x07'.encode())
logs=work / 'runs'
logs.mkdir(exist_ok=True)
subnet = 30 if tag == 'A' else 31
links={}

def text(raw):
    screen.sendall(raw.encode('utf-8','replace'))

def proof(name, tests):
    text('\x1b[2J\x1b[H')
    for console, command in tests:
        result=console.run(command)
        # Preserve Cisco IOS/VPCS command echo and the exact device response.
        text(result.strip('\r\n')+'\r\n\r\n')
    (work/'checkpoint.tmp').write_text(json.dumps({'name':name,'time':datetime.now().isoformat()}),encoding='utf-8')
    (work/'checkpoint.tmp').replace(checkpoint)
    print(tag,'awaiting capture',name,flush=True)
    end=time.monotonic()+240
    while not (work / (name+'.jpg')).exists():
        if time.monotonic()>end:
            print(tag,'capture timed out for',name,flush=True)
            break
        time.sleep(0.4)

def make(project_key):
    path, = sorted(delivery.rglob('*'+project_key+'.gns3project'))
    project=Project.__new__(Project)
    project.route='/projects/'+str(uuid4())
    with urlopen(Request(GNS3+project.route+'/import',data=path.read_bytes(),method='POST',headers={'Content-Type':'application/octet-stream'}), timeout=35):
        pass
    if api('GET',project.route)['status']!='opened':
        api('POST', project.route+'/open', {})
    project.info=api('GET',project.route)
    project.nodes={n['name']:n for n in api('GET',project.route+'/nodes')}
    project.folder=logs/project_key
    project.folder.mkdir(exist_ok=True)
    project.configuration=project.folder/'topology-notes.log'
    print(tag,project_key, project.info['project_id'],flush=True)
    return project

def close(project):
    if api('GET',project.route)['status']=='opened':
        api('POST',project.route+'/close',{})

def hit(console, dest, wanted=True):
    if wanted:
        wait_until(lambda: ping(console,dest), bool, seconds=65)
    else:
        assert not ping(console,dest)

def address(last, segment=None):
    return f'192.168.{segment if segment is not None else subnet}.{last}'

p=make('Switching')
try:
    with p.consoles() as c:
        for name in ('SW1','SW2'):
            for port_number in range(3):
                c[name].configure(f'interface FastEthernet0/{port_number}', 'switchport access vlan 1', 'exit')
        def set_ip(values,prefix):
            for i, ip in enumerate(values,1):
                c[f'PC{i}'].run(f'ip {ip}/{prefix}')
        original=[address(n) for n in (11,12,21,22)]
        set_ip(original,24)
        hit(c['PC1'],original[3])
        proof('01-switch-same-subnet',[(c['PC1'],'show ip'),(c['PC1'],f'ping {original[3]} -c 2')])
        other=address(22,subnet+2)
        c['PC4'].run(f'ip {other}/24')
        proof('02-switch-different-subnet',[(c['PC4'],'show ip'),(c['PC1'],f'ping {other} -c 2'),(c['PC1'],f'ping {original[2]} -c 2')])
        split=[original[0],address(140),original[2],address(150)]
        set_ip(split,25)
        hit(c['PC2'],split[3])
        proof('03-switch-two-subnets',[(c['PC2'],'show ip'),(c['PC2'],f'ping {split[3]} -c 2'),(c['PC1'],f'ping {split[3]} -c 2')])
        set_ip(original,24)
        for name in ('SW1','SW2'):
            switch_vlan(c[name])
            proof('04-vlan-'+name,[(c[name],'show vlan-switch brief')])
        hit(c['PC1'],original[2])
        hit(c['PC2'],original[3],False)
        proof('05-vlan-connectivity',[(c['PC1'],f'ping {original[2]} -c 2'),(c['PC2'],f'ping {original[3]} -c 2')])
finally:
    close(p)

p=make('Static')
try:
    with p.consoles() as c:
        s1=f'ip route 192.168.1.0 {MASK} {ROUTER_B[0]}'
        s2=f'ip route 202.103.1.0 {MASK} {ROUTER_A[0]}'
        c['R1'].configure('no '+s1)
        c['R2'].configure('no '+s2)
        proof('06-static-connected', [(c['R1'],'show ip route connected'),(c['R2'],'show ip route connected'),(c['PC1'],f'ping {PC_B} -c 2')])
        c['R1'].configure(s1)
        proof('07-static-one-side',[(c['R1'],'show ip route static'),(c['R2'],'show ip route static'),(c['PC1'],f'ping {ROUTER_B[0]} -c 2')])
        c['R2'].configure(s2)
        hit(c['PC1'],PC_B)
        hit(c['PC2'],PC_A)
        proof('08-static-two-sides',[(c['R1'],'show ip route static'),(c['R2'],'show ip route static'),(c['PC1'],f'ping {PC_B} -c 2'),(c['PC2'],f'ping {PC_A} -c 2')])
finally:
    close(p)

p=make('RIP')
remote={'R1':'192.168.1.0','R2':'202.103.1.0'}
def learned(c,name):
    return bool(re.search(rf'(?m)^R\s+{re.escape(remote[name])}',c[name].run('show ip route rip')))
def rip_probes(c,phase):
    proof(phase,[(c['R1'],'show ip route rip'),(c['R2'],'show ip route rip'),(c['PC1'],f'ping {PC_B} -c 2'),(c['PC2'],f'ping {PC_A} -c 2')])
try:
    with p.consoles() as c:
        hit(c['PC1'],PC_B)
        hit(c['PC2'],PC_A)
        rip_probes(c,'09-rip-before-disconnect')
        pinfo=api('GET',p.route+'/links')
        router_ids={p.nodes[n]['node_id'] for n in remote}
        linkid=next(link['link_id'] for link in pinfo if {n['node_id'] for n in link['nodes']}==router_ids)
        for name in remote: p.node_action(name,'suspend')
        api('DELETE',p.route+'/links/'+linkid)
        p.event('inter-router link removed')
        for name in remote: p.node_action(name,'resume')
        end=time.monotonic()+460
        while True:
            present=[learned(c,name) for name in remote]
            p.event(f'learned routes present {present}')
            if not any(present): break
            if time.monotonic()>end: raise RuntimeError('RIP withdraw timeout')
            time.sleep(15)
        rip_probes(c,'10-rip-withdrawn')
        for name in remote: p.node_action(name,'suspend')
        new_link=p.link('R1','Ethernet0/0','R2','Ethernet0/0')
        for name in remote: p.node_action(name,'resume')
        # The earlier run stopped here for restart. Try reprogramming the NIO while both nodes are running.
        api('DELETE',p.route+'/links/'+new_link)
        p.link('R1','Ethernet0/0','R2','Ethernet0/0')
        for name in remote: c[name].run('debug ip rip')
        try:
            for name in remote:
                wait_until(lambda: learned(c,name), bool, seconds=55, pause=4)
            hit(c['PC1'],PC_B)
            hit(c['PC2'],PC_A)
            p.event('RIP hot reattach passed after programming link on running nodes')
            rip_probes(c,'11-rip-restored')
        except RuntimeError:
            p.event('RIP hot reattach did not converge')
    if not (work/'11-rip-restored.jpg').exists():
        with p.consoles() as c:
            for name in remote: c[name].run('debug ip rip')
            hit(c['PC1'],PC_B)
            hit(c['PC2'],PC_A)
            p.event('RIP recovered after node restart')
            rip_probes(c,'11-rip-restored')
finally:
    close(p)

p=make('OSPF')
try:
    with p.consoles() as c:
        hit(c['PC1'],PC_B)
        hit(c['PC2'],PC_A)
        for name in ('R1','R2'):
            proof('12-ospf-'+name,[(c[name],'show ip ospf neighbor'),(c[name],'show ip route ospf')])
        proof('13-ospf-connectivity',[(c['PC1'],f'ping {PC_B} -c 2'),(c['PC2'],f'ping {PC_A} -c 2')])
finally:
    close(p)
print(tag,'native screenshot run finished',flush=True)
screen.close()
listener.close()

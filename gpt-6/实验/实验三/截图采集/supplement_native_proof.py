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
logs=work / 'supplement'
logs.mkdir(exist_ok=True)
subnet = 30 if tag == 'A' else 31
links={}

def text(raw):
    screen.sendall(raw.encode('utf-8','replace'))

def proof(name, tests):
    text('\x1b[2J\x1b[H')
    for console, command in tests:
        result=wait_until(lambda: console.run(command), lambda reply: command in reply, seconds=15)
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
            answer=wait_until(lambda: c[name].run('show vlan-switch brief'),
                lambda plain: '200  VLAN200' in plain and '300  VLAN300' in plain and 'Fa0/0, Fa0/1' in plain, seconds=35)
            proof('14-vlan-ports-'+name,[(c[name],'show vlan-switch brief')])
finally:
    close(p)

p=make('RIP')
try:
    with p.consoles() as c:
        hit(c['PC1'], PC_B)
        hit(c['PC2'], PC_A)
        router_ids={p.nodes[n]['node_id'] for n in ('R1','R2')}
        linkid=next(link['link_id'] for link in api('GET',p.route+'/links') if {n['node_id'] for n in link['nodes']}==router_ids)
        for name in ('R1','R2'): p.node_action(name,'suspend')
        api('DELETE',p.route+'/links/'+linkid)
        p.event('inter-router link removed for new camera capture')
        for name in ('R1','R2'): p.node_action(name,'resume')
        end=time.monotonic()+460
        while True:
            entries=[bool(re.search(r'(?m)^R\s+',c[name].run('show ip route rip'))) for name in ('R1','R2')]
            p.event(f'learned routes present {entries}')
            if not any(entries): break
            if time.monotonic()>end: raise RuntimeError('RIP withdraw timeout')
            time.sleep(15)
        proof('10-rip-withdrawn-tables',[(c['R1'],'show ip route rip'),(c['R2'],'show ip route rip'),(c['PC1'],f'ping {PC_B} -c 1')])
        for name in ('R1','R2'): p.node_action(name,'suspend')
        new_link=p.link('R1','Ethernet0/0','R2','Ethernet0/0')
        for name in ('R1','R2'): p.node_action(name,'resume')
        api('DELETE',p.route+'/links/'+new_link)
        p.link('R1','Ethernet0/0','R2','Ethernet0/0')
        hit(c['PC1'],PC_B)
        hit(c['PC2'],PC_A)
        p.event('RIP hot reattach passed; no node reboot')
        proof('11-rip-restored-tables',[(c['R1'],'show ip route rip'),(c['R2'],'show ip route rip'),(c['PC1'],f'ping {PC_B} -c 2'),(c['PC2'],f'ping {PC_A} -c 2')])
        for name in ('R1','R2'):
            c[name].run('debug ip rip')
            c[name].telnet.read_very_eager()
        for name in ('R1','R2'):
            device=c[name]
            peer = '202.103.2.2' if name=='R1' else '202.103.2.1'
            sent=b''
            limit=time.monotonic()+75
            while not (b'via Ethernet0/0' in sent and ('received v2 update from '+peer).encode() in sent):
                sent+=device.telnet.read_very_eager()
                if time.monotonic()>limit:
                    raise RuntimeError('RIP debug updates missing for '+name)
                time.sleep(.65)
            sent=sent[sent.find(b'RIP:'):]
            text('\x1b[2J\x1b[H')
            screen.sendall(sent)
            name='15-rip-debug-'+name
            (work/'checkpoint.tmp').write_text(json.dumps({'name':name,'time':datetime.now().isoformat()}),encoding='utf-8')
            (work/'checkpoint.tmp').replace(checkpoint)
            end=time.monotonic()+165
            print(tag,'awaiting capture',name,flush=True)
            while not (work/(name+'.jpg')).exists() and time.monotonic()<end:
                time.sleep(.4)
        for name in ('R1','R2'):
            c[name].run('undebug all')
finally:
    close(p)
print(tag,'native screenshot supplement finished',flush=True)
screen.close()
listener.close()


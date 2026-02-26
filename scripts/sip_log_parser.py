import re
import requests

LOG_FILE = './sip-logs.log'
NGINX_ENDPOINT = 'http://localhost:8000/api/logs'


def infer_id(message, module):
    m = re.search(r'sip:[^@>\s]+@(?P<domain>[^\s>]+)', message, re.IGNORECASE)
    if m:
        return m.group('domain')
    m_ip = re.search(r'from\s+(?P<ip>\d+\.\d+\.\d+\.\d+)', message, re.IGNORECASE)
    if m_ip:
        return m_ip.group('ip')
    return module


def parse_sip_logs():
    pattern = re.compile(r'\[(INFO|NOTICE|WARNING|ERROR|CRIT|ALERT)\] (.+?):(.+?) (.+)')
    with open(LOG_FILE, 'r') as file:
        for line in file:
            # try to extract event timestamp at start of the sip log line
            evt_ts = None
            m_ts = re.match(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)", line)
            if m_ts:
                # convert "YYYY-MM-DD HH:MM:SS.mmm" -> "YYYY-MM-DDTHH:MM:SS.mmm"
                evt_ts = m_ts.group('ts').replace(' ', 'T')

            match = pattern.search(line)
            if match:
                level, module, code, message = match.groups()
                svc_id = infer_id(message, module)
                payload = {
                    'id': svc_id,
                    'level': level,
                    'module': module,
                    'code': code,
                    'message': message
                }
                if evt_ts:
                    payload['evt_ts'] = evt_ts
                try:
                    response = requests.get(NGINX_ENDPOINT, params=payload)
                    if response.status_code == 200:
                        print(f"Logged: {payload['id']} level={level}")
                    else:
                        print(f"Failed to log: {payload}, HTTP {response.status_code}")
                except Exception as e:
                    print(f"Error sending log: {e}")


if __name__ == '__main__':
    parse_sip_logs()
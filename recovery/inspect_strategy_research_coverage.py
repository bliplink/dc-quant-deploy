"""Read-only coverage of production 15m bars available for independent research windows."""

import base64
import os
from pathlib import Path

import paramiko


QUERY = """SELECT securityID,min(startTime),max(startTime),count()
FROM dc.kline_view
WHERE lowerUTF8(text)='15m'
  AND securityID IN ('ADAUSDT','BNBUSDT','BTCUSDT','DOGEUSDT','ETHUSDT',
                     'LINKUSDT','SOLUSDT','TRXUSDT','UNIUSDT','XRPUSDT')
GROUP BY securityID ORDER BY securityID"""

SCENE_QUERY = """SELECT symbol,min(run_time),max(run_time),count()
FROM dc.deepseek_market_scene_analysis
WHERE symbol IN ('ADAUSDT','BNBUSDT','BTCUSDT','DOGEUSDT','ETHUSDT',
                 'LINKUSDT','SOLUSDT','TRXUSDT','UNIUSDT','XRPUSDT')
  AND ((analysis_type='deepseek_market_scene' AND prompt_version='deepseek_market_scene_v3')
    OR (analysis_type='historical_kline_scene' AND prompt_version='market_scene_v3_historical_kline_v1'))
GROUP BY symbol ORDER BY symbol"""


def query(client, sql):
    encoded = base64.b64encode(sql.encode('utf-8')).decode('ascii')
    _, stdout, stderr = client.exec_command(
        'printf %s ' + encoded +
        ' | base64 -d | sudo docker exec -i dc-clickhouse clickhouse-client --format TSV',
        timeout=120)
    result = stdout.read().decode('utf-8', 'replace')
    error = stderr.read().decode('utf-8', 'replace')
    if stdout.channel.recv_exit_status():
        raise RuntimeError(error[:2000])
    return result


def main():
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect('18.140.45.126', username='ec2-user',
                   key_filename=str(Path.home() / 'Desktop' / 'id_rsa_2048'),
                   passphrase=os.environ['STC_PROD_KEY_PASSPHRASE'],
                   look_for_keys=False, allow_agent=False, timeout=20)
    try:
        print('clickhouse_timezone\t' + query(client, 'SELECT timezone()').strip())
        print('securityID\tfirst_15m\tlast_15m\trows')
        print(query(client, QUERY), end='')
        print('symbol\tfirst_scene\tlast_scene\trows')
        print(query(client, SCENE_QUERY), end='')
    finally:
        client.close()


if __name__ == '__main__':
    main()

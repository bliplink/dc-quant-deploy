"""Export read-only 15m bars and scene labels for local strategy research."""

import argparse
import base64
import os
from pathlib import Path

import paramiko


SYMBOLS = ('ADAUSDT', 'BNBUSDT', 'BTCUSDT', 'DOGEUSDT', 'ETHUSDT',
           'LINKUSDT', 'SOLUSDT', 'TRXUSDT', 'UNIUSDT', 'XRPUSDT')


def export_query(client, sql, path):
    encoded = base64.b64encode(sql.encode('utf-8')).decode('ascii')
    command = ('printf %s ' + encoded + ' | base64 -d | '
               'sudo docker exec -i dc-clickhouse clickhouse-client --format TSV')
    _, stdout, stderr = client.exec_command(command, timeout=600)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as stream:
        while True:
            chunk = stdout.channel.recv(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
    error = stderr.read().decode('utf-8', 'replace').strip()
    status = stdout.channel.recv_exit_status()
    if status:
        path.unlink(missing_ok=True)
        raise RuntimeError('Export failed for ' + path.name + ': ' + error[:2000])
    print(path.name, path.stat().st_size, 'bytes', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='18.140.45.126')
    parser.add_argument('--user', default='ec2-user')
    parser.add_argument('--key', default=str(Path.home() / 'Desktop' / 'id_rsa_2048'))
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    args = parser.parse_args()
    for value in (args.start_date, args.end_date):
        if len(value) != 10 or value[4] != '-' or value[7] != '-' or not value.replace('-', '').isdigit():
            parser.error('Dates must be YYYY-MM-DD')
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username=args.user, key_filename=args.key,
                   passphrase=os.environ['STC_PROD_KEY_PASSPHRASE'],
                   look_for_keys=False, allow_agent=False, timeout=20,
                   banner_timeout=20, auth_timeout=20)
    output = Path(args.output_dir)
    try:
        for symbol in SYMBOLS:
            export_query(client,
                         "SELECT startTime, toFloat64(open), toFloat64(high), toFloat64(low), "
                         "toFloat64(close), toFloat64(volume) FROM dc.kline FINAL "
                         "WHERE upper(text)='15M' AND securityID='%s' AND close IS NOT NULL "
                         "AND startTime>=toDateTime('%s 00:00:00') "
                         "AND startTime<toDateTime('%s 00:00:00')+INTERVAL 1 DAY "
                         "ORDER BY startTime" % (symbol, args.start_date, args.end_date),
                         output / (symbol + '-15m.tsv'))
            export_query(client,
                         "SELECT run_time, scene, status, analysis_type, prompt_version "
                         "FROM dc.deepseek_market_scene_analysis "
                         "WHERE symbol='%s' AND run_time>=toDateTime('%s 00:00:00') "
                         "AND run_time<toDateTime('%s 00:00:00')+INTERVAL 1 DAY "
                         "AND ((analysis_type='deepseek_market_scene' AND "
                         "prompt_version='deepseek_market_scene_v3') OR "
                         "(analysis_type='historical_kline_scene' AND "
                         "prompt_version='market_scene_v3_historical_kline_v1')) "
                         "ORDER BY run_time" % (symbol, args.start_date, args.end_date),
                         output / (symbol + '-scenes.tsv'))
    finally:
        client.close()


if __name__ == '__main__':
    main()

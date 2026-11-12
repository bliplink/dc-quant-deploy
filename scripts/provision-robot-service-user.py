#!/usr/bin/env python3
"""Idempotently provision the existing Robot service identity in a selected SaaS MySQL.

Use the same identity for the Robot's PLATFORM/Manager Gateway login and its
ROBOT_RUNTIME API login. No extra password, privileged platform-admin account,
or per-tenant credentials are created. Secrets are read from a protected env
file, never passed on the CLI or emitted in the result.
"""
import argparse
import hashlib
import os
import re
import subprocess
from pathlib import Path

NAME = re.compile(r"[A-Za-z0-9_.@-]{3,45}\Z")
KEY = re.compile(r"[A-Za-z0-9]{32,64}\Z")
CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def read_env(path):
    values = {}
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name in ("ROBOT_RUNTIME_USER_ID", "ROBOT_RUNTIME_LOCATION",
                        "ROBOT_RUNTIME_API_KEY", "ROBOT_RUNTIME_API_SECRET"):
                values[name] = value.strip().strip('"').strip("'")
    return values


def identity(values):
    user = values.get("ROBOT_RUNTIME_USER_ID") or "robotsvr"
    location = values.get("ROBOT_RUNTIME_LOCATION") or "PLATFORM"
    key = values.get("ROBOT_RUNTIME_API_KEY", "")
    secret = values.get("ROBOT_RUNTIME_API_SECRET", "")
    if not NAME.fullmatch(user) or location != "PLATFORM" or not KEY.fullmatch(key) or not KEY.fullmatch(secret):
        raise ValueError("ROBOT_SERVICE_IDENTITY_INVALID_OR_MISSING")
    if key == secret:
        raise ValueError("ROBOT_API_KEY_MUST_DIFFER_FROM_SECRET")
    return user, location, key, secret


def sql_for(user, location, key, secret):
    # All dynamic SQL fields have been validated against closed allow-lists.
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return """START TRANSACTION;
INSERT INTO dc_users(user_id,user_name,name,password,user_type,enable,remark,
  create_time,update_time,enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES('{user}','{user}','Robot Gateway Service','{digest}','1','1',
  'Internal PLATFORM Robot gateway and runtime identity',NOW(3),NOW(3),
  '0','0','0','provision-robot-service-user','{location}')
ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',
  update_time=NOW(3),close_by='provision-robot-service-user';
UPDATE dc_users_api SET enable='0',update_time=DATE_FORMAT(NOW(3),'%Y-%m-%d %H:%i:%s.%f'),
  close_by='provision-robot-service-user'
WHERE location='{location}' AND user_id='{user}' AND api_key<>'{key}' AND type='ROBOT_RUNTIME';
INSERT INTO dc_users_api(user_id,type,api_key,secret_key,enable,create_time,
  update_time,close_by,inf1,location)
VALUES('{user}','ROBOT_RUNTIME','{key}','{secret}','1',
  DATE_FORMAT(NOW(3),'%Y-%m-%d %H:%i:%s.%f'),
  DATE_FORMAT(NOW(3),'%Y-%m-%d %H:%i:%s.%f'),
  'provision-robot-service-user','GW-only Robot runtime','{location}')
ON DUPLICATE KEY UPDATE secret_key=VALUES(secret_key),enable='1',
  update_time=VALUES(update_time),close_by='provision-robot-service-user',
  location=VALUES(location);
COMMIT;
SELECT 'ROBOT_USER_COUNT',COUNT(*) FROM dc_users
 WHERE location='{location}' AND user_id='{user}' AND enable='1';
SELECT 'ROBOT_API_COUNT',COUNT(*) FROM dc_users_api
 WHERE location='{location}' AND user_id='{user}' AND api_key='{key}'
   AND secret_key='{secret}' AND type='ROBOT_RUNTIME' AND enable='1';
""".format(user=user, location=location, key=key, secret=secret, digest=digest)


def sql_probe(user, location, key, secret):
    """Read only; decide whether LoginSvr should reload the API cache."""
    return ("""SELECT 'ROBOT_USER_COUNT',COUNT(*) FROM dc_users
 WHERE location='{location}' AND user_id='{user}' AND enable='1'
 AND password='{digest}';
SELECT 'ROBOT_API_COUNT',COUNT(*) FROM dc_users_api
 WHERE location='{location}' AND user_id='{user}' AND api_key='{key}'
 AND secret_key='{secret}' AND type='ROBOT_RUNTIME' AND enable='1';
""".format(user=user, location=location, key=key, secret=secret,
             digest=hashlib.sha256(secret.encode("utf-8")).hexdigest()))


def mysql_run(container, sql):
    # The root password stays INSIDE the MySQL container's environment. No
    # credential appears in host argv, logs, tracebacks, or repo files.
    command = ("exec mysql --protocol=TCP -h127.0.0.1 -uroot -N dc")
    process = subprocess.run(
        ["docker", "exec", "-i", container, "sh", "-c",
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" ' + command],
        input=sql, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=35, check=False)
    if process.returncode:
        raise RuntimeError("ROBOT_SERVICE_USER_MYSQL_OPERATION_FAILED")
    return process.stdout


def counts(output):
    found = {}
    for line in output.splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 2 and parts[0] in ("ROBOT_USER_COUNT", "ROBOT_API_COUNT"):
            found[parts[0]] = parts[1]
    return found.get("ROBOT_USER_COUNT") == "1" and found.get("ROBOT_API_COUNT") == "1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--mysql-container", required=True)
    args = parser.parse_args()
    if not CONTAINER.fullmatch(args.mysql_container):
        raise ValueError("INVALID_MYSQL_CONTAINER_NAME")
    user, location, key, secret = identity(read_env(args.env_file))
    before = counts(mysql_run(args.mysql_container, sql_probe(user, location, key, secret)))
    after = counts(mysql_run(args.mysql_container, sql_for(user, location, key, secret)))
    if not after:
        raise RuntimeError("ROBOT_SERVICE_USER_DB_VERIFICATION_FAILED")
    print("ROBOT_GATEWAY_SERVICE_USER_READY user={} location={} apiKey=redacted changed={} credentialsPrinted=false".format(
        user, location, str(not before).lower()))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        # No raw MySQL stderr or SQL is ever included in errors.
        print("ROBOT_GATEWAY_SERVICE_USER_NO_GO: {}".format(type(error).__name__ + ": " + str(error)),
              file=__import__("sys").stderr)
        raise SystemExit(2)
